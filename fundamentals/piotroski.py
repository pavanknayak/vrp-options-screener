"""
fundamentals/piotroski.py — Piotroski F-Score computation (9 binary factors).

All factors derived from PRD §10. When prior-year data is unavailable for a
YoY factor, that factor conservatively scores 0.

Exports:
    piotroski_f_score(financials: dict) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Return numerator / denominator, or None if either is None or denominator is 0."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def piotroski_f_score(financials: dict) -> dict:
    """Compute the Piotroski F-Score (0-9) from extended EDGAR financials.

    Args:
        financials: dict from fetch_edgar_financials_extended(). May be empty
                    (ETF case) — returns all-zero result without raising.

    Returns:
        {
            "f1": int,   # ROA > 0
            "f2": int,   # CFO > 0
            "f3": int,   # ROA improving YoY
            "f4": int,   # Accrual: CFO/TA > ROA
            "f5": int,   # Leverage decreased YoY
            "f6": int,   # Current ratio improved YoY
            "f7": int,   # No new shares issued
            "f8": int,   # Gross margin expanded YoY
            "f9": int,   # Asset turnover increased YoY
            "total": int,
            "details": dict[str, str],  # factor_name -> brief explanation
            "data_quality": str,        # "full" | "partial" | "empty"
        }
    """
    _zero = {
        "f1": 0, "f2": 0, "f3": 0, "f4": 0, "f5": 0,
        "f6": 0, "f7": 0, "f8": 0, "f9": 0,
        "total": 0,
        "details": {},
        "data_quality": "empty",
    }

    if not financials:
        return _zero

    # Extract fields — all may be None
    net_income: Optional[float] = financials.get("net_income")
    cfo: Optional[float] = financials.get("cfo")
    total_assets: Optional[float] = financials.get("total_assets")
    prior_total_assets: Optional[float] = financials.get("prior_total_assets")
    long_term_debt: Optional[float] = financials.get("long_term_debt")
    prior_long_term_debt: Optional[float] = financials.get("prior_long_term_debt")
    current_assets: Optional[float] = financials.get("current_assets")
    current_liabilities: Optional[float] = financials.get("current_liabilities")
    prior_current_assets: Optional[float] = financials.get("prior_current_assets")
    prior_current_liabilities: Optional[float] = financials.get("prior_current_liabilities")
    shares_outstanding: Optional[float] = financials.get("shares_outstanding")
    prior_shares_outstanding: Optional[float] = financials.get("prior_shares_outstanding")
    gross_profit: Optional[float] = financials.get("gross_profit")
    prior_gross_profit: Optional[float] = financials.get("prior_gross_profit")
    revenue: Optional[float] = financials.get("revenue")
    prior_revenue: Optional[float] = financials.get("prior_revenue")
    prior_net_income: Optional[float] = financials.get("prior_net_income")

    details: dict[str, str] = {}
    scores: dict[str, int] = {}

    # --- Profitability (4 points) ---

    # F1: ROA > 0  (ROA = Net Income / Total Assets, current year)
    roa_current = _safe_div(net_income, total_assets)
    if roa_current is not None:
        scores["f1"] = 1 if roa_current > 0 else 0
        details["f1"] = f"ROA={roa_current:.4f} ({'pass' if scores['f1'] else 'fail'})"
    else:
        scores["f1"] = 0
        details["f1"] = "ROA unavailable (net_income or total_assets missing)"

    # F2: CFO > 0
    if cfo is not None:
        scores["f2"] = 1 if cfo > 0 else 0
        details["f2"] = f"CFO={cfo:.0f} ({'pass' if scores['f2'] else 'fail'})"
    else:
        scores["f2"] = 0
        details["f2"] = "CFO unavailable"

    # F3: ROA increasing YoY  (ROA_current > ROA_prior)
    roa_prior = _safe_div(prior_net_income, prior_total_assets)
    if roa_current is not None and roa_prior is not None:
        scores["f3"] = 1 if roa_current > roa_prior else 0
        details["f3"] = f"ROA current={roa_current:.4f} vs prior={roa_prior:.4f} ({'pass' if scores['f3'] else 'fail'})"
    else:
        scores["f3"] = 0
        details["f3"] = "ROA YoY unavailable (prior year data missing) — conservative 0"

    # F4: Accrual quality: CFO/Total Assets > ROA
    cfo_ta = _safe_div(cfo, total_assets)
    if cfo_ta is not None and roa_current is not None:
        scores["f4"] = 1 if cfo_ta > roa_current else 0
        details["f4"] = f"CFO/TA={cfo_ta:.4f} vs ROA={roa_current:.4f} ({'pass' if scores['f4'] else 'fail'})"
    else:
        scores["f4"] = 0
        details["f4"] = "Accrual quality unavailable — conservative 0"

    # --- Leverage / Liquidity (3 points) ---

    # F5: Long-term debt ratio decreased YoY  (LTD/TA_current < LTD/TA_prior)
    ltd_ta_current = _safe_div(long_term_debt, total_assets)
    ltd_ta_prior = _safe_div(prior_long_term_debt, prior_total_assets)
    if ltd_ta_current is not None and ltd_ta_prior is not None:
        scores["f5"] = 1 if ltd_ta_current < ltd_ta_prior else 0
        details["f5"] = f"LTD/TA current={ltd_ta_current:.4f} vs prior={ltd_ta_prior:.4f} ({'pass' if scores['f5'] else 'fail'})"
    else:
        scores["f5"] = 0
        details["f5"] = "Leverage YoY unavailable — conservative 0"

    # F6: Current ratio improved YoY  ((CA/CL)_current > (CA/CL)_prior)
    cr_current = _safe_div(current_assets, current_liabilities)
    cr_prior = _safe_div(prior_current_assets, prior_current_liabilities)
    if cr_current is not None and cr_prior is not None:
        scores["f6"] = 1 if cr_current > cr_prior else 0
        details["f6"] = f"CR current={cr_current:.4f} vs prior={cr_prior:.4f} ({'pass' if scores['f6'] else 'fail'})"
    else:
        scores["f6"] = 0
        details["f6"] = "Current ratio YoY unavailable — conservative 0"

    # F7: No new shares issued  (shares_current <= shares_prior * 1.01)
    if shares_outstanding is not None and prior_shares_outstanding is not None:
        scores["f7"] = 1 if shares_outstanding <= prior_shares_outstanding * 1.01 else 0
        details["f7"] = f"Shares current={shares_outstanding:.0f} vs prior={prior_shares_outstanding:.0f} ({'pass' if scores['f7'] else 'fail'})"
    else:
        scores["f7"] = 0
        details["f7"] = "Shares YoY unavailable — conservative 0"

    # --- Operating Efficiency (2 points) ---

    # F8: Gross margin expanded YoY  (GM_current > GM_prior where GM = Gross Profit / Revenue)
    gm_current = _safe_div(gross_profit, revenue)
    gm_prior = _safe_div(prior_gross_profit, prior_revenue)
    if gm_current is not None and gm_prior is not None:
        scores["f8"] = 1 if gm_current > gm_prior else 0
        details["f8"] = f"GM current={gm_current:.4f} vs prior={gm_prior:.4f} ({'pass' if scores['f8'] else 'fail'})"
    else:
        scores["f8"] = 0
        details["f8"] = "Gross margin YoY unavailable — conservative 0"

    # F9: Asset turnover increased YoY  ((Revenue/TA)_current > (Revenue/TA)_prior)
    at_current = _safe_div(revenue, total_assets)
    at_prior = _safe_div(prior_revenue, prior_total_assets)
    if at_current is not None and at_prior is not None:
        scores["f9"] = 1 if at_current > at_prior else 0
        details["f9"] = f"AT current={at_current:.4f} vs prior={at_prior:.4f} ({'pass' if scores['f9'] else 'fail'})"
    else:
        scores["f9"] = 0
        details["f9"] = "Asset turnover YoY unavailable — conservative 0"

    total = sum(scores.values())

    # Determine data quality
    if roa_current is not None and cfo is not None and roa_prior is not None:
        data_quality = "full"
    elif roa_current is not None or cfo is not None:
        data_quality = "partial"
    else:
        data_quality = "empty"

    logger.debug(
        "Piotroski F-Score for %s: %d/9 (quality=%s)",
        financials.get("ticker", "?"), total, data_quality,
    )

    return {
        "f1": scores["f1"],
        "f2": scores["f2"],
        "f3": scores["f3"],
        "f4": scores["f4"],
        "f5": scores["f5"],
        "f6": scores["f6"],
        "f7": scores["f7"],
        "f8": scores["f8"],
        "f9": scores["f9"],
        "total": total,
        "details": details,
        "data_quality": data_quality,
    }
