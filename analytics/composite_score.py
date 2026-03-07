"""
analytics/composite_score.py — Composite VRP score (PRD §6.11).

Produces a single 0–100 score by combining 12 VRP signals using a weighted
sum, then applying multiplicative penalties for event risk, jump contamination,
and IV instability.

Public exports: composite_vrp_score, normalize_signal
"""
from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Weight vector — must sum to exactly 1.0
# ---------------------------------------------------------------------------

_WEIGHTS = [0.18, 0.12, 0.12, 0.10, 0.10, 0.08, 0.08, 0.07, 0.05, 0.04, 0.03, 0.03]
assert abs(sum(_WEIGHTS) - 1.0) < 1e-10, (
    f"Weights sum to {sum(_WEIGHTS)}, expected 1.0"
)


# ---------------------------------------------------------------------------
# normalize_signal
# ---------------------------------------------------------------------------

def normalize_signal(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to [min_val, max_val] and linearly scale to [0, 1].

    Parameters
    ----------
    value : float
        Raw signal value.
    min_val : float
        Lower bound of the expected signal range (maps to 0.0).
    max_val : float
        Upper bound of the expected signal range (maps to 1.0).

    Returns
    -------
    float
        Normalized value in [0.0, 1.0].
    """
    if max_val <= min_val:
        return 0.0
    return float(np.clip((value - min_val) / (max_val - min_val), 0.0, 1.0))


# ---------------------------------------------------------------------------
# GEX support score helper
# ---------------------------------------------------------------------------

def _gex_support_score(gex_bn: float) -> float:
    """Convert GEX billions to [0, 1] score for use in weighted sum.

    Positive GEX suppresses realized volatility (dealers are long gamma;
    they buy dips and sell rallies, dampening moves). Large positive GEX
    therefore supports premium collection.

    Parameters
    ----------
    gex_bn : float
        Net dealer gamma exposure in billions of dollars.

    Returns
    -------
    float
        Score in {0.0, 0.4, 0.7, 1.0}.
    """
    if gex_bn > 0.5:
        return 1.0
    if gex_bn > 0.0:
        return 0.7
    if gex_bn > -0.5:
        return 0.4
    return 0.0


# ---------------------------------------------------------------------------
# composite_vrp_score
# ---------------------------------------------------------------------------

def composite_vrp_score(
    signals: dict,
    has_earnings_in_window: bool = False,
    near_term_earnings: bool = False,
) -> float:
    """Compute composite VRP score in [0, 100] from 12-signal weighted sum.

    Signal weights (PRD §6.11, must sum to 1.0):
        0.18  vrp_pctile          — magnitude vs 252-day history
        0.12  vrp_persist_30d     — reliability (fraction of days VRP > 0)
        0.12  vrp_zscore          — statistical significance
        0.10  em_ratio            — implied vs realized expected move
        0.10  excess_vrp          — idiosyncratic premium above beta-adj index
        0.08  ivp                 — IV elevation percentile
        0.08  skew_25d            — hedging demand (put-call skew)
        0.07  term_slope_pctile   — term structure support
        0.05  jump_pct (inverted) — jump cleanliness
        0.04  pcr_oi              — put-buying demand
        0.03  gex_billions        — dealer positioning
        0.03  vov_z (inverted)    — IV stability

    Penalties applied multiplicatively after scaling (PRD §6.11):
        Event:   30% reduction if earnings within expiration window;
                 15% reduction if earnings near-term but outside window.
        Jump:    20% reduction if jump_pct > 0.35; 10% if jump_pct > 0.25.
        VoV:     DISQUALIFY (return 0.0) if vov_z > 2.5;
                 25% reduction if vov_z > 1.5.

    Parameters
    ----------
    signals : dict
        Output of compute_vrp_signals() from analytics.vrp_engine.
    has_earnings_in_window : bool
        True when an earnings release falls within the option expiration window.
    near_term_earnings : bool
        True when earnings are near-term but outside the current window.

    Returns
    -------
    float
        Score in [0.0, 100.0]. Returns 0.0 if VoV Z-score > 2.5 (DISQUALIFY).
    """
    s = signals  # alias for readability

    # VoV disqualifier — check before computing score (fast exit)
    vov_z = s.get('vov_z', 0.0)
    if vov_z is None:
        vov_z = 0.0
    vov_z = float(vov_z)

    if vov_z > 2.5:
        return 0.0  # DISQUALIFY — IV too unstable to collect premium

    # ------------------------------------------------------------------
    # 12-signal weighted sum
    # ------------------------------------------------------------------
    raw = (
        0.18 * normalize_signal(s.get('vrp_pctile', 0.0),      0.0,  1.0)   +  # Magnitude vs history
        0.12 * normalize_signal(s.get('vrp_persist_30d', 0.5), 0.4,  1.0)   +  # Reliability
        0.12 * normalize_signal(np.clip(s.get('vrp_zscore', 0.0), -3, 3),
                                -3.0, 3.0)                                    +  # Statistical significance
        0.10 * normalize_signal(s.get('em_ratio', 1.0),         0.8,  2.0)   +  # Implied vs realized move
        0.10 * normalize_signal(s.get('excess_vrp', 0.0),      -0.05, 0.10)  +  # Idiosyncratic premium
        0.08 * normalize_signal(s.get('ivp', 0.5),              0.0,  1.0)   +  # IV elevation
        0.08 * normalize_signal(s.get('skew_25d', 0.0),        -0.02, 0.08)  +  # Hedging demand
        0.07 * normalize_signal(s.get('term_slope_pctile', 0.5), 0.0, 1.0)  +  # Term structure support
        0.05 * normalize_signal(1.0 - s.get('jump_pct', 0.0),   0.5,  1.0)  +  # Jump cleanliness (inverted)
        0.04 * normalize_signal(s.get('pcr_oi', 1.0),           0.8,  2.5)  +  # Put buying demand
        0.03 * _gex_support_score(s.get('gex_billions', 0.0))               +  # Dealer positioning
        0.03 * normalize_signal(1.0 - vov_z / 3.0,              0.0,  1.0)     # IV stability (inverted VoV)
    )

    # raw is in [0, 1]; scale to [0, 100]
    score = raw * 100.0

    # ------------------------------------------------------------------
    # Multiplicative penalties (PRD §6.11)
    # ------------------------------------------------------------------
    event_penalty = (
        0.30 if has_earnings_in_window else
        (0.15 if near_term_earnings else 0.0)
    )

    jump_pct = s.get('jump_pct', 0.0)
    if jump_pct is None:
        jump_pct = 0.0
    jump_pct = float(jump_pct)
    jump_penalty = 0.20 if jump_pct > 0.35 else (0.10 if jump_pct > 0.25 else 0.0)

    vov_penalty = 0.25 if vov_z > 1.5 else 0.0

    score = score * (1.0 - event_penalty) * (1.0 - jump_penalty) * (1.0 - vov_penalty)
    return float(np.clip(score, 0.0, 100.0))
