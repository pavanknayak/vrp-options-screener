"""
analytics/iv_surface_svi.py — SVI (Stochastic Volatility Inspired) parametric
IV smile fitting.

SVI is arbitrage-free by construction for a single expiration slice when the
parameter constraints are satisfied. It uses a simple closed-form shape for
total variance as a function of log-moneyness:

    w(k) = a + b * (ρ * (k - m) + sqrt((k - m)^2 + σ^2))

where:
    k = log(K / F)   — log-moneyness (K = strike, F = forward)
    a               — overall level of variance (vertical shift)
    b               — slope / wing width
    ρ               — correlation / skew asymmetry in [-1, 1]
    m               — center (ATM translation)
    σ               — smoothness of the ATM region (always > 0)

Butterfly-arbitrage freedom is checked numerically on the fitted smile by
verifying that the discrete second derivative d²w/dk² >= 0 everywhere.

Public exports: svi_total_variance, fit_svi_slice, interpolate_svi
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def svi_total_variance(
    k: float | np.ndarray,
    a: float,
    b: float,
    rho: float,
    m: float,
    sigma: float,
) -> float | np.ndarray:
    """Compute SVI total variance w(k) = a + b*(ρ*(k-m) + sqrt((k-m)^2 + σ^2)).

    Parameters
    ----------
    k : float or np.ndarray
        Log-moneyness log(K/F).
    a, b, rho, m, sigma : float
        SVI parameters.

    Returns
    -------
    float or np.ndarray
        Total variance w(k) = IV(k)^2 * T.
    """
    diff = k - m
    return a + b * (rho * diff + np.sqrt(diff ** 2 + sigma ** 2))


def fit_svi_slice(
    log_moneyness: np.ndarray,
    market_ivs: np.ndarray,
    dte_years: float,
) -> dict | None:
    """Fit SVI to a single expiration slice.

    Fits SVI parameters (a, b, ρ, m, σ) to the observed IV smile using
    L-BFGS-B with parameter constraints enforced via penalty returns.
    Checks butterfly-arbitrage freedom on the fitted smile.

    Parameters
    ----------
    log_moneyness : np.ndarray
        Log-moneyness log(K/F) for each option. Minimum 4 points required.
    market_ivs : np.ndarray
        Market implied vols (annualized) corresponding to each log_moneyness.
    dte_years : float
        Time to expiry in years (e.g. 30/365 ≈ 0.082). Used to convert IVs
        to total variance for fitting and back to IVs for output.

    Returns
    -------
    dict or None
        On success:
            params       : dict — {'a', 'b', 'rho', 'm', 'sigma'}
            fitted_ivs   : list[float] — SVI-implied IVs at each log_moneyness
            rmse         : float — root-mean-squared error vs market_ivs
            arbitrage_free : bool — True if butterfly-arbitrage-free
            dte_years    : float — echoed back for downstream use
        Returns None when fewer than 4 points or if the optimizer fails.
    """
    if len(log_moneyness) < 4:
        return None

    dte_years = max(dte_years, 1e-6)  # guard against zero
    market_tv = market_ivs ** 2 * dte_years  # total variance

    def objective(params: np.ndarray) -> float:
        a, b, rho, m, sigma = params
        # Constraint penalties
        if b < 0 or abs(rho) >= 1 or sigma <= 0:
            return 1e10
        # SVI necessary condition: a + b * sigma * sqrt(1 - rho^2) >= 0
        if a + b * sigma * np.sqrt(1.0 - rho ** 2) < -1e-6:
            return 1e10
        w = svi_total_variance(log_moneyness, a, b, rho, m, sigma)
        if np.any(w < 0):
            return 1e10
        return float(np.sum((w - market_tv) ** 2))

    atm_tv = float(np.median(market_tv))
    x0 = [atm_tv * 0.8, 0.1, -0.3, 0.0, 0.1]
    bounds = [
        (0.0, None),      # a >= 0
        (0.0, None),      # b >= 0
        (-0.999, 0.999),  # |rho| < 1
        (None, None),     # m unconstrained
        (1e-4, None),     # sigma > 0
    ]

    try:
        result = minimize(
            objective,
            x0,
            method='L-BFGS-B',
            bounds=bounds,
            options={'maxiter': 1000, 'ftol': 1e-12, 'gtol': 1e-8},
        )

        # Accept solution even when optimizer reports not-success if residual is small
        if not result.success and result.fun > 1e-4:
            return None

        a, b, rho, m, sigma = result.x
        fitted_tv  = svi_total_variance(log_moneyness, a, b, rho, m, sigma)
        fitted_ivs = np.sqrt(np.maximum(fitted_tv / dte_years, 1e-8))
        rmse = float(np.sqrt(np.mean((fitted_ivs - market_ivs) ** 2)))

        # Butterfly-arbitrage check: d²w/dk² >= 0 everywhere on the smile
        k_test = np.linspace(float(log_moneyness.min()), float(log_moneyness.max()), 50)
        w_test  = svi_total_variance(k_test, a, b, rho, m, sigma)
        arb_free = bool(np.all(np.diff(np.diff(w_test)) >= -1e-8))

        return {
            'params': {
                'a': float(a),
                'b': float(b),
                'rho': float(rho),
                'm': float(m),
                'sigma': float(sigma),
            },
            'fitted_ivs':    fitted_ivs.tolist(),
            'rmse':          rmse,
            'arbitrage_free': arb_free,
            'dte_years':     float(dte_years),
        }

    except Exception:
        return None


def interpolate_svi(
    log_moneyness_target: float,
    svi_result: dict,
    dte_years: float,
) -> float | None:
    """Interpolate IV at a target log-moneyness using a fitted SVI result.

    Parameters
    ----------
    log_moneyness_target : float
        log(K_target / F) at which to evaluate the SVI smile.
    svi_result : dict
        Output of fit_svi_slice() — must contain a 'params' sub-dict.
    dte_years : float
        Time to expiry in years (used to convert total variance back to IV).

    Returns
    -------
    float or None
        Annualized implied volatility at the target log-moneyness, or None
        if the computation fails.
    """
    try:
        p = svi_result['params']
        tv = svi_total_variance(
            log_moneyness_target,
            p['a'], p['b'], p['rho'], p['m'], p['sigma'],
        )
        dte_years = max(dte_years, 1e-6)
        return float(np.sqrt(max(tv / dte_years, 1e-8)))
    except Exception:
        return None
