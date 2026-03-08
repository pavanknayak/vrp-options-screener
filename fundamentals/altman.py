"""
fundamentals/altman.py — Altman Z-Score computation with model selection.

Three models per PRD §10:
  Z  (1968): publicly traded manufacturers
  Z' (1983): non-manufacturers / default for public companies
  Z''(1995): private companies or when market price is unavailable

Model selection logic:
  - ETFs (asset_class contains "etf") or financial companies
    (asset_class in ["bank","insurance","reit","financial"]):
    -> score=None, model="N/A", zone="N/A", is_distress=False
  - Public equity with market price available:
    -> use Z' (non-manufacturer default per PRD simplification)
  - No market price available:
    -> use Z''

Exports:
    altman_z(financials, market_price, shares, asset_class) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ETF / financial asset classes that are not scored
# ---------------------------------------------------------------------------
_EXEMPT_ASSET_CLASSES = {
    "broad_market_etf",
    "sector_etf",
    "thematic_etf",
    "crypto_etf",
    "bond_etf",
    "bank",
    "insurance",
    "reit",
    "financial",
}

# ---------------------------------------------------------------------------
# Zone classification helpers
# ---------------------------------------------------------------------------

def _classify_z(score: float) -> str:
    """Zone for Z (1968) model: manufacturers."""
    if score < 1.81:
        return "distress"
    elif score <= 2.99:
        return "gray"
    else:
        return "safe"


def _classify_zp(score: float) -> str:
    """Zone for Z' (1983) model: non-manufacturers (default public)."""
    if score < 1.23:
        return "distress"
    elif score <= 2.90:
        return "gray"
    else:
        return "safe"


def _classify_zpp(score: float) -> str:
    """Zone for Z'' (1995) model: private / no market price."""
    if score < 1.10:
        return "distress"
    elif score <= 2.60:
        return "gray"
    else:
        return "safe"


# ---------------------------------------------------------------------------
# Model implementations
# ---------------------------------------------------------------------------

def _altman_z_original(
    wc_ta: float,
    re_ta: float,
    ebit_ta: float,
    mve_tl: float,
    sales_ta: float,
) -> tuple[float, str]:
    """Z (1968): publicly traded manufacturers.
    Reference implementation — not used in current selection logic (Z' default per PRD §10).
    Returns (score, zone).
    """
    score = (
        1.2 * wc_ta
        + 1.4 * re_ta
        + 3.3 * ebit_ta
        + 0.6 * mve_tl
        + 1.0 * sales_ta
    )
    return score, _classify_z(score)


def _altman_zp(
    wc_ta: float,
    re_ta: float,
    ebit_ta: float,
    mve_tl: float,
) -> tuple[float, str]:
    """Z' (1983): non-manufacturers, default for public companies.
    Returns (score, zone).
    """
    score = (
        6.56 * wc_ta
        + 3.26 * re_ta
        + 6.72 * ebit_ta
        + 1.05 * mve_tl
    )
    return score, _classify_zp(score)


