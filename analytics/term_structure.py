"""
analytics/term_structure.py — Nelson-Siegel term structure fitting for IV
across expirations.

The Nelson-Siegel model decomposes the IV term structure into three
interpretable factors:
    Level (L)     : long-run IV floor (all maturities converge here)
    Slope (S)     : short-end premium / discount vs the long end
    Curvature (C) : hump shape (medium-term effects)

Public exports: fit_nelson_siegel
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def fit_nelson_siegel(dtes: list[float], ivs: list[float]) -> dict | None:
    """Fit Nelson-Siegel model to IV across expirations.

    Model:
        IV(τ) = L + S * (1 - e^{-λτ}) / (λτ) + C * [(1 - e^{-λτ}) / (λτ) - e^{-λτ}]

    where τ = DTE / 252 (time in years).

    Parameters
    ----------
    dtes : list[float]
        Days-to-expiration values (calendar days). Minimum 3 required.
    ivs : list[float]
        Corresponding annualized ATM implied volatilities.
        Must be the same length as *dtes*.

    Returns
    -------
    dict or None
        On success:
            level        : float — long-run IV level (L)
            slope        : float — slope factor (S; negative = normal contango)
            curvature    : float — curvature factor (C)
            lambda       : float — speed of mean reversion (λ, always >= 0.01)
            fitted_ivs   : list[float] — model-implied IVs at the input DTEs
            residuals    : list[float] — (market IV) - (fitted IV) per expiration
            rmse         : float — root-mean-squared fitting error
            ts_slope_z   : float — placeholder 0.0 (requires historical fit history)
            ts_quality   : str — 'good' (rmse < 0.02) or 'poor'
        Returns None when fewer than 3 expirations are provided or if the
        optimizer fails to converge.
    """
    if len(dtes) < 3 or len(ivs) < 3:
        return None

    dtes_arr = np.array(dtes, dtype=float)
    ivs_arr  = np.array(ivs,  dtype=float)

    def ns_model(tau: np.ndarray, L: float, S: float, C: float, lam: float) -> np.ndarray:
        lam = max(lam, 0.01)
        factor = (1.0 - np.exp(-lam * tau)) / (lam * tau)
        return L + S * factor + C * (factor - np.exp(-lam * tau))

    def objective(params: np.ndarray) -> float:
        L, S, C, lam = params
        if lam <= 0 or L <= 0:
            return 1e10
        fitted = ns_model(dtes_arr / 252.0, L, S, C, lam)
        return float(np.sum((fitted - ivs_arr) ** 2))

    try:
        result = minimize(
            objective,
            x0=[float(np.mean(ivs_arr)), -0.02, 0.01, 1.0],
            method='Nelder-Mead',
            options={'maxiter': 500, 'xatol': 1e-6, 'fatol': 1e-8},
        )

        L, S, C, lam = result.x
        lam = max(lam, 0.01)
        fitted = ns_model(dtes_arr / 252.0, L, S, C, lam)
        residuals = ivs_arr - fitted
        rmse = float(np.sqrt(np.mean(residuals ** 2)))

        return {
            'level':      float(L),
            'slope':      float(S),
            'curvature':  float(C),
            'lambda':     float(lam),
            'fitted_ivs': fitted.tolist(),
            'residuals':  residuals.tolist(),
            'rmse':       rmse,
            'ts_slope_z': 0.0,  # requires history — set externally
            'ts_quality': 'good' if rmse < 0.02 else 'poor',
        }

    except Exception:
        return None
