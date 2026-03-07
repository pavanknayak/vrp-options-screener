"""
analytics/engine.py — Top-level analytics orchestrator (PRD §6).

run_analytics() is the single entry point called by the Phase 3 scanner
for each candidate ticker. It chains all analytics modules in dependency
order and returns a complete result dict (or a structured error dict —
it never raises an exception to the caller).

Call order:
    1. detect_regime()          analytics/regime.py
    2. compute_vrp()            analytics/iv_surface.py
    3. compute_vrp_signals()    analytics/vrp_engine.py
    4. composite_vrp_score()    analytics/composite_score.py

Public exports: run_analytics
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_analytics(
    ticker: str,
    chain: dict,                              # from fetch_options_chain()
    ohlc: pd.DataFrame,                       # from fetch_ohlcv()
    r: float,                                 # risk-free rate from get_risk_free_rate()
    vix: float,                               # current VIX level
    iv30_history: Optional[pd.Series] = None, # 252-day IV30 history (None = synthesised)
    vrp_history: Optional[pd.Series] = None,  # 252-day VRP history (None = synthesised)
    spy_vrp: float = 0.03,                    # SPY VRP benchmark (default 3 vol pts)
    beta: float = 1.0,                        # ticker beta (default 1.0)
    vvix: Optional[float] = None,             # VVIX for regime (optional)
    has_earnings_in_window: bool = False,
    near_term_earnings: bool = False,
) -> dict:
    """Full analytics pipeline for a single ticker.

    Returns a complete result dict, or a dict with a non-None 'error' key
    if any required pipeline step fails. This function never raises.

    Parameters
    ----------
    ticker : str
        Ticker symbol (for logging and result identification).
    chain : dict
        Schwab options chain dict with keys:
            'underlying_price': float
            'expirations': list of dicts, each with 'dte', 'calls', 'puts'
    ohlc : pd.DataFrame
        OHLCV DataFrame (columns: Open, High, Low, Close).
        Should cover at least 252 trading days.
    r : float
        Risk-free rate (continuously compounded decimal, e.g. 0.05 = 5%).
    vix : float
        Current VIX spot level.
    iv30_history : pd.Series, optional
        252-day rolling series of daily IV30 observations (most recent last).
        When None, a 30-element flat series is synthesised from iv30.
    vrp_history : pd.Series, optional
        252-day rolling series of daily VRP observations (most recent last).
        When None, a 30-element flat series is synthesised from vrp.
    spy_vrp : float
        Current SPY VRP for excess_vrp computation. Default 0.03 (3 vol pts).
    beta : float
        Ticker beta versus SPY from 252-day regression. Default 1.0.
    vvix : float, optional
        Current VVIX level for regime detection. Passed through to detect_regime().
    has_earnings_in_window : bool
        True when an earnings release falls within the option expiration window.
    near_term_earnings : bool
        True when earnings are near-term but outside the current option window.

    Returns
    -------
    dict
        Complete AnalyticsResult with keys:
            ticker, error, regime, iv30, iv60, iv30_td, vrp, ensemble_rv,
            har, garch, ewma, has_arbitrage, signals, composite_score,
            timing_action, timing_reason,
            vrp_pctile, ivp, gex_billions, pcr_oi, jump_pct,
            regime_label, regime_mult
    """
    result: dict = {'ticker': ticker, 'error': None}

    # ------------------------------------------------------------------
    # Step 1: Regime detection
    # ------------------------------------------------------------------
    try:
        from analytics.regime import detect_regime
        regime = detect_regime(vix, vvix=vvix)
        result['regime'] = regime
    except Exception as exc:
        logger.error("[%s] regime detection failed: %s", ticker, exc)
        result['error'] = f'regime_failed: {exc}'
        return result

    # ------------------------------------------------------------------
    # Step 2: IV surface + VRP computation
    # ------------------------------------------------------------------
    try:
        from analytics.iv_surface import compute_vrp
        vrp_data = compute_vrp(chain, ohlc, r)
        if vrp_data.get('error'):
            result['error'] = vrp_data['error']
            return result
        # Merge all iv_surface keys into result
        _surface_keys = [
            'iv30', 'iv60', 'iv30_td', 'iv60_td', 'vrp', 'ensemble_rv',
            'har', 'garch', 'ewma', 'has_arbitrage', 'exp_ivs',
        ]
        for k in _surface_keys:
            if k in vrp_data:
                result[k] = vrp_data[k]
    except Exception as exc:
        logger.error("[%s] IV surface failed: %s", ticker, exc)
        result['error'] = f'iv_surface_failed: {exc}'
        return result

    # ------------------------------------------------------------------
    # Step 3: All 12 VRP signals
    # ------------------------------------------------------------------
    try:
        from analytics.vrp_engine import compute_vrp_signals, vrp_timing_signal

        # Synthesise flat histories when none are supplied so downstream
        # signal computations always have something to work with.
        _iv30_hist = (
            iv30_history
            if iv30_history is not None
            else pd.Series([vrp_data['iv30']] * 30)
        )
        _vrp_hist = (
            vrp_history
            if vrp_history is not None
            else pd.Series([vrp_data['vrp']] * 30)
        )

        signals = compute_vrp_signals(
            vrp_data=vrp_data,
            ohlc=ohlc,
            chain=chain,
            iv30_history=_iv30_hist,
            vrp_history=_vrp_hist,
            spy_vrp=spy_vrp,
            beta=beta,
            vix=vix,
            r=r,
        )
        result['signals'] = signals

        timing_action, timing_reason = vrp_timing_signal(
            signals.get('vrp_5d_change', 0.0),
            signals.get('vrp_10d_change', 0.0),
            signals.get('vrp_pctile', 0.5),
        )
        result['timing_action'] = timing_action
        result['timing_reason'] = timing_reason
    except Exception as exc:
        logger.error("[%s] VRP signals failed: %s", ticker, exc)
        result['error'] = f'vrp_signals_failed: {exc}'
        return result

    # ------------------------------------------------------------------
    # Step 4: Composite score
    # ------------------------------------------------------------------
    try:
        from analytics.composite_score import composite_vrp_score
        score = composite_vrp_score(
            signals,
            has_earnings_in_window=has_earnings_in_window,
            near_term_earnings=near_term_earnings,
        )
        result['composite_score'] = score
    except Exception as exc:
        logger.error("[%s] composite score failed: %s", ticker, exc)
        result['error'] = f'composite_score_failed: {exc}'
        return result

    # ------------------------------------------------------------------
    # Convenience top-level keys for scanner (avoids nested dict access)
    # ------------------------------------------------------------------
    result['vrp_pctile']   = signals.get('vrp_pctile', 0.0)
    result['ivp']          = signals.get('ivp', 0.5)
    result['gex_billions'] = signals.get('gex_billions', 0.0)
    result['pcr_oi']       = signals.get('pcr_oi', 1.0)
    result['jump_pct']     = signals.get('jump_pct', 0.0)
    result['regime_label'] = regime['label']
    result['regime_mult']  = regime['multiplier']

    return result
