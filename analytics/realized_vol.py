"""
analytics/realized_vol.py — Realized volatility estimators for the VRP engine.

Three estimators are provided, in decreasing order of statistical efficiency:

Yang-Zhang (~14x efficiency vs close-to-close):
    Combines overnight gaps (open-to-prev-close), intraday drift
    (close-to-open), and Rogers-Satchell intraday variance. Correctly
    handles both overnight gaps and intraday drift — essential for stocks
    that gap on earnings or macro events.

Parkinson (~5x efficiency vs close-to-close):
    Uses log(High/Low) range. Efficient but underestimates vol when there
    are significant overnight gaps.

Garman-Klass (~8x efficiency vs close-to-close):
    Extends Parkinson with open/close info. Better than Parkinson but still
    biased when overnight gaps dominate.

All functions return a pd.Series of annualized volatilities (one value per
trading day, rolling). Callers use .iloc[-1] for the current point estimate.
Values are clipped to a minimum of 0.001 to prevent downstream log(0) errors.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_REQUIRED_COLS = ["Open", "High", "Low", "Close"]
_ANNUALIZE = 252


def _validate_ohlc(ohlc: pd.DataFrame) -> None:
    """Raise ValueError if any required OHLC column is missing."""
    missing = [c for c in _REQUIRED_COLS if c not in ohlc.columns]
    if missing:
        raise ValueError(
            f"ohlc DataFrame is missing required columns: {missing}. "
            f"Expected columns: {_REQUIRED_COLS}. Got: {list(ohlc.columns)}"
        )


def yang_zhang_vol(ohlc: pd.DataFrame, window: int = 21) -> pd.Series:
    """Yang-Zhang realized volatility estimator.

    Combines overnight return variance, intraday return variance, and the
    Rogers-Satchell estimator via a weighting constant k. This is the primary
    RV estimator used in VRP signal computation.

    Formula (PRD §6.2):
        log_oc = log(Open_t / Close_{t-1})          # overnight return
        log_co = log(Close_t / Open_t)               # intraday return
        log_ho = log(High_t / Open_t)
        log_lo = log(Low_t / Open_t)
        rs_t   = log_ho*(log_ho - log_co) + log_lo*(log_lo - log_co)
        k      = 0.34 / (1.34 + (window+1)/(window-1))
        sigma  = sqrt(252 * (
                     (1-k) * log_co.rolling(window).var()
                   + k     * rs.rolling(window).mean()
                   +         log_oc.rolling(window).var()
                 ))

    Parameters
    ----------
    ohlc : pd.DataFrame
        DataFrame with columns Open, High, Low, Close (and optionally Volume).
        Must have at least `window + 1` rows for non-NaN output.
    window : int
        Rolling window in trading days (default 21 ≈ 1 month).

    Returns
    -------
    pd.Series
        Annualized volatility series, clipped to minimum 0.001.
        NaN for the first `window` rows (insufficient history).
    """
    _validate_ohlc(ohlc)

    log_oc = np.log(ohlc["Open"] / ohlc["Close"].shift(1))   # overnight return
    log_co = np.log(ohlc["Close"] / ohlc["Open"])             # intraday return
    log_ho = np.log(ohlc["High"] / ohlc["Open"])
    log_lo = np.log(ohlc["Low"] / ohlc["Open"])

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)  # Rogers-Satchell

    k = 0.34 / (1.34 + (window + 1) / (window - 1))

    variance = (
        (1 - k) * log_co.rolling(window).var()
        + k * rs.rolling(window).mean()
        + log_oc.rolling(window).var()
    )

    sigma = np.sqrt(_ANNUALIZE * variance)
    return sigma.clip(lower=0.001)


def parkinson_vol(ohlc: pd.DataFrame, window: int = 21) -> pd.Series:
    """Parkinson realized volatility estimator.

    Uses the high-low price range. Approximately 5x more efficient than
    close-to-close but does not capture overnight gaps.

    Formula:
        log_hl = log(High_t / Low_t)
        pk_var = log_hl**2 / (4 * log(2))
        sigma  = sqrt(252 * pk_var.rolling(window).mean())

    Parameters
    ----------
    ohlc : pd.DataFrame
        DataFrame with columns Open, High, Low, Close.
    window : int
        Rolling window in trading days (default 21).

    Returns
    -------
    pd.Series
        Annualized volatility series, clipped to minimum 0.001.
    """
    _validate_ohlc(ohlc)

    log_hl = np.log(ohlc["High"] / ohlc["Low"])
    pk_var = log_hl ** 2 / (4 * np.log(2))

    sigma = np.sqrt(_ANNUALIZE * pk_var.rolling(window).mean())
    return sigma.clip(lower=0.001)


def garman_klass_vol(ohlc: pd.DataFrame, window: int = 21) -> pd.Series:
    """Garman-Klass realized volatility estimator.

    Extends Parkinson with open/close information. Approximately 8x more
    efficient than close-to-close. Still biased when overnight gaps dominate.

    Formula:
        log_hl = log(High_t / Low_t)
        log_co = log(Close_t / Open_t)
        gk_var = 0.5 * log_hl**2 - (2*log(2)-1) * log_co**2
        sigma  = sqrt(252 * gk_var.rolling(window).mean())

    Parameters
    ----------
    ohlc : pd.DataFrame
        DataFrame with columns Open, High, Low, Close.
    window : int
        Rolling window in trading days (default 21).

    Returns
    -------
    pd.Series
        Annualized volatility series, clipped to minimum 0.001.
    """
    _validate_ohlc(ohlc)

    log_hl = np.log(ohlc["High"] / ohlc["Low"])
    log_co = np.log(ohlc["Close"] / ohlc["Open"])
    gk_var = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2

    sigma = np.sqrt(_ANNUALIZE * gk_var.rolling(window).mean())
    return sigma.clip(lower=0.001)


def realized_vol_suite(ohlc: pd.DataFrame) -> dict:
    """Compute all three RV estimators over all four standard windows.

    Returns a flat dict with 12 scalar float values (estimator × window
    combinations) plus the full Yang-Zhang 21-day series for use by
    downstream HAR-RV forecasters (plan 02-02).

    Keys returned:
        yz_10d, yz_21d, yz_30d, yz_60d  (Yang-Zhang annualized vol)
        pk_10d, pk_21d, pk_30d, pk_60d  (Parkinson annualized vol)
        gk_10d, gk_21d, gk_30d, gk_60d  (Garman-Klass annualized vol)
        yz_series_21d                    (full pd.Series for HAR-RV input)

    Parameters
    ----------
    ohlc : pd.DataFrame
        DataFrame with columns Open, High, Low, Close. Minimum 60 rows
        recommended for all windows to produce non-NaN output.

    Returns
    -------
    dict
        13 keys as described above. Scalars are Python floats.
    """
    _validate_ohlc(ohlc)

    windows = [10, 21, 30, 60]
    estimators = {
        "yz": yang_zhang_vol,
        "pk": parkinson_vol,
        "gk": garman_klass_vol,
    }

    result: dict = {}
    for est_name, fn in estimators.items():
        for w in windows:
            series = fn(ohlc, window=w)
            result[f"{est_name}_{w}d"] = float(series.iloc[-1])

    # Full 21-day YZ series for downstream HAR-RV (avoids recomputation)
    result["yz_series_21d"] = yang_zhang_vol(ohlc, window=21)

    return result


def iv_to_trading_day(iv_calendar: float) -> float:
    """Convert a calendar-day annualized IV to a trading-day annualized vol.

    Options market convention quotes IV on a 365-day calendar basis.
    Realized volatility is computed on 252 trading days. This function
    rescales so the two are on the same basis (PRD §2.2).

    Formula:
        iv_trading = iv_calendar * sqrt(365 / 252)

    Parameters
    ----------
    iv_calendar : float
        Implied volatility expressed on a 365-day annualized calendar basis
        (e.g., 0.20 for 20%).

    Returns
    -------
    float
        IV rescaled to 252 trading-day annualized basis.
    """
    return iv_calendar * np.sqrt(365 / 252)


def estimator_divergence(yz: float, pk: float, gk: float) -> dict:
    """Detect large divergence between RV estimators, signalling overnight gaps.

    When Yang-Zhang diverges significantly from Parkinson or Garman-Klass,
    it indicates that overnight returns (gaps) are dominating realized vol.
    This is relevant for options structuring: ATM options may be mispriced if
    the gap component is transient (e.g., single earnings event).

    Parameters
    ----------
    yz : float
        Yang-Zhang annualized vol (includes overnight component).
    pk : float
        Parkinson annualized vol (intraday range only).
    gk : float
        Garman-Klass annualized vol (intraday, open/close adjusted).

    Returns
    -------
    dict with keys:
        yz_pk_gap : float         — YZ minus PK in vol points
        yz_gk_gap : float         — YZ minus GK in vol points
        overnight_dominated : bool — True if either gap exceeds 0.03 (3 vol pts)
        flag : str                 — Human-readable message or empty string
    """
    yz_pk_gap = yz - pk
    yz_gk_gap = yz - gk
    overnight_dominated = abs(yz_pk_gap) > 0.03 or abs(yz_gk_gap) > 0.03

    flag = (
        "Large overnight gaps dominating RV — consider reviewing ATM option suitability"
        if overnight_dominated
        else ""
    )

    return {
        "yz_pk_gap": yz_pk_gap,
        "yz_gk_gap": yz_gk_gap,
        "overnight_dominated": overnight_dominated,
        "flag": flag,
    }
