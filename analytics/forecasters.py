"""
analytics/forecasters.py — RV Forecasting Models and Jump Separation.

Implements three independent realized-volatility forecasters and their
ensemble average, plus Bipower Variation for jump-diffusion decomposition.

Models:
    HAR-RV      : Heterogeneous Autoregressive RV via OLS (PRD §6.3.1)
    GARCH-GJR   : GJR-GARCH(1,1,1) with student-t innovations (PRD §6.3.2)
    EWMA        : RiskMetrics EWMA lambda=0.94 (PRD §6.3.3)
    Ensemble    : Unweighted mean of all three

Jump decomposition:
    Bipower Variation (BPV) : diffusive variance proxy (PRD §6.4)
    jump_stats              : jump variance, pct, VRP quality flags
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HAR-RV
# ---------------------------------------------------------------------------

def har_rv_forecast(rv_daily: pd.Series, fit_window: int = 252) -> float:
    """Heterogeneous Autoregressive RV forecast (PRD §6.3.1).

    Fits an OLS regression of future 21-day RV on three lagged RV components:
        daily (rv_d), weekly 5-day mean (rv_w), monthly 21-day mean (rv_m).

    Falls back to the 21-day trailing mean when fewer than 63 valid training
    rows exist (< 3 months of history).

    Parameters
    ----------
    rv_daily : pd.Series
        Daily realized volatility series (annualized, e.g. from yang_zhang_vol).
    fit_window : int
        Maximum number of historical rows used to fit OLS (default 252 = 1 year).

    Returns
    -------
    float
        Predicted annualized RV 21 trading days ahead. Minimum 0.01.
    """
    rv_d = rv_daily
    rv_w = rv_daily.rolling(5).mean()
    rv_m = rv_daily.rolling(21).mean()

    X = pd.DataFrame({'d': rv_d, 'w': rv_w, 'm': rv_m})
    y = rv_daily.shift(-21)  # target: RV 21 trading days forward

    # Use the last fit_window rows where both X and y are non-NaN
    idx = X.dropna().index.intersection(y.dropna().index)[-fit_window:]

    if len(idx) < 63:
        logger.warning(
            "har_rv_forecast: fewer than 63 valid training rows (%d found); "
            "falling back to 21-day trailing mean.", len(idx)
        )
        return float(rv_daily.iloc[-21:].mean())

    model = LinearRegression().fit(X.loc[idx], y.loc[idx])

    # Predict using the last available daily/weekly/monthly values
    x_pred = [[float(rv_d.iloc[-1]), float(rv_w.iloc[-1]), float(rv_m.iloc[-1])]]
    forecast = float(model.predict(x_pred)[0])
    return max(forecast, 0.01)


# ---------------------------------------------------------------------------
# EWMA
# ---------------------------------------------------------------------------

def ewma_rv_forecast(returns: pd.Series, lam: float = 0.94) -> float:
    """RiskMetrics EWMA realized variance forecast (PRD §6.3.3).

    Applies exponentially decaying weights to squared daily log-returns.
    When lam=0 the weight vector degenerates to [1, 0, 0, ...], so the
    forecast equals sqrt(returns[-1]^2 * 252).

    Parameters
    ----------
    returns : pd.Series
        Daily log-returns (decimal, e.g. 0.01 = 1%).
    lam : float
        Decay factor in [0, 1). RiskMetrics standard is 0.94.

    Returns
    -------
    float
        Annualized EWMA volatility forecast. Always positive.
    """
    r2 = (returns ** 2).to_numpy()
    n = len(r2)

    # weights[0] corresponds to the oldest observation, weights[-1] to most recent
    indices = np.arange(n - 1, -1, -1)          # [n-1, n-2, ..., 0]
    weights = (1 - lam) * (lam ** indices)        # geometric decay
    total = weights.sum()
    if total == 0:
        # Edge case: lam == 1 or all weights zero — uniform average
        weights = np.ones(n) / n
    else:
        weights = weights / total                  # normalize to sum=1

    ewma_var = float(np.dot(weights, r2))
    return float(np.sqrt(ewma_var * 252))


# ---------------------------------------------------------------------------
# GARCH-GJR
# ---------------------------------------------------------------------------

def garch_rv_forecast(returns: pd.Series) -> float:
    """GJR-GARCH(1,1,1) with student-t forecast (PRD §6.3.2).

    Fits an asymmetric GARCH model that accounts for the leverage effect
    (negative returns increase future variance more than positive returns of
    the same magnitude). Uses arch library conventions: returns are scaled to
    percentage units before fitting.

    Falls back to EWMA on any convergence or numerical failure.

    Parameters
    ----------
    returns : pd.Series
        Daily log-returns (decimal, e.g. 0.01 = 1%).

    Returns
    -------
    float
        Annualized volatility forecast (21-day horizon). Always positive.
    """
    try:
        from arch import arch_model

        model = arch_model(
            returns * 100,        # scale to percentage returns (arch convention)
            vol='Garch',
            p=1,
            o=1,                  # GJR asymmetry term
            q=1,
            dist='t',             # student-t for fat tails
        )
        res = model.fit(disp='off')
        forecast = res.forecast(horizon=21)
        # forecast.variance shape: (1, 21) — daily variance in (returns*100)^2 units
        var_forecast_daily = forecast.variance.values[-1].mean() / 10000  # back to decimal
        return float(np.sqrt(var_forecast_daily * 252))
    except Exception as e:
        logger.warning("GARCH fit failed: %s; falling back to EWMA", e)
        return ewma_rv_forecast(returns)


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------

def ensemble_rv_forecast(ohlc: pd.DataFrame, returns: pd.Series) -> dict:
    """Unweighted ensemble of HAR-RV, GARCH-GJR, and EWMA forecasts.

    Defers import of yang_zhang_vol to avoid circular imports at module load
    time (analytics.realized_vol may also import from this module downstream).

    If garch_rv_forecast raises, EWMA is substituted so the ensemble remains
    a mean of three values (HAR, EWMA, EWMA).

    Parameters
    ----------
    ohlc : pd.DataFrame
        OHLCV DataFrame with columns Open, High, Low, Close.
    returns : pd.Series
        Daily log-returns corresponding to ohlc.

    Returns
    -------
    dict with keys:
        har      : float  — HAR-RV forecast
        garch    : float  — GARCH-GJR forecast (or EWMA fallback)
        ewma     : float  — EWMA forecast
        ensemble : float  — mean of all three (exact arithmetic mean)
    """
    # Deferred import: avoids circular dependency at module load time
    from analytics.realized_vol import yang_zhang_vol  # noqa: PLC0415

    rv_daily = yang_zhang_vol(ohlc, 21).dropna()

    har = har_rv_forecast(rv_daily)
    ewma = ewma_rv_forecast(returns)

    try:
        garch = garch_rv_forecast(returns)
    except Exception as e:
        logger.warning("ensemble_rv_forecast: GARCH failed (%s); using EWMA substitute.", e)
        garch = ewma

    ensemble = (har + garch + ewma) / 3.0

    return {
        'har': float(har),
        'garch': float(garch),
        'ewma': float(ewma),
        'ensemble': float(ensemble),
    }


# ---------------------------------------------------------------------------
# Bipower Variation
# ---------------------------------------------------------------------------

def bipower_variation(close: pd.Series, window: int = 21) -> float:
    """Annualized diffusive (continuous) volatility via Bipower Variation (PRD §6.4).

    BPV approximates the quadratic variation due to the continuous price path,
    excluding jumps. Uses consecutive absolute log-returns scaled by pi/2.

    Parameters
    ----------
    close : pd.Series
        Close price series.
    window : int
        Rolling window in trading days (default 21).

    Returns
    -------
    float
        Annualized diffusive volatility (square root of annualized BPV).
        Always positive (minimum floor 1e-8 before sqrt).
    """
    log_ret = np.log(close / close.shift(1)).dropna()
    abs_ret = log_ret.abs()
    bpv_var = (np.pi / 2) * (abs_ret * abs_ret.shift(1)).rolling(window).mean() * 252
    bpv_latest_var = float(bpv_var.iloc[-1])
    return float(np.sqrt(max(bpv_latest_var, 1e-8)))  # vol, not variance


# ---------------------------------------------------------------------------
# Jump Statistics
# ---------------------------------------------------------------------------

def jump_stats(rv_yz_21d: float, bpv: float, iv30_td: float) -> dict:
    """Decompose realized variance into jump and diffusive components (PRD §6.4).

    Uses BPV as a proxy for the diffusive (continuous) component of RV.
    Jump variance = max(RV^2 - BPV^2, 0).

    Parameters
    ----------
    rv_yz_21d : float
        21-day Yang-Zhang realized volatility (annualized).
    bpv : float
        Bipower variation estimate (annualized diffusive vol).
    iv30_td : float
        30-day implied volatility in trading-day terms (annualized).

    Returns
    -------
    dict with keys:
        jump_var      : float  — jump variance contribution
        jump_pct      : float  — jump fraction of implied variance, clipped [0, 1]
        bpv           : float  — diffusive vol (same as input)
        diffusive_vrp : float  — signed VRP from diffusive component only
        quality       : str    — 'clean' | 'mixed' | 'jump_dominated'
        flag          : str    — position-sizing guidance or empty string
    """
    rv_var = rv_yz_21d ** 2
    bpv_var = bpv ** 2
    jump_var = max(rv_var - bpv_var, 0.0)
    iv30_var = iv30_td ** 2

    jump_pct = jump_var / max(iv30_var, 1e-8)   # fraction of implied variance

    diffusive_vrp_vol = np.sign(iv30_var - bpv_var) * np.sqrt(abs(iv30_var - bpv_var))

    quality = (
        'clean'            if jump_pct < 0.20 else
        'mixed'            if jump_pct < 0.35 else
        'jump_dominated'
    )

    flag = (
        ''                                                                   if jump_pct < 0.20 else
        'Reduce position size 25% — mixed jump'                              if jump_pct < 0.35 else
        'NO-GO unless diffusive VRP qualifies — jump risk dominates'
    )

    return {
        'jump_var':      float(jump_var),
        'jump_pct':      float(np.clip(jump_pct, 0, 1)),
        'bpv':           float(bpv),
        'diffusive_vrp': float(diffusive_vrp_vol),
        'quality':       quality,
        'flag':          flag,
    }
