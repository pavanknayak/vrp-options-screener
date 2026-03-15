"""
recommendations/roll_analyzer.py — Roll analysis for existing short-vol positions.

Given an existing position and current market data, computes:
- Current estimated P&L
- Roll-forward analysis for next 3 monthly expirations
- Net roll credit for each scenario
- Roll recommendation (roll now vs wait)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RollOption:
    """One possible roll target."""
    expiration: str          # "YYYY-MM-DD"
    dte: int
    new_strike: float
    new_credit: float        # estimated credit for new position
    close_cost: float        # estimated cost to close current position
    net_roll_credit: float   # current_pnl + new_credit - close_cost (net dollars)
    recommendation: str      # "ROLL NOW" | "WAIT" | "TAKE PROFIT"


@dataclass
class RollAnalysis:
    current_pnl_pct: float   # current P&L as % of max profit
    current_dte: int
    roll_options: list[RollOption]
    primary_recommendation: str
    reasoning: str


def analyze_roll(
    ticker: str,
    structure: str,
    short_strike: float,
    expiration_date: str,       # "YYYY-MM-DD"
    entry_credit: float,        # original credit per share
    contracts: int,
    current_price: float,       # current underlying price
    current_iv: float = 0.25,   # current ATM IV
) -> RollAnalysis:
    """Analyze whether to roll a position forward.

    Uses BSM approximation to estimate current option value without needing
    a live options chain.
    """
    try:
        from datetime import datetime
        today = date.today()
        exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        current_dte = max((exp_date - today).days, 0)

        # Estimate current option value via BSM approximation
        current_option_value = _bsm_put_approx(
            current_price, short_strike, current_dte / 252, current_iv, 0.05
        )
        current_pnl = (entry_credit - current_option_value) * 100 * contracts
        max_profit = entry_credit * 100 * contracts
        current_pnl_pct = current_pnl / max_profit if max_profit > 0 else 0

        # Build roll options for next 3 monthly expirations
        roll_options = []
        for months_ahead in [1, 2, 3]:
            new_exp = _next_monthly_expiry(today, months_ahead)
            new_dte = (new_exp - today).days
            # Estimate credit at same delta at new expiration
            new_credit = _estimate_credit_at_delta(
                current_price, short_strike, new_dte / 252, current_iv, 0.20
            )
            close_cost = current_option_value * 100 * contracts
            net_credit = (new_credit - current_option_value) * 100 * contracts

            if current_dte <= 21:
                rec = "ROLL NOW"
            elif current_pnl_pct >= 0.50:
                rec = "TAKE PROFIT"
            elif net_credit > 0:
                rec = "ROLL NOW"
            else:
                rec = "WAIT"

            roll_options.append(RollOption(
                expiration=new_exp.strftime("%Y-%m-%d"),
                dte=new_dte,
                new_strike=_suggest_roll_strike(current_price, short_strike, current_pnl_pct),
                new_credit=new_credit,
                close_cost=current_option_value,
                net_roll_credit=net_credit,
                recommendation=rec,
            ))

        # Primary recommendation
        if current_pnl_pct >= 0.50:
            primary = "TAKE PROFIT — 50% of max profit reached"
            reason = f"Position has earned {current_pnl_pct:.0%} of maximum profit. Close now to eliminate remaining risk."
        elif current_dte <= 21:
            primary = "ROLL FORWARD — Approaching gamma risk zone"
            reason = f"Only {current_dte} DTE remaining. Roll to next expiration to avoid assignment risk and capture new theta."
        elif roll_options and roll_options[0].net_roll_credit > 0:
            primary = "CONSIDER ROLLING — Net credit available"
            reason = f"Rolling to {roll_options[0].expiration} generates net credit of ${roll_options[0].net_roll_credit:.0f}."
        else:
            primary = "HOLD — Let theta decay work"
            reason = f"Position at {current_pnl_pct:.0%} of max profit with {current_dte} DTE. Continue holding."

        return RollAnalysis(
            current_pnl_pct=current_pnl_pct,
            current_dte=current_dte,
            roll_options=roll_options,
            primary_recommendation=primary,
            reasoning=reason,
        )
    except Exception as e:
        logger.error("analyze_roll error: %s", e)
        return RollAnalysis(
            current_pnl_pct=0.0, current_dte=0, roll_options=[],
            primary_recommendation="Unable to compute roll analysis",
            reasoning=str(e),
        )


def _bsm_put_approx(S, K, T, sigma, r):
    """Simple BSM put price approximation."""
    if T <= 0:
        return max(K - S, 0.0)
    try:
        from scipy.stats import norm
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    except Exception:
        return max(K - S, 0.0) * 0.5


def _estimate_credit_at_delta(S, reference_strike, T, sigma, target_delta=0.20):
    """Estimate credit for a put at approximately target_delta."""
    try:
        # Approximate: use reference_strike scaled by current price
        ratio = reference_strike / S  # e.g. 0.95 if 5% OTM
        new_strike = S * ratio  # keep same moneyness
        bid_approx = _bsm_put_approx(S, new_strike, T, sigma, 0.05)
        return bid_approx * 0.75  # slippage-adjusted
    except Exception:
        return 0.0


def _suggest_roll_strike(current_price, original_strike, pnl_pct):
    """Suggest roll strike: if profitable, roll down slightly; if losing, roll to ATM."""
    if pnl_pct >= 0.30:
        return round(current_price * (original_strike / max(current_price, 1)) * 0.98, 1)
    return round(current_price * 0.95, 1)  # 5% OTM


def _next_monthly_expiry(today: date, months_ahead: int) -> date:
    """Get the 3rd Friday of the month N months ahead."""
    import calendar
    target_month = today.month + months_ahead
    target_year = today.year + (target_month - 1) // 12
    target_month = ((target_month - 1) % 12) + 1

    # Find 3rd Friday
    cal = calendar.monthcalendar(target_year, target_month)
    fridays = [week[4] for week in cal if week[4] != 0]
    third_friday = fridays[2] if len(fridays) >= 3 else fridays[-1]
    return date(target_year, target_month, third_friday)
