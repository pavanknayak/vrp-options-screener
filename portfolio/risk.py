"""
portfolio/risk.py — Portfolio-level risk metrics and constraints.

Provides:
- CVaR (Conditional Value at Risk) constraint for position sizing
- Sector concentration monitoring
- Drawdown circuit breaker
- Portfolio greeks (theta, delta, vega) estimation
"""
from __future__ import annotations
import logging
from datetime import date
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A3 — CVaR Constraint
# ---------------------------------------------------------------------------

def compute_portfolio_cvar(
    positions: list[dict],
    portfolio_value: float,
    confidence: float = 0.95,
    horizon_days: int = 30,
    n_simulations: int = 10_000,
) -> dict:
    """Estimate portfolio CVaR via Monte Carlo simulation.

    Args:
        positions: List of position dicts with keys: ticker, structure,
                   short_strike, entry_credit, contracts, entry_price, sector
        portfolio_value: Total portfolio value
        confidence: CVaR confidence level (default 0.95)
        horizon_days: Simulation horizon in trading days
        n_simulations: Number of Monte Carlo paths

    Returns:
        dict with: cvar_dollars, cvar_pct, var_dollars, var_pct,
                   short_vol_pct, worst_case_loss
    """
    if not positions:
        return {"cvar_dollars": 0, "cvar_pct": 0, "var_dollars": 0, "var_pct": 0,
                "short_vol_pct": 0, "worst_case_loss": 0}

    rng = np.random.default_rng(42)

    # Build position P&L matrix
    pnl_matrix = np.zeros((n_simulations, len(positions)))

    for i, pos in enumerate(positions):
        entry_price = float(pos.get("entry_price", 100))
        short_strike = float(pos.get("short_strike", entry_price * 0.95))
        entry_credit = float(pos.get("entry_credit", 1.0))
        contracts = int(pos.get("contracts", 1))
        structure = pos.get("structure", "csp")

        # Simulate underlying price paths (log-normal, 25% vol assumption)
        sigma = 0.25
        dt = horizon_days / 252
        rand = rng.standard_normal(n_simulations)
        terminal_prices = entry_price * np.exp(-0.5 * sigma**2 * dt + sigma * np.sqrt(dt) * rand)

        # Compute P&L per simulation
        if structure == "csp":
            pnl = np.where(
                terminal_prices >= short_strike,
                entry_credit * 100 * contracts,
                (terminal_prices - short_strike + entry_credit) * 100 * contracts
            )
        else:
            long_strike = float(pos.get("long_strike", short_strike - 5))
            max_loss = (short_strike - long_strike - entry_credit) * 100 * contracts
            max_profit = entry_credit * 100 * contracts
            raw = (terminal_prices - short_strike + entry_credit) * 100 * contracts
            pnl = np.clip(raw, -max_loss, max_profit)

        pnl_matrix[:, i] = pnl

    # Portfolio P&L
    portfolio_pnl = pnl_matrix.sum(axis=1)
    losses = -portfolio_pnl  # convert to losses (positive = bad)

    # VaR and CVaR
    var_dollars = float(np.percentile(losses, confidence * 100))
    tail_losses = losses[losses >= var_dollars]
    cvar_dollars = float(tail_losses.mean()) if len(tail_losses) > 0 else var_dollars

    # Short vol exposure (sum of max potential losses)
    short_vol_exposure = sum(
        float(pos.get("short_strike", 100)) * int(pos.get("contracts", 1)) * 100
        for pos in positions
        if pos.get("structure") in ("csp", "spread", "collar", "iron_condor")
    )
    short_vol_pct = short_vol_exposure / max(portfolio_value, 1)
    worst_case = float(np.max(losses))

    return {
        "cvar_dollars": cvar_dollars,
        "cvar_pct": cvar_dollars / portfolio_value,
        "var_dollars": var_dollars,
        "var_pct": var_dollars / portfolio_value,
        "short_vol_pct": short_vol_pct,
        "worst_case_loss": worst_case,
    }


