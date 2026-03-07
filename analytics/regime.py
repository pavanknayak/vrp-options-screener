"""Volatility regime detection and Vol-of-Vol signal (PRD §6.12, §6.8)."""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def detect_regime(vix: float, vvix: float = None, vix3m: float = None,
                  vvix_history: pd.Series = None) -> dict:
    """Detect the current volatility regime from VIX level and optional auxiliary inputs.

    Parameters
    ----------
    vix : float
        Current VIX spot level.
    vvix : float, optional
        Current VVIX (vol-of-vol index) level.
    vix3m : float, optional
        VIX 3-month futures level for term structure slope.
    vvix_history : pd.Series, optional
        Historical VVIX series (at least 30 observations) for Z-score computation.

    Returns
    -------
    dict
        label, multiplier, message, vix, vvix, vvix_z, term_slope, is_crisis
    """
    # Compute VVIX Z-score if history available
    vvix_z = None
    if vvix is not None and vvix_history is not None and len(vvix_history) >= 30:
        hist_std = vvix_history.std()
        if hist_std > 0:
            vvix_z = (vvix - vvix_history.mean()) / hist_std
        else:
            # std=0: Z-score is undefined; treat as 0 to avoid crashes
            vvix_z = 0.0

    # Primary VIX level thresholds (PRD §6.12, exact values).
    # Crisis check comes FIRST — VIX > 40 always wins regardless of VVIX.
    if vix > 40:
        label, mult, msg = "Crisis", 0.00, "Close all. Do not open new short-vol."
    elif vvix_z is not None and vvix_z > 2.5:
        label, mult, msg = "VOL_UNSTABLE", 0.25, "VVIX spike: VRP unreliable. 25% size max."
    elif vix > 28:
        label, mult, msg = "High", 0.75, "Rich premium; tail risk elevated."
    elif vix > 20:
        label, mult, msg = "Elevated", 1.25, "Premium-rich: increase size modestly."
    elif vix > 15:
        label, mult, msg = "Normal", 1.00, "Standard environment."
    else:
        label, mult, msg = "Low", 0.50, "Thin premium; reduce size, be selective."

    # Term slope (VIX3M - VIX): contango = normal, backwardation = stress
    term_slope = (vix3m - vix) if vix3m is not None else None

    return {
        'label':      label,
        'multiplier': mult,
        'message':    msg,
        'vix':        vix,
        'vvix':       vvix,
        'vvix_z':     vvix_z,
        'term_slope': term_slope,
        'is_crisis':  label == "Crisis",
    }


def vov_signal(iv30_history: pd.Series) -> dict:
    """Compute Vol-of-Vol signal from a rolling IV30 series (PRD §6.8).

    Parameters
    ----------
    iv30_history : pd.Series
        Time series of 30-day implied volatility observations (decimal, e.g. 0.22).
        Needs at least 30 observations for a meaningful result.

    Returns
    -------
    dict
        vov_30d (annualized), vov_z (Z-score vs rolling 252-day history),
        flag (human-readable warning string), disqualify (bool).
    """
    if len(iv30_history) < 30:
        return {
            'vov_30d':    None,
            'vov_z':      None,
            'flag':       'insufficient_history',
            'disqualify': False,
        }

    vov_30d = float(iv30_history.iloc[-30:].std() * np.sqrt(252))  # annualized

    # Z-score vs. 252-day rolling VoV history
    rolling_vov = iv30_history.rolling(30).std() * np.sqrt(252)
    rolling_vov = rolling_vov.dropna()
    if len(rolling_vov) >= 21:
        vov_z = (vov_30d - float(rolling_vov.mean())) / max(float(rolling_vov.std()), 1e-8)
    else:
        vov_z = 0.0

    flag = ''
    if vov_z > 2.5:
        flag = 'NO-GO: VoV Z > 2.5 — IV extremely unstable'
    elif vov_z > 1.5:
        flag = 'Reduce position size 30% — VoV Z > 1.5'

    return {
        'vov_30d':    vov_30d,
        'vov_z':      float(vov_z),
        'flag':       flag,
        'disqualify': vov_z > 2.5,
    }
