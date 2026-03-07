"""
analytics/iv_surface.py — IV surface pipeline for VRP signal computation.

Implements the full IV surface extraction pipeline (PRD §5, §6 Stage 2):

1. BSM price/IV inversion via Brent root-finding (no Newton iterations,
   guaranteed convergence for in-the-money options).
2. Liquidity filtering: bid > 0, OI > 100, spread < 15% of mid, strike
   range filters (puts 0.70x-1.05x spot, calls 0.95x-1.30x spot).
3. PCHIP monotone-cubic smile fitting — no spurious oscillations, no
   negative forward variance within a single expiration.
4. Total-variance-space interpolation for IV30 and IV60:
   total_var = IV^2 * DTE — linear interpolation in TV space prevents
   calendar arbitrage at interpolated points.
5. compute_vrp: combines IV surface with ensemble RV forecast from
   analytics.forecasters to produce the primary VRP signal.

Public exports: bsm_iv, fit_iv_smile, interpolate_iv_surface,
                compute_vrp, iv_smile_has_arbitrage
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq
from scipy.stats import norm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal BSM pricer
# ---------------------------------------------------------------------------

def bsm_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = 'call',
) -> float:
    """Black-Scholes-Merton option price (internal helper).

    Parameters
    ----------
    S : float
        Current underlying price.
    K : float
        Strike price.
    T : float
        Time to expiration in years (calendar-day fraction, e.g. 30/365).
    r : float
        Risk-free rate (continuously compounded, decimal).
    sigma : float
        Annualized implied volatility (decimal, e.g. 0.20 for 20%).
    option_type : str
        'call' or 'put'.

    Returns
    -------
    float
        BSM theoretical price, floored at 0.0.
    """
    if T <= 0 or sigma <= 0:
        # Return intrinsic value when expired or zero vol
        if option_type == 'call':
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    d1 = (np.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == 'call':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return max(float(price), 0.0)


# ---------------------------------------------------------------------------
# BSM IV inversion
# ---------------------------------------------------------------------------

def bsm_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = 'call',
) -> float | None:
    """BSM implied volatility via Brent root-finding (PRD §5 Stage 2 Step 3).

    Uses scipy.optimize.brentq over the search interval [1e-4, 20.0].
    Returns None for deep ITM options (price <= intrinsic + 1e-6) and for
    T <= 0, because BSM IV is undefined in those cases.

    Parameters
    ----------
    market_price : float
        Observed mid-price of the option.
    S : float
        Current underlying price.
    K : float
        Strike price.
    T : float
        Time to expiration in years (calendar-day fraction).
    r : float
        Risk-free rate (continuously compounded).
    option_type : str
        'call' or 'put'.

    Returns
    -------
    float or None
        Implied volatility in [0.01, 15.0] if a solution exists, otherwise None.
    """
    intrinsic = max(S - K, 0.0) if option_type == 'call' else max(K - S, 0.0)

    if market_price <= intrinsic + 1e-6:
        return None  # deep ITM or bad data — skip
    if T <= 0:
        return None

    def objective(sigma: float) -> float:
        return bsm_price(S, K, T, r, sigma, option_type) - market_price

    try:
        iv = brentq(objective, 1e-4, 20.0, xtol=1e-6, maxiter=100)
        return float(iv) if 0.01 <= iv <= 15.0 else None
    except ValueError:
        # brentq raises ValueError when f(a) and f(b) have the same sign,
        # i.e. the option price is outside BSM-reachable range
        return None


# ---------------------------------------------------------------------------
# Arbitrage checker
# ---------------------------------------------------------------------------

def iv_smile_has_arbitrage(
    strikes: np.ndarray,
    total_var: np.ndarray,
) -> bool:
    """Check whether a total-variance smile has a butterfly arbitrage violation.

    A single-expiration smile is butterfly-arbitrage-free when total variance
    w(K) = IV(K)^2 * T is non-decreasing as K increases (from OTM put to OTM
    call). A negative dw between any two consecutive strikes signals a
    violation (PRD §5).

    Parameters
    ----------
    strikes : np.ndarray
        Sorted strike prices (ascending).
    total_var : np.ndarray
        Total variance values w(K) = IV(K)^2 * T, same length as strikes.

    Returns
    -------
    bool
        True if any forward variance dw = w[i+1] - w[i] < -1e-6 (violation),
        False if the smile is arbitrage-free.
    """
    dw = np.diff(total_var)
    return bool(np.any(dw < -1e-6))


# ---------------------------------------------------------------------------
# Liquidity filter
# ---------------------------------------------------------------------------

def filter_chain_options(
    calls_df: pd.DataFrame,
    puts_df: pd.DataFrame,
    spot: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply PRD §5 Stage 2 Step 2 liquidity filters to a single expiration.

    Filters applied to both calls and puts:
        - bid > 0
        - openInterest > 100
        - (ask - bid) / ((ask + bid) / 2) < 0.15  (spread < 15% of mid)

    Strike range filters:
        - Puts : keep strikes in [0.70 * spot, 1.05 * spot]
        - Calls: keep strikes in [0.95 * spot, 1.30 * spot]

    If either DataFrame has fewer than 3 rows after filtering, the original
    (unfiltered) DataFrame is returned with a warning logged.

    Parameters
    ----------
    calls_df : pd.DataFrame
        Raw calls slice from Schwab chain for a single expiration.
        Must have columns: bid, ask, openInterest, strike.
    puts_df : pd.DataFrame
        Raw puts slice from Schwab chain for a single expiration.
    spot : float
        Current underlying price.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (filtered_calls, filtered_puts)
    """
    def _liquidity_mask(df: pd.DataFrame) -> pd.Series:
        mid = (df['bid'] + df['ask']) / 2.0
        spread_ratio = (df['ask'] - df['bid']) / mid.replace(0, np.nan)
        return (
            (df['bid'] > 0)
            & (df['openInterest'] > 100)
            & (spread_ratio < 0.15)
        )

    # Puts: OTM and near-ATM — 0.70x to 1.05x spot
    put_strike_mask = (puts_df['strike'] >= 0.70 * spot) & (puts_df['strike'] <= 1.05 * spot)
    puts_filtered = puts_df[_liquidity_mask(puts_df) & put_strike_mask]

    # Calls: OTM and near-ATM — 0.95x to 1.30x spot
    call_strike_mask = (calls_df['strike'] >= 0.95 * spot) & (calls_df['strike'] <= 1.30 * spot)
    calls_filtered = calls_df[_liquidity_mask(calls_df) & call_strike_mask]

    if len(puts_filtered) < 3:
        logger.warning(
            "filter_chain_options: puts filtered to %d rows (< 3); reverting to unfiltered.",
            len(puts_filtered),
        )
        puts_filtered = puts_df

    if len(calls_filtered) < 3:
        logger.warning(
            "filter_chain_options: calls filtered to %d rows (< 3); reverting to unfiltered.",
            len(calls_filtered),
        )
        calls_filtered = calls_df

    return calls_filtered, puts_filtered