def _altman_zpp(
    wc_ta: float,
    re_ta: float,
    ebit_ta: float,
    bve_tl: float,
) -> tuple[float, str]:
    """Z'' (1995): private companies / no market price available.
    Uses book value of equity instead of market value.
    Returns (score, zone).
    """
    score = (
        6.56 * wc_ta
        + 3.26 * re_ta
        + 6.72 * ebit_ta
        + 1.05 * bve_tl
    )
    return score, _classify_zpp(score)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def altman_z(
    financials: dict,
    market_price: Optional[float] = None,
    shares: Optional[float] = None,
    asset_class: str = "us_equity",
) -> dict:
    """Compute Altman Z-Score with automatic model selection.

    Args:
        financials:   dict from fetch_edgar_financials_extended(). May be empty.
        market_price: Current share price (from yfinance OHLCV last close).
                      If None, falls back to Z'' model.
        shares:       Shares outstanding. If None, uses financials["shares_outstanding"].
        asset_class:  TickerInfo.asset_class — determines if scoring is applicable.

    Returns:
        {
            "score": float | None,
            "model": str,         # "Z'", "Z''", or "N/A"
            "zone":  str,         # "safe", "gray", "distress", or "N/A"
            "is_distress": bool,
            "components": dict,   # ratios used in computation
            "skip_reason": str | None,
        }
    """
    _na = {
        "score": None,
        "model": "N/A",
        "zone": "N/A",
        "is_distress": False,
        "components": {},
        "skip_reason": None,
    }

    # Exempt asset classes
    ac_lower = asset_class.lower()
    if any(exempt in ac_lower for exempt in _EXEMPT_ASSET_CLASSES):
        return {**_na, "skip_reason": f"not_applicable:{asset_class}"}

    # Empty financials (ETF in EDGAR, or fetch failure)
    if not financials:
        return {**_na, "skip_reason": "no_edgar_data"}

    # Extract balance sheet items needed for all models
    total_assets: Optional[float] = financials.get("total_assets")
    working_capital: Optional[float] = financials.get("working_capital")
    retained_earnings: Optional[float] = financials.get("retained_earnings")
    net_income: Optional[float] = financials.get("net_income")
    interest_expense: Optional[float] = financials.get("interest_expense")
    tax_expense: Optional[float] = financials.get("tax_expense")
    total_debt: Optional[float] = financials.get("total_debt")
    book_value: Optional[float] = financials.get("book_value")
    revenue: Optional[float] = financials.get("revenue")

    # Shares: prefer argument, fall back to financials
    if shares is None:
        shares = financials.get("shares_outstanding")

    # Cannot compute without total_assets
    if total_assets is None or total_assets == 0:
        return {**_na, "skip_reason": "total_assets_missing"}

    # EBIT = Net Income + Interest Expense + Tax Expense
    ebit: Optional[float] = None
    if net_income is not None:
        ebit = net_income
        if interest_expense is not None:
            ebit += interest_expense
        if tax_expense is not None:
            ebit += tax_expense

    # Core ratios (default to 0 if component missing — conservative)
    wc_ta = (working_capital or 0.0) / total_assets
    re_ta = (retained_earnings or 0.0) / total_assets
    ebit_ta = (ebit or 0.0) / total_assets

    # Total liabilities (approximate as total_assets - book_value)
    total_liabilities: float = total_assets - (book_value or 0.0)
    if total_liabilities <= 0:
        total_liabilities = total_debt or total_assets  # fallback

    # Book Value of Equity / Total Liabilities (for Z'')
    bve_tl = (book_value or 0.0) / total_liabilities if total_liabilities != 0 else 0.0

    # Market Value of Equity / Total Liabilities (for Z')
    mve: Optional[float] = None
    if market_price is not None and shares is not None and shares > 0:
        mve = market_price * shares
    mve_tl = mve / total_liabilities if (mve is not None and total_liabilities != 0) else None

    # Sales / Total Assets (for Z only — reference)
    sales_ta = (revenue or 0.0) / total_assets

    components = {
        "wc_ta": round(wc_ta, 6),
        "re_ta": round(re_ta, 6),
        "ebit_ta": round(ebit_ta, 6),
        "bve_tl": round(bve_tl, 6),
        "mve_tl": round(mve_tl, 6) if mve_tl is not None else None,
        "sales_ta": round(sales_ta, 6),
    }

    # Model selection:
    # Per PRD §10: default to Z' for all public equity; fall back to Z'' if no market price
    if mve_tl is not None:
        # Z' (1983) — non-manufacturer default for public companies
        score, zone = _altman_zp(wc_ta, re_ta, ebit_ta, mve_tl)
        model = "Z'"
    else:
        # Z'' (1995) — no market price
        score, zone = _altman_zpp(wc_ta, re_ta, ebit_ta, bve_tl)
        model = "Z''"

    is_distress = (zone == "distress")

    logger.debug(
        "Altman %s for %s: score=%.3f zone=%s",
        model, financials.get("ticker", "?"), score, zone,
    )

    return {
        "score": round(score, 4),
        "model": model,
        "zone": zone,
        "is_distress": is_distress,
        "components": components,
        "skip_reason": None,
    }
