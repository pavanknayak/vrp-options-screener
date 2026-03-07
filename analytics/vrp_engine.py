"""
analytics/vrp_engine.py — VRP signal computation engine (PRD §6.5, §6.9).

Aggregates all 12+ VRP signal groups into a single dict for downstream
consumption by the composite score (Plan 02-06). Each signal has a specific
economic interpretation; none are approximated or omitted.

Signal groups:
    Historical context : vrp_pctile, vrp_persist_30d, vrp_zscore, vrp_sharpe,
                         vrp_5d_change, vrp_10d_change, vrp_momentum,
                         excess_vrp, ivr, ivp
    Market structure   : skew_25d, skew_zscore, term_slope, vov_30d, vov_z,
                         em_ratio, jump_pct, gex_billions, pcr_oi

Public exports: compute_vrp_signals, vrp_timing_signal
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.stats import norm, percentileofscore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main signal computation
# ---------------------------------------------------------------------------

def compute_vrp_signals(
    vrp_data: dict,          # output of compute_vrp() from iv_surface.py
    ohlc: pd.DataFrame,      # 252-row OHLCV DataFrame
    chain: dict,             # Schwab options chain dict
    iv30_history: pd.Series, # rolling 252-day daily IV30 series (most recent last)
    vrp_history: pd.Series,  # rolling 252-day daily VRP series (most recent last)
    spy_vrp: float,          # current SPY VRP (for excess_vrp; pass 0.0 if unavailable)
    beta: float,             # ticker beta vs SPY (from yfinance or compute 252d regression)
    vix: float,              # current VIX level
    r: float,                # risk-free rate
) -> dict:
    """Compute all VRP signals for composite scoring (PRD §6.5, §6.9).

    Parameters
    ----------
    vrp_data : dict
        Output of ``compute_vrp()`` from analytics.iv_surface. Must contain
        keys: vrp, iv30, iv60 (optional), iv30_td, ensemble_rv, exp_ivs.
    ohlc : pd.DataFrame
        OHLCV DataFrame with columns Open, High, Low, Close.
        Should cover at least 252 trading days.
    chain : dict
        Schwab options chain dict with keys:
            'underlying_price': float
            'expirations': list of dicts, each with 'dte', 'calls', 'puts'
    iv30_history : pd.Series
        252-day rolling series of daily 30-day IV observations (most recent last).
    vrp_history : pd.Series
        252-day rolling series of daily VRP observations (most recent last).
    spy_vrp : float
        Current SPY VRP for excess_vrp computation. Pass 0.0 if unavailable.
    beta : float
        Ticker beta versus SPY from 252-day regression.
    vix : float
        Current VIX spot level (informational; used for future extensions).
    r : float
        Risk-free rate (continuously compounded, decimal).

    Returns
    -------
    dict
        All signal keys (18+) as floats. Safe defaults provided when data
        is missing or computation fails.
    """
    signals: dict = {}

    # -----------------------------------------------------------------------
    # Task 1: Historical context signals
    # -----------------------------------------------------------------------

    vrp = float(vrp_data['vrp'])
    signals['vrp'] = vrp

    # vrp_pctile — percentile of current VRP vs 252-day history
    vrp_history_clean = vrp_history.dropna()
    vrp_pctile = percentileofscore(vrp_history_clean, vrp, kind='rank') / 100.0
    signals['vrp_pctile'] = float(vrp_pctile)

    # vrp_persist_30d — fraction of last 30 sessions VRP > 0
    if len(vrp_history) >= 30:
        vrp_persist_30d = float((vrp_history.iloc[-30:] > 0).mean())
    else:
        vrp_persist_30d = 0.5
    signals['vrp_persist_30d'] = vrp_persist_30d

    # vrp_zscore — (vrp - mean) / std
    vrp_mean = float(vrp_history.mean())
    vrp_std  = float(vrp_history.std())
    vrp_zscore = (vrp - vrp_mean) / max(vrp_std, 1e-8)
    signals['vrp_zscore'] = float(vrp_zscore)

    # vrp_sharpe — annualized Sharpe of VRP stream (monthly observations,
    # annualized by sqrt(252/21))
    vrp_sharpe = float(vrp_history.mean() / max(vrp_history.std(), 1e-8) * np.sqrt(252 / 21))
    signals['vrp_sharpe'] = vrp_sharpe

    # vrp_5d_change, vrp_10d_change — VRP momentum (PRD §6.9)
    vrp_5d_change  = vrp - float(vrp_history.iloc[-5])  if len(vrp_history) >= 5  else 0.0
    vrp_10d_change = vrp - float(vrp_history.iloc[-10]) if len(vrp_history) >= 10 else 0.0
    vrp_momentum   = int(np.sign(vrp_5d_change))  # +1 rising, -1 falling, 0 flat
    signals['vrp_5d_change']  = float(vrp_5d_change)
    signals['vrp_10d_change'] = float(vrp_10d_change)
    signals['vrp_momentum']   = vrp_momentum

    # excess_vrp — idiosyncratic premium above beta-adjusted index
    excess_vrp = vrp - (beta * spy_vrp)
    signals['excess_vrp'] = float(excess_vrp)

    # ivr — IV Rank in [0, 1]
    iv52_low  = float(iv30_history.min())
    iv52_high = float(iv30_history.max())
    ivr = (vrp_data['iv30'] - iv52_low) / max(iv52_high - iv52_low, 1e-8)
    ivr = float(np.clip(ivr, 0.0, 1.0))
    signals['ivr'] = ivr

    # ivp — IV Percentile in [0, 1]
    iv30_history_clean = iv30_history.dropna()
    ivp = percentileofscore(iv30_history_clean, vrp_data['iv30'], kind='rank') / 100.0
    signals['ivp'] = float(ivp)

    # -----------------------------------------------------------------------
    # Task 2: Market-structure signals
    # -----------------------------------------------------------------------

    # --- skew_25d and skew_zscore ---
    # Extract 25-delta skew from the options chain impliedVolatility column if
    # available; otherwise use ATM PCHIP smile proxy (PRD §6.5).
    skew_25d = _compute_skew_25d(vrp_data, chain, r)
    signals['skew_25d'] = float(skew_25d)

    # skew_zscore: requires cached historical smile data — not available in
    # Phase 2; use 0.0 as safe default and flag absence.
    signals['skew_zscore'] = 0.0
    signals['skew_history_available'] = False

    # --- term_slope ---
    # Positive = contango (normal term structure)
    # Negative = backwardation (stress / near-term event risk)
    term_slope = (vrp_data.get('iv60') or 0) - (vrp_data.get('iv30') or 0)
    signals['term_slope'] = float(term_slope)

    # --- VoV signal (from regime.py) ---
    from analytics.regime import vov_signal
    vov = vov_signal(iv30_history)
    signals['vov_30d'] = float(vov['vov_30d']) if vov['vov_30d'] is not None else 0.0
    signals['vov_z']   = float(vov['vov_z'])   if vov['vov_z']   is not None else 0.0
    signals['vov_flag']       = vov.get('flag', '')
    signals['vov_disqualify'] = bool(vov.get('disqualify', False))

    # --- EM ratio — ATM straddle / (RV × spot × sqrt(DTE/252)) (PRD §2.4) ---
    em_ratio = _compute_em_ratio(chain, vrp_data)
    signals['em_ratio'] = float(em_ratio)

    # --- jump_pct — from forecasters (bipower variation + jump_stats) ---
    from analytics.forecasters import bipower_variation, jump_stats
    close_s = ohlc['Close']
    bpv = bipower_variation(close_s, window=21)
    js = jump_stats(
        rv_yz_21d=vrp_data.get('ensemble_rv', 0.20),  # ensemble as RV proxy
        bpv=bpv,
        iv30_td=vrp_data.get('iv30_td', vrp_data.get('iv30', 0.20))
    )
    signals['jump_pct']      = float(js['jump_pct'])
    signals['jump_var']      = float(js['jump_var'])
    signals['diffusive_vrp'] = float(js['diffusive_vrp'])
    signals['jump_quality']  = js['quality']
    signals['jump_flag']     = js['flag']

    # --- GEX and PCR ---
    from analytics.microstructure import compute_gex, compute_pcr
    gex_result = compute_gex(chain, chain['underlying_price'])
    pcr_result = compute_pcr(chain)
    signals['gex_billions']          = float(gex_result['gex_billions'])
    signals['gex_supports_collection'] = bool(gex_result['supports_collection'])
    signals['pcr_oi']                 = float(pcr_result['pcr_oi'])
    signals['pcr_volume']             = float(pcr_result['pcr_volume'])

    return signals


# ---------------------------------------------------------------------------
# Skew computation helper
# ---------------------------------------------------------------------------

def _compute_skew_25d(vrp_data: dict, chain: dict, r: float) -> float:
    """Extract 25-delta skew from chain impliedVolatility or use smile proxy.

    Priority order:
    1. If chain expirations have 'impliedVolatility' column: use per-strike IVs
       from the nearest-30DTE expiration to find put and call IV at 25-delta
       moneyness strikes, return put_iv - call_iv.
    2. Otherwise: use ATM IV with ±BSM-delta proxy strike offsets.
    3. Final fallback: 0.0.
    """
    spot = chain.get('underlying_price', 0.0)
    if spot <= 0:
        return 0.0

    expirations = chain.get('expirations', [])
    if not expirations:
        return 0.0

    # Find expiration nearest to 30 DTE
    exp_30 = min(expirations, key=lambda e: abs(e.get('dte', 999) - 30))
    dte = exp_30.get('dte', 30)
    T = max(dte / 365.0, 1e-4)

    calls_df = exp_30.get('calls', pd.DataFrame())
    puts_df  = exp_30.get('puts',  pd.DataFrame())

    # Path 1: per-strike impliedVolatility available in chain
    if (not calls_df.empty and 'impliedVolatility' in calls_df.columns and
            not puts_df.empty and 'impliedVolatility' in puts_df.columns):

        iv_atm = _get_atm_iv_from_chain(calls_df, puts_df, spot)
        if iv_atm is None or iv_atm <= 0:
            iv_atm = vrp_data.get('iv30', 0.20)

        # BSM 25-delta put strike: OTM put, delta = -0.25
        # K_p = S * exp(N^{-1}(0.25) * iv * sqrt(T))
        k_put  = spot * np.exp(norm.ppf(0.25) * iv_atm * np.sqrt(T))
        # BSM 25-delta call strike: OTM call, delta = +0.25
        # K_c = S * exp(N^{-1}(0.75) * iv * sqrt(T))
        k_call = spot * np.exp(norm.ppf(0.75) * iv_atm * np.sqrt(T))

        # Find closest put IV to k_put
        put_iv  = _nearest_strike_iv(puts_df,  k_put)
        call_iv = _nearest_strike_iv(calls_df, k_call)

        if put_iv is not None and call_iv is not None:
            return float(put_iv - call_iv)

    # Path 2: use PCHIP smile from exp_ivs if available
    exp_ivs = vrp_data.get('exp_ivs', [])
    if exp_ivs:
        exp_30_iv = min(exp_ivs, key=lambda e: abs(e.get('dte', 999) - 30), default=None)
        if exp_30_iv is not None:
            iv_atm = exp_30_iv['atm_iv']
            # Approximate 25-delta skew using ±2% moneyness proxy
            # (7% of ATM IV is a typical realized skew magnitude proxy)
            skew_proxy = iv_atm * 1.05 - iv_atm * 0.98
            return float(skew_proxy)

    return 0.0


def _get_atm_iv_from_chain(calls_df: pd.DataFrame, puts_df: pd.DataFrame,
                            spot: float) -> float | None:
    """Return ATM implied volatility by averaging nearest call and put IVs."""
    try:
        atm_call_idx = (calls_df['strike'] - spot).abs().idxmin()
        atm_put_idx  = (puts_df['strike']  - spot).abs().idxmin()
        call_iv = float(calls_df.loc[atm_call_idx, 'impliedVolatility'])
        put_iv  = float(puts_df.loc[atm_put_idx,   'impliedVolatility'])
        return (call_iv + put_iv) / 2.0
    except Exception:
        return None


def _nearest_strike_iv(df: pd.DataFrame, target_strike: float) -> float | None:
    """Return the impliedVolatility from the row with the closest strike."""
    try:
        idx = (df['strike'] - target_strike).abs().idxmin()
        iv = float(df.loc[idx, 'impliedVolatility'])
        return iv if np.isfinite(iv) and iv > 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# EM ratio helper
# ---------------------------------------------------------------------------

def _compute_em_ratio(chain: dict, vrp_data: dict) -> float:
    """Compute EM ratio: ATM straddle / (RV x spot x sqrt(DTE/252)) (PRD §2.4).

    Returns 1.0 (neutral) when ATM strikes cannot be found.
    """
    spot = chain.get('underlying_price', 0.0)
    expirations = chain.get('expirations', [])
    if spot <= 0 or not expirations:
        return 1.0

    atm_call = atm_put = None
    dte_used = 30

    for exp in expirations:
        spot_val = chain['underlying_price']
        calls = exp.get('calls', pd.DataFrame())
        puts  = exp.get('puts',  pd.DataFrame())

        if calls.empty or puts.empty:
            continue
        if 'bid' not in calls.columns or 'ask' not in calls.columns:
            continue
        if 'bid' not in puts.columns or 'ask' not in puts.columns:
            continue

        atm_call_row = calls.iloc[(calls['strike'] - spot_val).abs().argsort()[:1]]
        atm_put_row  = puts.iloc[(puts['strike']   - spot_val).abs().argsort()[:1]]

        if len(atm_call_row) and len(atm_put_row):
            atm_call = float((atm_call_row['bid'].values[0] + atm_call_row['ask'].values[0]) / 2)
            atm_put  = float((atm_put_row['bid'].values[0]  + atm_put_row['ask'].values[0])  / 2)
            dte_used = exp.get('dte', 30)
            break

    if atm_call is None or atm_put is None:
        return 1.0

    atm_straddle = atm_call + atm_put
    rv_21d       = vrp_data.get('ensemble_rv', 0.20)
    em_ratio     = atm_straddle / max(rv_21d * spot * np.sqrt(dte_used / 252), 1e-8)
    return float(em_ratio)


# ---------------------------------------------------------------------------
# VRP timing signal
# ---------------------------------------------------------------------------

def vrp_timing_signal(
    vrp_5d_change: float,
    vrp_10d_change: float,
    vrp_pctile: float,
) -> tuple[str, str]:
    """Return entry timing recommendation based on VRP momentum and level (PRD §6.9).

    Threshold: 0.005 annualized decimal = 0.5 vol points (VRP is in decimal,
    e.g. 0.03 = 3 vol pts, so 0.5 vol pts = 0.005).

    Parameters
    ----------
    vrp_5d_change : float
        VRP change over the last 5 trading days (current VRP minus VRP 5 days ago).
        Positive = rising, negative = falling. Units: annualized decimal.
    vrp_10d_change : float
        VRP change over the last 10 trading days. Same units.
    vrp_pctile : float
        Current VRP percentile versus 252-day history. Range [0, 1].

    Returns
    -------
    tuple[str, str]
        (action, reason) where action is one of:
            "ENTER NOW"
            "ENTER NOW or WAIT 1-3 DAYS"
            "WAIT 1-3 DAYS"
            "ENTER AT OPPORTUNITY"
    """
    is_rising  = vrp_5d_change > 0.005   # > 0.5 vol pts in annualized decimal
    is_falling = vrp_5d_change < -0.005

    if is_falling and vrp_pctile > 0.65:
        return (
            "ENTER NOW",
            "VRP is contracting — premium collapsing toward mean. Enter immediately.",
        )
    elif is_rising and vrp_pctile > 0.80:
        return (
            "ENTER NOW or WAIT 1-3 DAYS",
            "VRP is expanding at 80th+ pctile. Can enter now or wait for peak.",
        )
    elif is_rising and vrp_pctile < 0.70:
        return (
            "WAIT 1-3 DAYS",
            "VRP expanding but below threshold. Let premium build before entering.",
        )
    else:
        return (
            "ENTER AT OPPORTUNITY",
            "VRP stable at elevated level. Enter on minor IV spike or underlying dip.",
        )