# ---------------------------------------------------------------------------
# PCHIP smile fitter
# ---------------------------------------------------------------------------

def fit_iv_smile(
    strikes: np.ndarray,
    ivs: np.ndarray,
) -> PchipInterpolator | None:
    """Fit a PCHIP monotone-cubic spline to the IV smile (PRD §5 Stage 2 Step 4).

    PCHIP (Piecewise Cubic Hermite Interpolating Polynomial) ensures monotone
    local behaviour — no spurious oscillations in the fitted smile — which
    prevents negative forward variance within the fitted range.

    Parameters
    ----------
    strikes : np.ndarray
        Strike prices (need not be sorted).
    ivs : np.ndarray
        Implied volatilities corresponding to each strike. Values <= 0.01 or
        non-finite are treated as invalid and excluded.

    Returns
    -------
    PchipInterpolator or None
        Fitted interpolator if >= 3 valid (strike, IV) pairs exist, else None.
    """
    valid = np.isfinite(ivs) & (ivs > 0.01)
    s = np.asarray(strikes)[valid]
    v = np.asarray(ivs)[valid]

    if len(s) < 3:
        return None

    order = np.argsort(s)
    s_sorted = s[order]
    v_sorted = v[order]

    # Deduplicate: when the same strike appears from both puts and calls,
    # keep the average IV to avoid the "strictly increasing x" requirement
    unique_strikes, idx_inv = np.unique(s_sorted, return_inverse=True)
    if len(unique_strikes) < 3:
        return None
    unique_ivs = np.array(
        [v_sorted[idx_inv == i].mean() for i in range(len(unique_strikes))]
    )

    # extrapolate=False: returns NaN outside the fitted strike range
    return PchipInterpolator(unique_strikes, unique_ivs, extrapolate=False)


