"""
fundamentals/engine.py — Fundamentals Engine orchestrator.

Entry point for Phase 5 (Recommendations) and the Streamlit UI.
Fetches EDGAR extended financials + market price, runs all four scoring
models, computes the Combined Fundamental Score, and enforces per-tier gates.

Exports:
    run_fundamentals(ticker, tier, asset_class) -> dict
"""
from __future__ import annotations

import logging
from typing import Optional

from data.fred_fetcher import get_risk_free_rate
from data.yfinance_fetcher import fetch_ohlcv
from fundamentals.altman import altman_z
from fundamentals.edgar_extended import fetch_edgar_financials_extended
from fundamentals.piotroski import piotroski_f_score
from fundamentals.quality import margin_of_safety, quality_of_earnings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-tier gate configuration
# ---------------------------------------------------------------------------

# Structure:
#   tier_id -> {
#       "min_combined":  float | None,  # None = no fundamental check (ETFs)
#       "altman_min":    float | None,  # minimum Altman Z' score; None = distress only
#       "altman_distress_blocks": bool, # True = any distress blocks
#       "piotroski_min": int | None,    # minimum F-Score total
#       "csp_allowed":   bool,          # False = CSP structurally blocked (6B)
#   }

_TIER_GATES: dict[str, dict] = {
    # Tiers 1A-1I: ETFs and indices — no fundamental check
    "1A": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1B": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1C": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1D": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1E": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1F": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1G": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1H": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    "1I": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": True},
    # Tier 2: S&P 500 Large Cap
    "2":  {"min_combined": 40.0, "altman_min": None, "altman_distress_blocks": True,  "piotroski_min": None, "csp_allowed": True},
    # Tier 3: S&P MidCap 400
    "3":  {"min_combined": 55.0, "altman_min": 1.23, "altman_distress_blocks": True,  "piotroski_min": 5, "csp_allowed": True},
    # Tier 4: S&P SmallCap 600
    "4":  {"min_combined": 65.0, "altman_min": 2.50, "altman_distress_blocks": True,  "piotroski_min": 6, "csp_allowed": True},
    # Tier 5: Micro-Cap
    "5":  {"min_combined": 75.0, "altman_min": 2.99, "altman_distress_blocks": True,  "piotroski_min": 7, "csp_allowed": True},
    # Tier 6A: India ADRs
    "6A": {"min_combined": 65.0, "altman_min": None, "altman_distress_blocks": True,  "piotroski_min": 6, "csp_allowed": True},
    # Tier 6B: China ADRs — CSP always blocked
    "6B": {"min_combined": None, "altman_min": None, "altman_distress_blocks": False, "piotroski_min": None, "csp_allowed": False},
    # Tier 7: Rest-of-World ADRs
    "7":  {"min_combined": 40.0, "altman_min": None, "altman_distress_blocks": True,  "piotroski_min": None, "csp_allowed": True},
}

# Default structures available before gate removal (gate strips "csp" if blocked)
_ALL_STRUCTURES = ["csp", "spread", "collar"]
_NON_CSP_STRUCTURES = ["spread", "collar"]