def check_cvar_constraint(
    new_position: dict,
    existing_positions: list[dict],
    portfolio_value: float,
    max_cvar_pct: float = 0.15,
) -> dict:
    """Check if adding new_position keeps portfolio CVaR within limits.

    Returns dict with: allowed (bool), current_cvar_pct, projected_cvar_pct,
                       message (str)
    """
    current = compute_portfolio_cvar(existing_positions, portfolio_value)
    projected = compute_portfolio_cvar(existing_positions + [new_position], portfolio_value)

    allowed = projected["cvar_pct"] <= max_cvar_pct
    return {
        "allowed": allowed,
        "current_cvar_pct": current["cvar_pct"],
        "projected_cvar_pct": projected["cvar_pct"],
        "message": (
            f"OK — CVaR increases from {current['cvar_pct']:.1%} to {projected['cvar_pct']:.1%}"
            if allowed else
            f"BLOCKED — would push CVaR to {projected['cvar_pct']:.1%} (limit: {max_cvar_pct:.1%})"
        ),
    }


# ---------------------------------------------------------------------------
# B4 — Sector Concentration
# ---------------------------------------------------------------------------

def compute_sector_exposure(positions: list[dict], portfolio_value: float) -> dict:
    """Compute sector exposure as % of total portfolio theta (estimated).

    Returns dict: sector_name -> {count, capital_at_risk, pct_of_total}
    """
    sector_exposure: dict[str, dict] = {}

    for pos in positions:
        sector = pos.get("sector", "Unknown")
        capital = float(pos.get("short_strike", 100)) * int(pos.get("contracts", 1)) * 100

        if sector not in sector_exposure:
            sector_exposure[sector] = {"count": 0, "capital_at_risk": 0.0}
        sector_exposure[sector]["count"] += 1
        sector_exposure[sector]["capital_at_risk"] += capital

    total_at_risk = sum(v["capital_at_risk"] for v in sector_exposure.values())

    for sector in sector_exposure:
        pct = sector_exposure[sector]["capital_at_risk"] / max(total_at_risk, 1)
        sector_exposure[sector]["pct_of_total"] = pct
        sector_exposure[sector]["over_limit"] = pct > 0.25 and sector not in ("Diversified",)

    return sector_exposure


def get_sector_limit_warning(sector: str, current_positions: list[dict]) -> Optional[str]:
    """Return warning message if adding a position in `sector` would breach 25% limit."""
    exposure = compute_sector_exposure(current_positions, 1.0)
    current_pct = exposure.get(sector, {}).get("pct_of_total", 0.0)

    if sector in ("Diversified", "Unknown"):
        return None
    if current_pct >= 0.25:
        return f"WARNING: {sector} already at {current_pct:.0%} of portfolio (limit: 25%). Consider diversifying."
    if current_pct >= 0.20:
        return f"NOTE: {sector} at {current_pct:.0%} of portfolio — approaching 25% limit."
    return None


# ---------------------------------------------------------------------------
# B5 — Drawdown Circuit Breaker
# ---------------------------------------------------------------------------

def get_portfolio_drawdown(portfolio_value: float) -> dict:
    """Read current portfolio drawdown from NAV history.

    Returns dict with: current_nav, peak_nav, drawdown_pct,
                       soft_limit_hit (bool), hard_limit_hit (bool)
    """
    try:
        from cache.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT nav, peak_nav, drawdown_pct FROM portfolio_nav_history ORDER BY date DESC LIMIT 1"
        )
        if rows:
            nav, peak_nav, drawdown_pct = rows[0]
        else:
            nav = portfolio_value
            peak_nav = portfolio_value
            drawdown_pct = 0.0

        return {
            "current_nav": nav,
            "peak_nav": peak_nav,
            "drawdown_pct": drawdown_pct,
            "soft_limit_hit": drawdown_pct >= 0.08,
            "hard_limit_hit": drawdown_pct >= 0.15,
        }
    except Exception as e:
        logger.warning("get_portfolio_drawdown error: %s", e)
        return {"current_nav": portfolio_value, "peak_nav": portfolio_value,
                "drawdown_pct": 0.0, "soft_limit_hit": False, "hard_limit_hit": False}


