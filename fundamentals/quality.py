"""
fundamentals/quality.py — Quality of Earnings and Margin of Safety scoring.

Quality of Earnings:
    qoe = CFO / Net Income
    Flag accrual_anomaly when qoe < 0.8
    Flag negative_cfo (hard disqualifier) when CFO < 0 and Net Income > 0

Margin of Safety (MOS) — 6 factors, score 0-100:
    Factor 1: Earnings yield premium (E/P - r_free)         weight=25%
    Factor 2: Price-to-Tangible Book Value (P/TBV)          weight=20%
    Factor 3: Interest coverage (EBIT / Interest)           weight=20%
    Factor 4: FCF yield (FCF / Market Cap)                  weight=15%
    Factor 5: Debt / Tangible Equity                        weight=10%
    Factor 6: Revenue growth YoY                            weight=10%

Exports:
    quality_of_earnings(financials: dict) -> dict
    margin_of_safety(financials, market_price, shares, r_free) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Linear interpolation helper (clamps to [0, 100])
# ---------------------------------------------------------------------------

def _linear_score(value: float, low: float, high: float, invert: bool = False) -> float:
    """Map value linearly from [low, high] to [0, 100], clamped.

    If invert=True, lower value -> higher score (e.g., P/TBV, D/E).
    """
    if high == low:
        return 0.0
    if invert:
        # low value -> score 100; high value -> score 0
        raw = (high - value) / (high - low) * 100.0
    else:
        # low value -> score 0; high value -> score 100
        raw = (value - low) / (high - low) * 100.0
    return max(0.0, min(100.0, raw))


# ---------------------------------------------------------------------------
# Quality of Earnings
# ---------------------------------------------------------------------------

def quality_of_earnings(financials: dict) -> dict:
    """Compute Quality of Earnings ratio (CFO / Net Income) and anomaly flags.

    Args:
        financials: dict from fetch_edgar_financials_extended(). May be empty.

    Returns:
        {
            "qoe": float | None,
            "accrual_anomaly": bool,
            "negative_cfo": bool,
            "flags": list[str],
            "skip_reason": str | None,
        }
    """
    _empty = {
        "qoe": None,
        "accrual_anomaly": False,
        "negative_cfo": False,
        "flags": [],
        "skip_reason": "no_data",
    }

    if not financials:
        return _empty

    cfo: Optional[float] = financials.get("cfo")
    net_income: Optional[float] = financials.get("net_income")

    if cfo is None or net_income is None:
        return _empty

    flags: list[str] = []
    accrual_anomaly = False
    negative_cfo = False

    # Hard disqualifier: CFO negative while NI positive
    if cfo < 0 and net_income > 0:
        negative_cfo = True
        flags.append("negative_cfo: CFO < 0 while Net Income > 0 — hard disqualifier")

    # QoE ratio
    if net_income == 0:
        qoe: Optional[float] = None
        if cfo > 0:
            flags.append("qoe_undefined: net_income=0 but CFO positive")
        elif cfo < 0:
            flags.append("qoe_undefined: net_income=0 and CFO negative")
    else:
        qoe = cfo / net_income
        if qoe < 0.8:
            accrual_anomaly = True
            flags.append(f"accrual_anomaly: QoE={qoe:.3f} < 0.8 threshold")
        else:
            flags.append(f"qoe_ok: QoE={qoe:.3f} >= 0.8")

    logger.debug(
        "QoE for %s: qoe=%s accrual_anomaly=%s negative_cfo=%s",
        financials.get("ticker", "?"), qoe, accrual_anomaly, negative_cfo,
    )

    return {
        "qoe": round(qoe, 4) if qoe is not None else None,
        "accrual_anomaly": accrual_anomaly,
        "negative_cfo": negative_cfo,
        "flags": flags,
        "skip_reason": None,
    }


# ---------------------------------------------------------------------------
# Margin of Safety (MOS Score)
# ---------------------------------------------------------------------------

def margin_of_safety(
    financials: dict,
    market_price: Optional[float] = None,
    shares: Optional[float] = None,
    r_free: float = 0.05,
) -> dict:
    """Compute Margin of Safety score (0-100) across 6 factors per PRD §10.

    Args:
        financials:   dict from fetch_edgar_financials_extended().
        market_price: Current share price (yfinance last close).
        shares:       Shares outstanding; uses financials value if None.
        r_free:       Risk-free rate decimal (from get_risk_free_rate()).

    Returns:
        {
            "mos_score": float,
            "factor_scores": dict,
            "factor_weights": dict,
            "components": dict,
            "skip_reason": str | None,
        }
    """
    _empty = {
        "mos_score": 0.0,
        "factor_scores": {f"factor{i}": 0.0 for i in range(1, 7)},
        "factor_weights": {
            "factor1_earnings_yield_premium": 0.25,
            "factor2_ptbv": 0.20,
            "factor3_interest_coverage": 0.20,
            "factor4_fcf_yield": 0.15,
            "factor5_de_ratio": 0.10,
            "factor6_revenue_growth": 0.10,
        },
        "components": {},
        "skip_reason": "no_data",
    }

    if not financials:
        return _empty

    # Shares: prefer argument, fall back to financials
    if shares is None:
        shares = financials.get("shares_outstanding")

    # Market cap
    market_cap: Optional[float] = None
    if market_price is not None and shares is not None and shares > 0:
        market_cap = market_price * shares

    # Raw financial data
    net_income: Optional[float] = financials.get("net_income")
    book_value: Optional[float] = financials.get("book_value")
    interest_expense: Optional[float] = financials.get("interest_expense")
    tax_expense: Optional[float] = financials.get("tax_expense")
    fcf: Optional[float] = financials.get("fcf")
    total_debt: Optional[float] = financials.get("total_debt")
    revenue: Optional[float] = financials.get("revenue")
    prior_revenue: Optional[float] = financials.get("prior_revenue")

    # EBIT
    ebit: Optional[float] = None
    if net_income is not None:
        ebit = net_income
        if interest_expense is not None:
            ebit += interest_expense
        if tax_expense is not None:
            ebit += tax_expense

    # Tangible book value (use book_value as proxy)
    tbv: Optional[float] = book_value

    components: dict = {}
    factor_scores: dict[str, float] = {}
    weights = {
        "factor1_earnings_yield_premium": 0.25,
        "factor2_ptbv": 0.20,
        "factor3_interest_coverage": 0.20,
        "factor4_fcf_yield": 0.15,
        "factor5_de_ratio": 0.10,
        "factor6_revenue_growth": 0.10,
    }

    # --- Factor 1: Earnings Yield Premium (E/P - r_free) ---
    ep: Optional[float] = None
    if net_income is not None and market_cap is not None and market_cap > 0:
        ep = net_income / market_cap
    components["ep"] = ep
    components["r_free"] = r_free

    if ep is not None and ep > r_free:
        spread = ep - r_free
        f1 = _linear_score(spread, low=0.0, high=0.04)
    elif ep is not None and ep <= r_free:
        f1 = 0.0
    else:
        f1 = 0.0
    factor_scores["factor1_earnings_yield_premium"] = round(f1, 2)

    # --- Factor 2: Price-to-Tangible Book Value (P/TBV) ---
    ptbv: Optional[float] = None
    if market_price is not None and tbv is not None and shares is not None and shares > 0:
        tbv_per_share = tbv / shares
        if tbv_per_share > 0:
            ptbv = market_price / tbv_per_share
    components["ptbv"] = ptbv

    if ptbv is not None:
        f2 = _linear_score(ptbv, low=1.5, high=5.0, invert=True)
    else:
        f2 = 0.0
    factor_scores["factor2_ptbv"] = round(f2, 2)

    # --- Factor 3: Interest Coverage (EBIT / Interest) ---
    interest_coverage: Optional[float] = None
    if ebit is not None and interest_expense is not None and interest_expense > 0:
        interest_coverage = ebit / interest_expense
    elif ebit is not None and (interest_expense is None or interest_expense == 0):
        interest_coverage = 10.0
    components["interest_coverage"] = interest_coverage

    if interest_coverage is not None:
        f3 = _linear_score(interest_coverage, low=1.5, high=5.0)
    else:
        f3 = 0.0
    factor_scores["factor3_interest_coverage"] = round(f3, 2)

    # --- Factor 4: FCF Yield (FCF / Market Cap) ---
    fcf_yield: Optional[float] = None
    if fcf is not None and market_cap is not None and market_cap > 0:
        fcf_yield = fcf / market_cap
    components["fcf_yield"] = fcf_yield

    if fcf_yield is not None:
        f4 = _linear_score(fcf_yield, low=0.0, high=0.08)
    else:
        f4 = 0.0
    factor_scores["factor4_fcf_yield"] = round(f4, 2)

    # --- Factor 5: Debt / Tangible Equity ---
    de_ratio: Optional[float] = None
    if total_debt is not None and tbv is not None and tbv > 0:
        de_ratio = total_debt / tbv
    components["de_ratio"] = de_ratio

    if de_ratio is not None:
        f5 = _linear_score(de_ratio, low=0.5, high=3.0, invert=True)
    else:
        f5 = 0.0
    factor_scores["factor5_de_ratio"] = round(f5, 2)

    # --- Factor 6: Revenue Growth YoY ---
    rev_growth: Optional[float] = None
    if revenue is not None and prior_revenue is not None and prior_revenue > 0:
        rev_growth = (revenue - prior_revenue) / prior_revenue
    components["rev_growth"] = rev_growth

    if rev_growth is not None:
        f6 = _linear_score(rev_growth, low=-0.10, high=0.10)
    else:
        f6 = 0.0
    factor_scores["factor6_revenue_growth"] = round(f6, 2)

    # --- Weighted sum ---
    mos_score = (
        weights["factor1_earnings_yield_premium"] * factor_scores["factor1_earnings_yield_premium"]
        + weights["factor2_ptbv"] * factor_scores["factor2_ptbv"]
        + weights["factor3_interest_coverage"] * factor_scores["factor3_interest_coverage"]
        + weights["factor4_fcf_yield"] * factor_scores["factor4_fcf_yield"]
        + weights["factor5_de_ratio"] * factor_scores["factor5_de_ratio"]
        + weights["factor6_revenue_growth"] * factor_scores["factor6_revenue_growth"]
    )
    mos_score = round(max(0.0, min(100.0, mos_score)), 4)

    logger.debug(
        "MOS for %s: score=%.2f factors=%s",
        financials.get("ticker", "?"), mos_score, factor_scores,
    )

    return {
        "mos_score": mos_score,
        "factor_scores": factor_scores,
        "factor_weights": weights,
        "components": components,
        "skip_reason": None,
    }