# ---------------------------------------------------------------------------
# Total-variance interpolation helper
# ---------------------------------------------------------------------------

def _interp_tv(
    dtes: np.ndarray,
    tot_vars: np.ndarray,
    target_dte: float,
) -> float | None:
    """Interpolate (or extrapolate) total variance at target_dte.

    Interpolation is performed in total-variance space
    (TV = IV^2 * DTE) to prevent arbitrage at interpolated points.
    The result is converted back to annualized vol.

    Parameters
    ----------
    dtes : np.ndarray
        DTE values (calendar days) for each expiration, sorted ascending.
    tot_vars : np.ndarray
        Total variance = IV^2 * DTE for each expiration.
    target_dte : float
        Target DTE to interpolate to (e.g. 30 or 60).

    Returns
    -------
    float or None
        Annualized implied volatility at target_dte, or None if the result
        is non-finite or non-positive.
    """
    tv = float(np.interp(target_dte, dtes, tot_vars))
    if tv <= 0 or not np.isfinite(tv):
        return None
    # Annualized vol from total variance: sqrt(TV / DTE)
    return float(np.sqrt(tv / target_dte))


# ---------------------------------------------------------------------------
# IV surface
# ---------------------------------------------------------------------------

def interpolate_iv_surface(chain: dict, spot: float, r: float) -> dict:
    """Extract per-expiration ATM IVs and interpolate to IV30 and IV60.

    Implements PRD §5 Stage 2 Steps 3-6:
    1. For each expiration: filter options, invert BSM to per-strike IVs,
       fit PCHIP smile, evaluate ATM IV at spot.
    2. Sort by DTE. Check for negative forward variance across expirations.
    3. Interpolate total-variance (IV^2 * DTE) linearly to DTE=30 and DTE=60.

    Parameters
    ----------
    chain : dict
        Schwab options chain dict with keys:
            'underlying_price': float
            'expirations': list of dicts, each with keys:
                'dte': int (calendar days to expiration)
                'calls': pd.DataFrame
                'puts' : pd.DataFrame
    spot : float
        Current underlying price (should equal chain['underlying_price']).
    r : float
        Risk-free rate (continuously compounded, decimal).

    Returns
    -------
    dict with keys:
        iv30         : float or None — 30-day IV interpolated in TV space
        iv60         : float or None — 60-day IV interpolated in TV space
        exp_ivs      : list of dicts — per-expiration {dte, atm_iv, total_var}
        has_arbitrage: bool — True if any negative forward variance detected
    """
    exp_ivs: list[dict] = []

    for exp in chain['expirations']:
        dte = exp['dte']
        T = dte / 365.0  # calendar-day fraction for BSM

        calls, puts = filter_chain_options(exp['calls'], exp['puts'], spot)

        # Per-strike BSM inversion for puts then calls
        ivs_list: list[tuple[float, float]] = []

        for _, row in puts.iterrows():
            mid = (row['bid'] + row['ask']) / 2.0
            iv = bsm_iv(mid, spot, row['strike'], T, r, 'put')
            if iv is not None:
                ivs_list.append((float(row['strike']), iv))

        for _, row in calls.iterrows():
            mid = (row['bid'] + row['ask']) / 2.0
            iv = bsm_iv(mid, spot, row['strike'], T, r, 'call')
            if iv is not None:
                ivs_list.append((float(row['strike']), iv))

        if len(ivs_list) < 3:
            logger.warning(
                "interpolate_iv_surface: expiration DTE=%d has only %d valid IVs; skipping.",
                dte, len(ivs_list),
            )
            continue

        strikes_arr = np.array([x[0] for x in ivs_list])
        ivs_arr = np.array([x[1] for x in ivs_list])

        smile = fit_iv_smile(strikes_arr, ivs_arr)
        if smile is None:
            logger.warning(
                "interpolate_iv_surface: fit_iv_smile returned None for DTE=%d; skipping.", dte
            )
            continue

        atm_iv = float(smile(spot))

        if not np.isfinite(atm_iv) or atm_iv <= 0:
            # PCHIP returned NaN at spot (spot outside fitted strike range) —
            # fall back to nearest valid IV
            dists = np.abs(strikes_arr - spot)
            atm_iv = float(ivs_arr[np.argmin(dists)])
            logger.warning(
                "interpolate_iv_surface: PCHIP returned non-finite ATM IV at DTE=%d; "
                "using nearest-strike IV=%.4f instead.", dte, atm_iv
            )

        exp_ivs.append({
            'dte': dte,
            'atm_iv': atm_iv,
            'total_var': atm_iv ** 2 * dte,
        })

    if len(exp_ivs) < 2:
        return {
            'iv30': None,
            'iv60': None,
            'error': 'Insufficient expirations for interpolation',
        }

    # Sort by DTE ascending before interpolation
    exp_ivs.sort(key=lambda x: x['dte'])
    dtes = np.array([e['dte'] for e in exp_ivs])
    tot_vars = np.array([e['total_var'] for e in exp_ivs])

    # Check for negative forward variance (calendar arbitrage across expirations)
    has_arb = bool(np.any(np.diff(tot_vars) < -1e-6))
    if has_arb:
        logger.warning(
            "interpolate_iv_surface: Negative forward variance detected — "
            "IV surface has calendar arbitrage."
        )

    iv30 = _interp_tv(dtes, tot_vars, target_dte=30)
    iv60 = _interp_tv(dtes, tot_vars, target_dte=60)

    return {
        'iv30': iv30,
        'iv60': iv60,
        'exp_ivs': exp_ivs,
        'has_arbitrage': has_arb,
    }


