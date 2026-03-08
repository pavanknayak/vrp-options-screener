"""
recommendations/gonogo.py — 21-point go/no-go evaluation matrix (PRD §7).

Every Stage 2 candidate passes through evaluate_gonogo() before any
recommendation is assembled. The function encodes all hard disqualifiers
(HARD-01 through HARD-09) followed by soft filters (SOFT-01 through SOFT-12)
in strict priority order. Evaluation stops at the first failing criterion,
so callers receive the single most important reason for rejection.

Public exports: GoNoGoResult, evaluate_gonogo
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GoNoGoResult:
    """Result of the 21-point go/no-go evaluation for a single candidate."""

    passed: bool
    """True only if all 21 checks pass."""

    failed_criterion: Optional[str]
    """First failing criterion ID (e.g. 'HARD-04'), or None if passed."""

    failed_reason: Optional[str]
    """Human-readable explanation of the failure, or None if passed."""

    permitted_structures: list[str]
    """Forwarded from fundamentals gate_result.permitted_structures."""

    checks: list[dict]
    """All evaluated checks with keys: id, name, passed, reason."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_check(check_id: str, name: str, passed: bool, reason: str) -> dict:
    return {"id": check_id, "name": name, "passed": passed, "reason": reason}


def _fail(
    check_id: str,
    name: str,
    reason: str,
    checks: list[dict],
    permitted_structures: list[str],
) -> GoNoGoResult:
    checks.append(_make_check(check_id, name, False, reason))
    return GoNoGoResult(
        passed=False,
        failed_criterion=check_id,
        failed_reason=reason,
        permitted_structures=permitted_structures,
        checks=checks,
    )


