"""
data/edgar_fetcher.py — SEC EDGAR XBRL fundamental financials fetcher.

No authentication required. Rate limit: 10 req/sec (we sleep 0.15 s between requests).
Required header: User-Agent identifying the application.

Exports:
    fetch_edgar_financials(ticker) -> dict
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests

from cache.db import TTL, get_db

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "VRP Options Screener personal-use@local.dev"}
_CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_CIK_CACHE_KEY = "edgar_cik_map_global"
_CIK_TTL = 604800  # 7 days

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_cik_map() -> dict[str, str]:
    """Return {TICKER: zero-padded-10-digit-CIK} mapping from SEC, cached 7 days."""
    cached = get_db().get(_CIK_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        time.sleep(0.15)
        resp = requests.get(_CIK_MAP_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        raw: dict = resp.json()
        # SEC format: {0: {"cik_str": int, "ticker": str, "title": str}, ...}
        cik_map = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in raw.values()
            if "ticker" in entry and "cik_str" in entry
        }
        get_db().set(_CIK_CACHE_KEY, cik_map, _CIK_TTL)
        logger.info("EDGAR CIK map loaded: %d tickers", len(cik_map))
        return cik_map
    except Exception as exc:
        logger.error("Failed to fetch EDGAR CIK map: %s", exc)
        return {}


def _latest_annual_value(facts: dict, concept: str) -> Optional[float]:
    """Return the most recent 10-K value for a us-gaap concept, or None.

    Args:
        facts:   The full company facts dict from EDGAR.
        concept: e.g. "Revenues", "NetIncomeLoss" (without us-gaap: prefix).
    """
    try:
        units = facts["us-gaap"][concept]["units"]
        # Most concepts report in USD; some (e.g. shares) use shares
        unit_data: list[dict] = units.get("USD") or units.get("shares") or []
        annual = [
            entry for entry in unit_data
            if entry.get("form") in ("10-K", "10-K/A")
        ]
        if not annual:
            return None
        # Most recent by 'end' date
        latest = max(annual, key=lambda e: e.get("end", ""))
        return float(latest["val"])
    except (KeyError, TypeError, ValueError):
        return None


def _latest_annual_value_any(facts: dict, *concepts: str) -> Optional[float]:
    """Try each concept in order; return first non-None result."""
    for concept in concepts:
        val = _latest_annual_value(facts, concept)
        if val is not None:
            return val
    return None


# ---------------------------------------------------------------------------
# Public fetcher
# ---------------------------------------------------------------------------


def fetch_edgar_financials(ticker: str) -> dict:
    """Fetch fundamental financials for *ticker* from SEC EDGAR XBRL.

    Returns a dict with keys:
        ticker, cik, revenue, net_income, cfo, fcf, total_debt,
        total_assets, book_value, interest_expense, shares_outstanding,
        fiscal_year_end

    Returns {} if the ticker is not in EDGAR (e.g., ETFs, foreign companies)
    or if any unrecoverable error occurs.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_edgar_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for EDGAR %s", ticker)
        return cached

    try:
        cik_map = _get_cik_map()
        cik = cik_map.get(ticker)
        if not cik:
            logger.info("Ticker %s not found in EDGAR CIK map (likely ETF or foreign)", ticker)
            return {}

        time.sleep(0.15)
        url = _COMPANY_FACTS_URL.format(cik=cik)
        resp = requests.get(url, headers=_HEADERS, timeout=60)
        if resp.status_code == 404:
            logger.info(
                "Ticker %s (CIK %s) has no EDGAR XBRL companyfacts (ETF or non-filer)",
                ticker,
                cik,
            )
            return {}
        resp.raise_for_status()
        data = resp.json()

        facts = data.get("facts", {})

        # Revenue — try both common GAAP concepts
        revenue = _latest_annual_value_any(
            facts,
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        )

        # Core income statement / cash flow items
        net_income = _latest_annual_value(facts, "NetIncomeLoss")
        cfo = _latest_annual_value(facts, "NetCashProvidedByUsedInOperatingActivities")

        # CapEx (reported as negative outflow by GAAP, use abs())
        capex_raw = _latest_annual_value(facts, "PaymentsToAcquirePropertyPlantAndEquipment")
        capex = abs(capex_raw) if capex_raw is not None else None

        # Free cash flow
        if cfo is not None and capex is not None:
            fcf: Optional[float] = cfo - capex
        else:
            fcf = None

        # Balance sheet items
        long_term_debt = _latest_annual_value(facts, "LongTermDebt")
        short_term_debt = _latest_annual_value(facts, "ShortTermBorrowings")
        if long_term_debt is not None or short_term_debt is not None:
            total_debt: Optional[float] = (long_term_debt or 0.0) + (short_term_debt or 0.0)
        else:
            total_debt = None

        total_assets = _latest_annual_value(facts, "Assets")
        book_value = _latest_annual_value_any(
            facts,
            "StockholdersEquity",
            "RetainedEarningsAccumulatedDeficit",
        )
        interest_expense = _latest_annual_value(facts, "InterestExpense")
        shares_outstanding = _latest_annual_value(facts, "CommonStockSharesOutstanding")

        # Fiscal year end — derive from the revenue or net_income filing's 'end' date
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

        result = {
            "ticker": ticker,
            "cik": cik,
            "revenue": revenue,
            "net_income": net_income,
            "cfo": cfo,
            "fcf": fcf,
            "total_debt": total_debt,
            "total_assets": total_assets,
            "book_value": book_value,
            "interest_expense": interest_expense,
            "shares_outstanding": shares_outstanding,
            "fiscal_year_end": fiscal_year_end,
        }

        get_db().set(cache_key, result, TTL["fundamentals"])
        logger.info(
            "Fetched EDGAR financials for %s (CIK %s): revenue=%s, net_income=%s",
            ticker,
            cik,
            revenue,
            net_income,
        )
        return result

    except Exception as exc:
        logger.error("fetch_edgar_financials(%s) failed: %s", ticker, exc)
        return {}