def update_portfolio_nav(current_nav: float) -> None:
    """Update portfolio NAV history and compute drawdown."""
    try:
        from cache.db import get_db
        import time
        db = get_db()
        today = date.today().isoformat()

        rows = db.execute(
            "SELECT peak_nav FROM portfolio_nav_history ORDER BY date DESC LIMIT 1"
        )
        peak_nav = rows[0][0] if rows else current_nav
        peak_nav = max(peak_nav, current_nav)
        drawdown_pct = (peak_nav - current_nav) / peak_nav if peak_nav > 0 else 0.0

        db.execute_write(
            """INSERT OR REPLACE INTO portfolio_nav_history
               (date, nav, peak_nav, drawdown_pct, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (today, current_nav, peak_nav, drawdown_pct, time.time())
        )
    except Exception as e:
        logger.warning("update_portfolio_nav error: %s", e)


# ---------------------------------------------------------------------------
# C6 — Portfolio Greeks (BSM approximations)
# ---------------------------------------------------------------------------

def estimate_position_greeks(
    ticker: str,
    structure: str,
    short_strike: float,
    expiration_date: str,
    entry_credit: float,
    contracts: int,
    current_price: float,
    current_iv: float = 0.25,
    risk_free_rate: float = 0.05,
) -> dict:
    """Estimate Greeks for a single position using BSM approximation.

    Returns dict: delta, vega, theta, gamma (per contract, then scaled by contracts)
    """
    try:
        from datetime import datetime
        from scipy.stats import norm

        today = date.today()
        exp = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        dte = max((exp - today).days, 1)
        T = dte / 252
        S = current_price
        K = short_strike
        sigma = current_iv
        r = risk_free_rate

        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        # Put Greeks (short put position — negate for short)
        delta_per_share = -norm.cdf(-d1)  # put delta is negative; short put = positive delta
        gamma_per_share = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        vega_per_share = S * norm.pdf(d1) * np.sqrt(T) / 100  # per 1% change in vol
        theta_per_share = (
            -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
            + r * K * np.exp(-r*T) * norm.cdf(-d2)
        ) / 365  # daily theta

        # Scale by contracts and 100 shares; negate for short position
        scale = contracts * 100
        return {
            "delta": float(-delta_per_share * scale),  # short put = positive delta
            "gamma": float(-gamma_per_share * scale),  # short = negative gamma
            "vega": float(-vega_per_share * scale),    # short = negative vega
            "theta": float(-theta_per_share * scale),  # short = positive theta (collect decay)
        }
    except Exception as e:
        logger.warning("estimate_position_greeks error: %s", e)
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}


def compute_portfolio_greeks(positions: list[dict], portfolio_value: float) -> dict:
    """Compute aggregate portfolio Greeks from all positions.

    Returns dict: total_delta, total_vega, total_theta, total_gamma,
                  theta_efficiency (annualized % yield from theta),
                  vega_by_expiration (dict of week -> total_vega)
    """
    total_delta = total_vega = total_theta = total_gamma = 0.0
    vega_by_exp: dict[str, float] = {}

    for pos in positions:
        greeks = estimate_position_greeks(
            ticker=pos.get("ticker", ""),
            structure=pos.get("structure", "csp"),
            short_strike=float(pos.get("short_strike", 100)),
            expiration_date=pos.get("expiration_date", date.today().isoformat()),
            entry_credit=float(pos.get("entry_credit", 1.0)),
            contracts=int(pos.get("contracts", 1)),
            current_price=float(pos.get("entry_price", pos.get("short_strike", 100))),
        )
        total_delta += greeks["delta"]
        total_vega += greeks["vega"]
        total_theta += greeks["theta"]
        total_gamma += greeks["gamma"]

        exp = pos.get("expiration_date", "Unknown")
        vega_by_exp[exp] = vega_by_exp.get(exp, 0.0) + greeks["vega"]

    # Theta efficiency: annualized daily theta as % of portfolio value
    theta_efficiency = (total_theta * 252) / max(portfolio_value, 1) if portfolio_value > 0 else 0.0

    return {
        "total_delta": total_delta,
        "total_vega": total_vega,
        "total_theta": total_theta,
        "total_gamma": total_gamma,
        "theta_efficiency": theta_efficiency,
        "vega_by_expiration": vega_by_exp,
    }