def _pass_check(checks: list[dict], check_id: str, name: str, reason: str = "OK") -> None:
    checks.append(_make_check(check_id, name, True, reason))


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_gonogo(
    analytics_result: dict,
    fundamentals_result: dict,
    ticker_info,
    proposed_structure: str,
    slippage_adj_ev: float,
) -> GoNoGoResult:
    """Evaluate a candidate against the 21-point go/no-go matrix.

    Parameters
    ----------
    analytics_result : dict
        Output from run_analytics() — must contain vrp_pctile, signals, etc.
    fundamentals_result : dict
        Output from run_fundamentals() — must contain gate_result and altman.
    ticker_info : TickerInfo
        Resolved tier metadata from universe.loader.get_ticker_info().
    proposed_structure : str
        Pre-selected structure: 'csp', 'spread', or 'collar'.
    slippage_adj_ev : float
        Slippage-adjusted expected value (pre-computed by pnl.py).

    Returns
    -------
    GoNoGoResult
        passed=True with all 21 checks if candidate clears every criterion.
        passed=False with the first failing criterion ID and human-readable reason.
    """
    try:
        return _evaluate_inner(
            analytics_result, fundamentals_result, ticker_info,
            proposed_structure, slippage_adj_ev,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("evaluate_gonogo: unexpected error: %s", exc, exc_info=True)
        return GoNoGoResult(
            passed=False,
            failed_criterion="INTERNAL_ERROR",
            failed_reason=f"Unexpected error during go/no-go evaluation: {exc}",
            permitted_structures=[],
            checks=[],
        )


def _evaluate_inner(
    analytics_result: dict,
    fundamentals_result: dict,
    ticker_info,
    proposed_structure: str,
    slippage_adj_ev: float,
) -> GoNoGoResult:
    """Core evaluation logic — may raise; caller wraps in try/except."""

    checks: list[dict] = []

    # Resolve permitted_structures early (needed for GoNoGoResult regardless of outcome)
    permitted_structures: list[str] = (
        fundamentals_result
        .get("gate_result", {})
        .get("permitted_structures", ["csp", "spread", "collar"])
    )

    # Warn if fundamentals result contains an error
    if fundamentals_result.get("error"):
        warnings.warn(
            f"fundamentals_result contains error — fundamental checks treated as skipped: "
            f"{fundamentals_result['error']}",
            stacklevel=3,
        )
        logger.warning(
            "evaluate_gonogo: fundamentals_result has error key '%s' — "
            "fundamental checks (HARD-06, SOFT-08) will pass through",
            fundamentals_result["error"],
        )

    # Convenience aliases
    signals: dict = analytics_result.get("signals", {})
    tier: str = ticker_info.tier

    # ------------------------------------------------------------------
    # HARD disqualifiers (HARD-01 through HARD-09)
    # Evaluation stops at first failure.
    # ------------------------------------------------------------------

    # HARD-01: VRP Statistical Significance
    vrp_pctile: float = analytics_result.get("vrp_pctile", 0.0)
    if vrp_pctile < 0.40:
        return _fail(
            "HARD-01",
            "VRP Statistical Significance",
            f"VRP at {vrp_pctile * 100:.0f}th percentile — below 40th percentile threshold.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-01", "VRP Statistical Significance")

    # HARD-02: Earnings Inside DTE Window
    has_earnings: bool = bool(analytics_result.get("has_earnings_in_window", False))
    if has_earnings:
        return _fail(
            "HARD-02",
            "Earnings Inside DTE Window",
            "Earnings fall within the option expiration window — binary event risk.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-02", "Earnings Inside DTE Window")

    # HARD-03: Slippage-Adjusted EV Positive
    if slippage_adj_ev <= 0:
        return _fail(
            "HARD-03",
            "Slippage-Adjusted EV Positive",
            f"Slippage-adjusted EV is {slippage_adj_ev:.4f} — non-positive expected value.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-03", "Slippage-Adjusted EV Positive")

    # HARD-04: VoV Z-Score Stability
    vov_z: float = signals.get("vov_z", 0.0)
    if vov_z > 2.5:
        return _fail(
            "HARD-04",
            "VoV Z-Score Stability",
            f"VoV Z-score {vov_z:.2f} exceeds 2.5 — IV too unstable to collect premium.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-04", "VoV Z-Score Stability")

    # HARD-05: Regime Not Crisis
    regime_label: str = analytics_result.get("regime_label", "")
    if regime_label == "Crisis":
        return _fail(
            "HARD-05",
            "Regime Not Crisis",
            "Crisis regime detected (VIX > 40). No new short-vol positions.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-05", "Regime Not Crisis")

    # HARD-06: Altman Distress Gate
    altman: dict = fundamentals_result.get("altman", {})
    is_distress: bool = bool(altman.get("is_distress", False))
    requires_fundamental: bool = bool(ticker_info.requires_fundamental_score)
    if is_distress and requires_fundamental and not fundamentals_result.get("error"):
        score_val = altman.get("score", "N/A")
        return _fail(
            "HARD-06",
            "Altman Distress Gate",
            f"Altman Z in distress zone (score={score_val}) — fundamental gate blocks CSP.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-06", "Altman Distress Gate")

    # HARD-07: Jump% Threshold
    jump_pct: float = analytics_result.get("jump_pct", 0.0)
    if jump_pct > 0.50:
        return _fail(
            "HARD-07",
            "Jump% Threshold",
            f"Jump component {jump_pct * 100:.1f}% of RV — above 50% threshold, diffusive VRP unreliable.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-07", "Jump% Threshold")

    # HARD-08: China ADR Structure Ban
    if ticker_info.asset_class == "china_adr" and proposed_structure == "csp":
        return _fail(
            "HARD-08",
            "China ADR Structure Ban",
            "China ADR (Tier 6B) CSP structurally banned — only Spread/Collar permitted.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-08", "China ADR Structure Ban")

    # HARD-09: Crypto ETF Structure Ban
    if ticker_info.asset_class == "crypto_etf" and proposed_structure == "csp":
        return _fail(
            "HARD-09",
            "Crypto ETF Structure Ban",
            "Crypto ETF CSP structurally banned — only Spread/Collar permitted.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "HARD-09", "Crypto ETF Structure Ban")

    # ------------------------------------------------------------------
    # SOFT filters (SOFT-01 through SOFT-12)
    # Evaluation stops at first failure.
    # ------------------------------------------------------------------

    composite_score: float = analytics_result.get("composite_score", 0.0)

    # SOFT-01: Composite Score Minimum (Tier 1A-1I)
    if tier.startswith("1") and composite_score < 35:
        return _fail(
            "SOFT-01",
            "Composite Score Minimum (Tier 1A-1I)",
            f"Composite score {composite_score:.1f} below 35 minimum for ETF tier.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-01", "Composite Score Minimum (Tier 1A-1I)")

    # SOFT-02: Composite Score Minimum (Tier 2)
    if tier == "2" and composite_score < 45:
        return _fail(
            "SOFT-02",
            "Composite Score Minimum (Tier 2)",
            f"Composite score {composite_score:.1f} below 45 minimum for Tier 2.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-02", "Composite Score Minimum (Tier 2)")

    # SOFT-03: Composite Score Minimum (Tier 3)
    if tier == "3" and composite_score < 50:
        return _fail(
            "SOFT-03",
            "Composite Score Minimum (Tier 3)",
            f"Composite score {composite_score:.1f} below 50 minimum for Tier 3.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-03", "Composite Score Minimum (Tier 3)")

    # SOFT-04: Composite Score Minimum (Tier 4/5)
    if tier in ("4", "5") and composite_score < 55:
        return _fail(
            "SOFT-04",
            "Composite Score Minimum (Tier 4/5)",
            f"Composite score {composite_score:.1f} below 55 minimum for Tier 4/5.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-04", "Composite Score Minimum (Tier 4/5)")

    # SOFT-05: Composite Score Minimum (ADR Tiers)
    if tier in ("6A", "6B", "7") and composite_score < 50:
        return _fail(
            "SOFT-05",
            "Composite Score Minimum (ADR Tiers)",
            f"Composite score {composite_score:.1f} below 50 minimum for ADR tier.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-05", "Composite Score Minimum (ADR Tiers)")

    # SOFT-06: IVP Minimum
    ivp: float = analytics_result.get("ivp", 0.0)
    if ivp < 0.40:
        return _fail(
            "SOFT-06",
            "IVP Minimum",
            f"IVP {ivp * 100:.0f}th percentile below 40th — IV not sufficiently elevated.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-06", "IVP Minimum")

    # SOFT-07: VRP Persistence
    vrp_persist: float = signals.get("vrp_persist_30d", 0.0)
    if vrp_persist < 0.50:
        return _fail(
            "SOFT-07",
            "VRP Persistence",
            f"VRP positive only {vrp_persist * 100:.0f}% of last 30 days — premium insufficiently persistent.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-07", "VRP Persistence")

    # SOFT-08: Fundamental Gate
    fund_gate: dict = fundamentals_result.get("gate_result", {})
    fund_gate_passed: bool = bool(fund_gate.get("passed", True))
    equity_tiers = ("3", "4", "5", "6A", "7")
    if (
        not fund_gate_passed
        and tier in equity_tiers
        and not fundamentals_result.get("error")
    ):
        fund_failed_criterion = fund_gate.get("failed_criterion", "unknown")
        return _fail(
            "SOFT-08",
            "Fundamental Gate",
            f"Fundamental gate failed: {fund_failed_criterion}.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-08", "Fundamental Gate")

    # SOFT-09: GEX Not Severely Negative
    gex_billions: float = analytics_result.get("gex_billions", 0.0)
    if gex_billions < -2.0:
        return _fail(
            "SOFT-09",
            "GEX Not Severely Negative",
            f"GEX {gex_billions:.2f}B — severely negative dealer positioning amplifies realized vol.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-09", "GEX Not Severely Negative")

    # SOFT-10: Term Structure Not Severely Inverted
    term_slope: float = signals.get("term_slope", 0.0)
    if term_slope < -0.05:
        return _fail(
            "SOFT-10",
            "Term Structure Not Severely Inverted",
            f"Term structure deeply inverted ({term_slope * 100:.1f}pp) — contango required for premium collection.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-10", "Term Structure Not Severely Inverted")

    # SOFT-11: VoV Moderate Check
    high_crisis_regimes = ("Crisis", "High")
    if vov_z > 1.5 and regime_label in high_crisis_regimes:
        return _fail(
            "SOFT-11",
            "VoV Moderate Check",
            f"VoV Z {vov_z:.2f} elevated in High/Crisis regime — double vol-instability flag.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-11", "VoV Moderate Check")

    # SOFT-12: PCR Not Extreme Bearish
    pcr_oi: float = analytics_result.get("pcr_oi", 1.0)
    if pcr_oi > 3.0:
        return _fail(
            "SOFT-12",
            "PCR Not Extreme Bearish",
            f"PCR OI {pcr_oi:.2f} — extreme put-buying indicates hedger panic, not orderly premium.",
            checks,
            permitted_structures,
        )
    _pass_check(checks, "SOFT-12", "PCR Not Extreme Bearish")

    # ------------------------------------------------------------------
    # All 21 checks passed
    # ------------------------------------------------------------------
    return GoNoGoResult(
        passed=True,
        failed_criterion=None,
        failed_reason=None,
        permitted_structures=permitted_structures,
        checks=checks,
    )