def _enforce_tier_gate(
    tier: str,
    asset_class: str,
    combined_score: float,
    f_score: int,
    altman_zone: str,
    altman_score: Optional[float],
) -> dict:
    """Evaluate per-tier fundamental gate and return pass/fail decision.

    Args:
        tier:           TickerInfo.tier (e.g., "2", "3", "6B")
        asset_class:    TickerInfo.asset_class (e.g., "us_equity", "china_adr")
        combined_score: 0.45*(f_score/9*100) + 0.55*mos_score
        f_score:        Piotroski total (0-9)
        altman_zone:    "safe" | "gray" | "distress" | "N/A"
        altman_score:   Altman Z/Z'/Z'' numeric score or None

    Returns:
        {
            "passed": bool,
            "failed_criterion": str | None,   # first failing criterion name
            "permitted_structures": list[str],
            "gate_details": dict,             # per-criterion pass/fail for go/no-go matrix
        }
    """
    gate_config = _TIER_GATES.get(tier)

    # Unknown tier — default permissive (log warning)
    if gate_config is None:
        logger.warning("Unknown tier '%s' in _enforce_tier_gate — defaulting to pass", tier)
        return {
            "passed": True,
            "failed_criterion": None,
            "permitted_structures": list(_ALL_STRUCTURES),
            "gate_details": {"tier_known": False},
        }

    gate_details: dict = {}
    failed_criterion: Optional[str] = None
    permitted_structures = list(_ALL_STRUCTURES)

    # --- Rule 1: CSP structurally blocked (6B) ---
    if not gate_config["csp_allowed"]:
        # Remove CSP from permitted structures — does not set failed_criterion
        # (Spread/Collar remain available)
        permitted_structures = list(_NON_CSP_STRUCTURES)
        gate_details["csp_allowed"] = False
        # For 6B: gate passes for spread/collar, fails for CSP
        # We mark failed_criterion so the caller knows CSP was removed
        failed_criterion = "china_adr_csp_blocked"
        gate_details["china_adr_csp_blocked"] = True
        logger.info("Tier 6B: CSP blocked by policy — spread/collar permitted")
        return {
            "passed": False,
            "failed_criterion": failed_criterion,
            "permitted_structures": permitted_structures,
            "gate_details": gate_details,
        }

    # --- Rule 2: No fundamental check required (ETF tiers 1A-1I) ---
    if gate_config["min_combined"] is None and not gate_config["altman_distress_blocks"] and gate_config["piotroski_min"] is None:
        gate_details["fundamental_check_required"] = False
        return {
            "passed": True,
            "failed_criterion": None,
            "permitted_structures": permitted_structures,
            "gate_details": gate_details,
        }

    gate_details["fundamental_check_required"] = True

    # --- Rule 3: Altman distress hard block ---
    if gate_config["altman_distress_blocks"] and altman_zone == "distress":
        failed_criterion = f"altman_distress:zone={altman_zone},score={altman_score}"
        gate_details["altman_distress"] = "FAIL"
        logger.info(
            "Tier %s gate FAIL: Altman distress (score=%s zone=%s)",
            tier, altman_score, altman_zone,
        )
        return {
            "passed": False,
            "failed_criterion": failed_criterion,
            "permitted_structures": [],
            "gate_details": gate_details,
        }
    gate_details["altman_distress"] = "pass" if altman_zone != "distress" else "N/A"

    # --- Rule 4: Altman minimum score ---
    altman_min = gate_config.get("altman_min")
    if altman_min is not None:
        if altman_score is None or altman_score < altman_min:
            failed_criterion = f"altman_min:{altman_min}:actual={altman_score}"
            gate_details["altman_min"] = "FAIL"
            logger.info(
                "Tier %s gate FAIL: Altman score %s < minimum %s",
                tier, altman_score, altman_min,
            )
            return {
                "passed": False,
                "failed_criterion": failed_criterion,
                "permitted_structures": [],
                "gate_details": gate_details,
            }
        gate_details["altman_min"] = "pass"

    # --- Rule 5: Piotroski minimum ---
    piotroski_min = gate_config.get("piotroski_min")
    if piotroski_min is not None:
        if f_score < piotroski_min:
            failed_criterion = f"piotroski_min:{piotroski_min}:actual={f_score}"
            gate_details["piotroski_min"] = "FAIL"
            logger.info(
                "Tier %s gate FAIL: Piotroski F-Score %d < minimum %d",
                tier, f_score, piotroski_min,
            )
            return {
                "passed": False,
                "failed_criterion": failed_criterion,
                "permitted_structures": [],
                "gate_details": gate_details,
            }
        gate_details["piotroski_min"] = "pass"

    # --- Rule 6: Combined Fundamental Score minimum ---
    min_combined = gate_config.get("min_combined")
    if min_combined is not None:
        if combined_score <= min_combined:
            failed_criterion = f"combined_score_min:{min_combined}:actual={combined_score:.1f}"
            gate_details["combined_score_min"] = "FAIL"
            logger.info(
                "Tier %s gate FAIL: combined_score %.1f <= minimum %.1f",
                tier, combined_score, min_combined,
            )
            return {
                "passed": False,
                "failed_criterion": failed_criterion,
                "permitted_structures": [],
                "gate_details": gate_details,
            }
        gate_details["combined_score_min"] = "pass"

    logger.debug("Tier %s gate PASS: combined=%.1f f=%d altman=%s", tier, combined_score, f_score, altman_zone)
    return {
        "passed": True,
        "failed_criterion": None,
        "permitted_structures": permitted_structures,
        "gate_details": gate_details,
    }


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def run_fundamentals(
    ticker: str,
    tier: str,
    asset_class: str,
) -> dict:
    """Run all four fundamental scoring models and enforce per-tier gate.

    This is the single public entry point for Phase 5 (Recommendations) and UI.

    Args:
        ticker:      Uppercase ticker symbol.
        tier:        TickerInfo.tier (e.g., "2", "3", "6B").
        asset_class: TickerInfo.asset_class (e.g., "us_equity", "china_adr").

    Returns a dict with the following structure:
        {
            "ticker": str,
            "tier": str,
            "asset_class": str,
            "requires_fundamental_score": bool,
            # Scoring models
            "piotroski": dict,       # from piotroski_f_score()
            "altman": dict,          # from altman_z()
            "qoe": dict,             # from quality_of_earnings()
            "mos": dict,             # from margin_of_safety()
            # Combined score
            "combined_score": float, # 0.45*(f_score/9*100) + 0.55*mos_score
            # Gate result
            "gate_result": {
                "passed": bool,
                "failed_criterion": str | None,
                "permitted_structures": list[str],
                "gate_details": dict,
            },
        }

    On any unhandled exception: returns {"ticker": ticker, "error": str(exc)}
    ETF tickers (ETF asset_class or tier 1A-1I): returns immediately with gate_result.passed=True,
    requires_fundamental_score=False, and zeroed scoring model results.
    """
    ticker = ticker.upper()
    logger.info("[FUND] run_fundamentals(%s, tier=%s, asset_class=%s)", ticker, tier, asset_class)

    try:
        # --- ETF fast path ---
        _etf_asset_classes = {
            "broad_market_etf", "sector_etf", "thematic_etf",
            "crypto_etf", "bond_etf",
        }
        _etf_tiers = {"1A", "1B", "1C", "1D", "1E", "1F", "1G", "1H", "1I"}
        is_etf = (asset_class.lower() in _etf_asset_classes) or (tier in _etf_tiers)

        _empty_piotroski = {
            "f1": 0, "f2": 0, "f3": 0, "f4": 0, "f5": 0,
            "f6": 0, "f7": 0, "f8": 0, "f9": 0,
            "total": 0, "details": {}, "data_quality": "empty",
        }
        _empty_altman = {
            "score": None, "model": "N/A", "zone": "N/A",
            "is_distress": False, "components": {}, "skip_reason": "etf",
        }
        _empty_qoe = {
            "qoe": None, "accrual_anomaly": False, "negative_cfo": False,
            "flags": [], "skip_reason": "etf",
        }
        _empty_mos = {
            "mos_score": 0.0,
            "factor_scores": {f"factor{i}": 0.0 for i in range(1, 7)},
            "factor_weights": {},
            "components": {},
            "skip_reason": "etf",
        }

        if is_etf:
            logger.debug("[FUND] %s is ETF/index — skipping fundamental scoring", ticker)
            return {
                "ticker": ticker,
                "tier": tier,
                "asset_class": asset_class,
                "requires_fundamental_score": False,
                "piotroski": _empty_piotroski,
                "altman": _empty_altman,
                "qoe": _empty_qoe,
                "mos": _empty_mos,
                "combined_score": 0.0,
                "gate_result": {
                    "passed": True,
                    "failed_criterion": None,
                    "permitted_structures": ["csp", "spread", "collar"],
                    "gate_details": {"fundamental_check_required": False},
                },
            }

        # --- Fetch market price (last OHLCV close) ---
        market_price: Optional[float] = None
        shares: Optional[float] = None
        ohlcv = fetch_ohlcv(ticker)
        if not ohlcv.empty and "Close" in ohlcv.columns:
            closes = ohlcv["Close"].dropna()
            if len(closes) > 0:
                market_price = float(closes.iloc[-1])

        # --- Fetch extended EDGAR financials ---
        financials = fetch_edgar_financials_extended(ticker)
        if financials:
            shares = financials.get("shares_outstanding")

        # --- Scoring models ---
        piotroski = piotroski_f_score(financials)
        altman = altman_z(financials, market_price=market_price, shares=shares, asset_class=asset_class)
        qoe = quality_of_earnings(financials)
        r_free = get_risk_free_rate()
        mos = margin_of_safety(financials, market_price=market_price, shares=shares, r_free=r_free)

        # --- Combined Fundamental Score ---
        f_score_total: int = piotroski.get("total", 0)
        mos_score: float = mos.get("mos_score", 0.0)
        combined_score = 0.45 * (f_score_total / 9 * 100) + 0.55 * mos_score
        combined_score = round(combined_score, 4)

        # --- Per-tier gate enforcement ---
        altman_zone: str = altman.get("zone", "N/A")
        altman_score: Optional[float] = altman.get("score")
        gate_result = _enforce_tier_gate(
            tier=tier,
            asset_class=asset_class,
            combined_score=combined_score,
            f_score=f_score_total,
            altman_zone=altman_zone,
            altman_score=altman_score,
        )

        logger.info(
            "[FUND] %s: combined=%.1f f=%d/9 altman=%s(%s) mos=%.1f gate=%s",
            ticker, combined_score, f_score_total,
            altman.get("model"), altman_zone, mos_score,
            "PASS" if gate_result["passed"] else f"FAIL:{gate_result['failed_criterion']}",
        )

        return {
            "ticker": ticker,
            "tier": tier,
            "asset_class": asset_class,
            "requires_fundamental_score": True,
            "piotroski": piotroski,
            "altman": altman,
            "qoe": qoe,
            "mos": mos,
            "combined_score": combined_score,
            "gate_result": gate_result,
        }

    except Exception as exc:
        logger.error("[FUND] run_fundamentals(%s) failed: %s", ticker, exc, exc_info=True)
        return {"ticker": ticker, "error": str(exc)}
