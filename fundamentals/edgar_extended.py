"""
fundamentals/edgar_extended.py — Extended SEC EDGAR fetcher with prior-year fields.

Builds on data/edgar_fetcher.py to expose current AND prior-year financials
required for Piotroski F-Score YoY comparisons.

Exports:
    fetch_edgar_financials_extended(ticker) -> dict
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests

from cache.db import TTL, get_db
from data.edgar_fetcher import _get_cik_map, _HEADERS, _COMPANY_FACTS_URL, _latest_annual_value, _latest_annual_value_any

logger = logging.getLogger(__name__)


def _prior_annual_value(facts: dict, concept: str) -> Optional[float]:
    """Return the SECOND-MOST-RECENT 10-K value for a us-gaap concept, or None.

    Used for Piotroski YoY comparisons. If fewer than two annual filings
    exist for the concept, returns None (conservative: factor scores 0).
    """
    try:
        units = facts["us-gaap"][concept]["units"]
        unit_data: list[dict] = units.get("USD") or units.get("shares") or []
        annual = [
            entry for entry in unit_data
            if entry.get("form") in ("10-K", "10-K/A")
        ]
        if len(annual) < 2:
            return None
        # Sort by 'end' date descending; second entry is prior year
        sorted_annual = sorted(annual, key=lambda e: e.get("end", ""), reverse=True)
        return float(sorted_annual[1]["val"])
    except (KeyError, TypeError, ValueError):
        return None


def _prior_annual_value_any(facts: dict, *concepts: str) -> Optional[float]:
    """Try each concept in order; return first non-None prior-year result."""
    for concept in concepts:
        val = _prior_annual_value(facts, concept)
        if val is not None:
            return val
    return None


def fetch_edgar_financials_extended(ticker: str) -> dict:
    """Fetch current + prior-year fundamentals for Piotroski and MOS scoring.

    Returns a superset of fetch_edgar_financials() adding prior-year fields
    and balance-sheet items needed by Phase 4 scoring models.

    New fields (on top of base fetcher):
        prior_revenue, prior_net_income, prior_cfo, prior_total_assets,
        prior_total_debt, prior_shares_outstanding,
        current_assets, current_liabilities,
        prior_current_assets, prior_current_liabilities,
        gross_profit, prior_gross_profit,
        tax_expense, retained_earnings, working_capital,
        long_term_debt, prior_long_term_debt

    Returns {} if the ticker is not in EDGAR (ETFs, foreign companies) or
    any unrecoverable error occurs. Never raises.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_edgar_extended_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for EDGAR extended %s", ticker)
        return cached

    try:
        cik_map = _get_cik_map()
        cik = cik_map.get(ticker)
        if not cik:
            logger.info(
                "Ticker %s not found in EDGAR CIK map (likely ETF or foreign)", ticker
            )
            return {}

        time.sleep(0.15)
        url = _COMPANY_FACTS_URL.format(cik=cik)
        resp = requests.get(url, headers=_HEADERS, timeout=60)
        if resp.status_code == 404:
            logger.info(
                "Ticker %s (CIK %s) has no EDGAR companyfacts", ticker, cik
            )
            return {}
        resp.raise_for_status()
        facts = resp.json().get("facts", {})

        # --- Current year ---
        revenue = _latest_annual_value_any(
            facts,
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        )
        net_income = _latest_annual_value(facts, "NetIncomeLoss")
        cfo = _latest_annual_value(facts, "NetCashProvidedByUsedInOperatingActivities")
        capex_raw = _latest_annual_value(facts, "PaymentsToAcquirePropertyPlantAndEquipment")
        capex = abs(capex_raw) if capex_raw is not None else None
        fcf: Optional[float] = (cfo - capex) if (cfo is not None and capex is not None) else None

        long_term_debt = _latest_annual_value(facts, "LongTermDebt")
        short_term_debt = _latest_annual_value(facts, "ShortTermBorrowings")
        total_debt: Optional[float] = (
            (long_term_debt or 0.0) + (short_term_debt or 0.0)
            if (long_term_debt is not None or short_term_debt is not None)
            else None
        )
        total_assets = _latest_annual_value(facts, "Assets")
        book_value = _latest_annual_value_any(
            facts, "StockholdersEquity", "RetainedEarningsAccumulatedDeficit"
        )
        interest_expense = _latest_annual_value(facts, "InterestExpense")
        shares_outstanding = _latest_annual_value(facts, "CommonStockSharesOutstanding")

        # Balance sheet items for Piotroski and MOS
        current_assets = _latest_annual_value(facts, "AssetsCurrent")
        current_liabilities = _latest_annual_value(facts, "LiabilitiesCurrent")
        gross_profit = _latest_annual_value(facts, "GrossProfit")
        tax_expense = _latest_annual_value_any(
            facts, "IncomeTaxExpenseBenefit", "CurrentIncomeTaxExpenseBenefit"
        )
        retained_earnings = _latest_annual_value(facts, "RetainedEarningsAccumulatedDeficit")

        working_capital: Optional[float] = (
            (current_assets - current_liabilities)
            if (current_assets is not None and current_liabilities is not None)
            else None
        )

        # Fiscal year end
        fiscal_year_end: Optional[str] = None
        try:
            for concept in (
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "NetIncomeLoss",
            ):
                unit_data = (
                    facts.get("us-gaap", {})
                    .get(concept, {})
                    .get("units", {})
                    .get("USD", [])
                )
                annual = [e for e in unit_data if e.get("form") in ("10-K", "10-K/A")]
                if annual:
                    latest = max(annual, key=lambda e: e.get("end", ""))
                    fiscal_year_end = latest.get("end")
                    break
        except Exception:
            pass

        # --- Prior year ---
        prior_revenue = _prior_annual_value_any(
            facts,
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        )
        prior_net_income = _prior_annual_value(facts, "NetIncomeLoss")
        prior_cfo = _prior_annual_value(facts, "NetCashProvidedByUsedInOperatingActivities")
        prior_long_term_debt = _prior_annual_value(facts, "LongTermDebt")
        prior_short_term_debt = _prior_annual_value(facts, "ShortTermBorrowings")
        prior_total_debt: Optional[float] = (
            (prior_long_term_debt or 0.0) + (prior_short_term_debt or 0.0)
            if (prior_long_term_debt is not None or prior_short_term_debt is not None)
            else None
        )
        prior_total_assets = _prior_annual_value(facts, "Assets")
        prior_shares_outstanding = _prior_annual_value(facts, "CommonStockSharesOutstanding")
        prior_current_assets = _prior_annual_value(facts, "AssetsCurrent")
        prior_current_liabilities = _prior_annual_value(facts, "LiabilitiesCurrent")
        prior_gross_profit = _prior_annual_value(facts, "GrossProfit")

        result = {
            # Identity
            "ticker": ticker,
            "cik": cik,
            "fiscal_year_end": fiscal_year_end,
            # Current year — income statement
            "revenue": revenue,
            "net_income": net_income,
            "cfo": cfo,
            "fcf": fcf,
            "gross_profit": gross_profit,
            "tax_expense": tax_expense,
            # Current year — balance sheet
            "total_assets": total_assets,
            "total_debt": total_debt,
            "long_term_debt": long_term_debt,
            "book_value": book_value,
            "retained_earnings": retained_earnings,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "working_capital": working_capital,
            "interest_expense": interest_expense,
            "shares_outstanding": shares_outstanding,
            # Prior year
            "prior_revenue": prior_revenue,
            "prior_net_income": prior_net_income,
            "prior_cfo": prior_cfo,
            "prior_total_assets": prior_total_assets,
            "prior_total_debt": prior_total_debt,
            "prior_long_term_debt": prior_long_term_debt,
            "prior_shares_outstanding": prior_shares_outstanding,
            "prior_current_assets": prior_current_assets,
            "prior_current_liabilities": prior_current_liabilities,
            "prior_gross_profit": prior_gross_profit,
        }

        get_db().set(cache_key, result, TTL["fundamentals"])
        logger.info(
            "Fetched EDGAR extended for %s: net_income=%s, cfo=%s, prior_net_income=%s",
            ticker, net_income, cfo, prior_net_income,
        )
        return result

    except Exception as exc:
        logger.error("fetch_edgar_financials_extended(%s) failed: %s", ticker, exc)
        return {}
