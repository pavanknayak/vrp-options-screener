"""Microstructure signals: Dealer Gamma Exposure (GEX) and Put-Call Ratio (PCR).

PRD references: GEX §6.6, PCR §6.7.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_gex(chain: dict, spot: float) -> dict:
    """Compute Dealer Gamma Exposure (GEX) from an options chain.

    Sign convention (PRD §6.6): dealers are assumed short calls and short puts
    (sold to retail).  Being short a call is short gamma → negative contribution.
    Being short a put is also short gamma, but delta-hedging behaviour means the
    net GEX contribution is positive (dealers buy shares as spot falls).

    GEX = Σ_expirations [
        - Σ_calls  (OI × gamma × 100 × spot²)   # dealer short call  → -gamma
        + Σ_puts   (OI × gamma × 100 × spot²)   # dealer short put   → +gamma
    ]

    Parameters
    ----------
    chain : dict
        Options chain as returned by data/schwab_client.fetch_options_chain().
        Must have ``chain['expirations']`` — a list of dicts each with 'calls'
        and 'puts' DataFrames containing at least 'openInterest' and 'gamma'.
    spot : float
        Current underlying price (used in GEX dollar-value scaling).

    Returns
    -------
    dict
        gex_raw, gex_billions, sign, magnitude, interpretation, supports_collection
    """
    gex = 0.0
    for exp in chain.get('expirations', []):
        calls = exp.get('calls', pd.DataFrame())
        puts = exp.get('puts', pd.DataFrame())

        # Dealers SHORT calls: their GEX contribution is NEGATIVE (short gamma)
        for _, row in calls.iterrows():
            oi    = row.get('openInterest', 0) or 0
            gamma = row.get('gamma', 0) or 0
            gex  += oi * gamma * 100 * spot ** 2 * (-1)   # dealer short call = -gamma

        # Dealers SHORT puts: their GEX contribution is POSITIVE (long gamma via delta hedge)
        for _, row in puts.iterrows():
            oi    = row.get('openInterest', 0) or 0
            gamma = row.get('gamma', 0) or 0
            gex  += oi * gamma * 100 * spot ** 2 * (+1)   # dealer short put = +gamma

    gex_bn = gex / 1e9

    # Interpret magnitude against PRD §6.6 thresholds
    if gex_bn > 0.5:
        interp = "Strongly supportive — dealer hedging suppresses vol"
    elif gex_bn > 0:
        interp = "Mildly supportive"
    elif gex_bn > -0.5:
        interp = "Mildly adverse — neutral on position size"
    else:
        interp = "Adverse — reduce position size 25%"

    return {
        'gex_raw':            gex,
        'gex_billions':       gex_bn,
        'sign':               'positive' if gex > 0 else 'negative',
        'magnitude':          abs(gex_bn),
        'interpretation':     interp,
        'supports_collection': gex > 0,
    }


def compute_pcr(chain: dict) -> dict:
    """Compute Put-Call Ratio (PCR) aggregated across all expirations (PRD §6.7).

    Parameters
    ----------
    chain : dict
        Options chain with ``chain['expirations']`` list of dicts each containing
        'calls' and 'puts' DataFrames with 'openInterest' and optionally 'volume'.

    Returns
    -------
    dict
        pcr_oi, pcr_volume, put_oi, call_oi, interpretation
    """
    total_put_oi   = 0
    total_call_oi  = 0
    total_put_vol  = 0
    total_call_vol = 0

    for exp in chain.get('expirations', []):
        calls = exp.get('calls', pd.DataFrame())
        puts  = exp.get('puts',  pd.DataFrame())

        if not puts.empty and 'openInterest' in puts.columns:
            total_put_oi  += puts['openInterest'].sum()
        if not calls.empty and 'openInterest' in calls.columns:
            total_call_oi += calls['openInterest'].sum()

        if not puts.empty and 'volume' in puts.columns:
            total_put_vol  += puts['volume'].sum()
        if not calls.empty and 'volume' in calls.columns:
            total_call_vol += calls['volume'].sum()

    pcr_oi  = total_put_oi  / max(total_call_oi,  1)
    pcr_vol = total_put_vol / max(total_call_vol, 1)

    # PRD §6.7 interpretation thresholds
    if pcr_oi > 1.8:
        interp = "Heavy institutional put buying — strong hedging demand premium"
    elif pcr_oi > 1.2:
        interp = "Elevated but normal — moderate hedging demand"
    elif pcr_oi >= 0.8:
        interp = "Balanced — structural premium present, less hedging-demand driven"
    else:
        interp = "Call-heavy — unusual; investigate for event rumors or M&A"

    return {
        'pcr_oi':         float(pcr_oi),
        'pcr_volume':     float(pcr_vol),
        'put_oi':         int(total_put_oi),
        'call_oi':        int(total_call_oi),
        'interpretation': interp,
    }