# ---------------------------------------------------------------------------
# VRP computation
# ---------------------------------------------------------------------------

def compute_vrp(chain: dict, ohlc: pd.DataFrame, r: float) -> dict:
    """Compute the Volatility Risk Premium (VRP) signal (PRD §2.1, §6.3.4).

    VRP = IV30_td - ensemble_RV

    IV30 is converted from calendar-day to trading-day basis via
    iv_to_trading_day() before subtraction so both quantities are on the
    same annualization convention (252 trading days).

    Parameters
    ----------
    chain : dict
        Schwab options chain dict (see interpolate_iv_surface for schema).
    ohlc : pd.DataFrame
        OHLCV DataFrame with columns Open, High, Low, Close.
        Used for RV estimation; should cover at least 252 trading days.
    r : float
        Risk-free rate (continuously compounded, decimal).

    Returns
    -------
    dict with keys:
        iv30        : float — 30-day IV on calendar-day basis
        iv60        : float or None — 60-day IV on calendar-day basis
        iv30_td     : float — iv30 rescaled to trading-day basis (primary signal)
        iv60_td     : float or None — iv60 on trading-day basis
        vrp         : float — iv30_td minus ensemble_rv (positive = overpriced vol)
        ensemble_rv : float — mean of HAR, GARCH-GJR, EWMA forecasts
        har         : float — HAR-RV forecast component
        garch       : float — GARCH-GJR forecast component (or EWMA fallback)
        ewma        : float — EWMA forecast component
        has_arbitrage: bool — from IV surface check
        exp_ivs     : list — per-expiration {dte, atm_iv, total_var}
    """
    from analytics.realized_vol import iv_to_trading_day
    from analytics.forecasters import ensemble_rv_forecast

    spot = chain['underlying_price']
    returns = np.log(ohlc['Close'] / ohlc['Close'].shift(1)).dropna()

    surface = interpolate_iv_surface(chain, spot, r)

    if surface.get('iv30') is None:
        return {'error': 'IV surface failed', **surface}

    # Convert calendar-day IV to trading-day basis for fair VRP comparison
    iv30_td = iv_to_trading_day(surface['iv30'])
    iv60_td = iv_to_trading_day(surface['iv60']) if surface.get('iv60') is not None else None

    ens = ensemble_rv_forecast(ohlc, returns)
    vrp = iv30_td - ens['ensemble']

    return {
        'iv30': surface['iv30'],
        'iv60': surface.get('iv60'),
        'iv30_td': iv30_td,
        'iv60_td': iv60_td,
        'vrp': float(vrp),
        'ensemble_rv': ens['ensemble'],
        'har': ens['har'],
        'garch': ens['garch'],
        'ewma': ens['ewma'],
        'has_arbitrage': surface.get('has_arbitrage', False),
        'exp_ivs': surface.get('exp_ivs', []),
    }
