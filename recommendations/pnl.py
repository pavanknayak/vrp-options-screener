"""
recommendations/pnl.py
-----------------------
Slippage-adjusted expected value, four-scenario P&L, and fractional Kelly
position sizing for the VRP Options Screener recommendation engine.

This module is the quantitative core of the recommendation card — every
dollar-denominated number the user acts on flows through these functions.

Public API:
    ScenarioPnL              — per-scenario P&L dataclass
    PnLResult                — full P&L result dataclass
    compute_slippage_ev()    — per-leg slippage-adjusted credit
    compute_pnl_scenarios()  — four-scenario P&L + trade management levels
    compute_kelly_size()     — fractional Kelly position sizing
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regime-conditional scenario probability table (A1)
# ---------------------------------------------------------------------------

REGIME_SCENARIO_PROBS: dict[str, dict[str, float]] = {
    "Low":          {"Bull": 0.25, "Base": 0.65, "Bear": 0.08, "Crash": 0.02},
    "Normal":       {"Bull": 0.22, "Base": 0.62, "Bear": 0.12, "Crash": 0.04},
    "Elevated":     {"Bull": 0.18, "Base": 0.58, "Bear": 0.16, "Crash": 0.08},
    "High":         {"Bull": 0.12, "Base": 0.50, "Bear": 0.25, "Crash": 0.13},
    "Crisis":       {"Bull": 0.05, "Base": 0.35, "Bear": 0.35, "Crash": 0.25},
    "VOL_UNSTABLE": {"Bull": 0.15, "Base": 0.50, "Bear": 0.22, "Crash": 0.13},
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScenarioPnL:
    """P&L for one macro scenario (Bull / Base / Bear / Crash)."""

    name: str               # "Bull" | "Base" | "Bear" | "Crash"
    underlying_move: float  # e.g. +0.15, 0.0, -0.10, -0.25
    terminal_price: float   # spot * (1 + underlying_move)
    pnl_per_contract: float # P&L in dollars for 1 contract (100 shares)
    probability: float      # scenario probability [0.0, 1.0]
    weighted_pnl: float     # pnl_per_contract * probability


@dataclass
class PnLResult:
    """Complete P&L analysis for one recommended trade."""

    net_credit: float              # credit received per share (dollars)
    max_loss: float                # maximum loss per contract (dollars, positive number)
    breakeven: float               # breakeven underlying price
    profit_target: float           # 50% of max profit = net_credit_contract * 0.50
    hard_stop: float               # 200% of net_credit loss (2× credit received per contract)
    roll_trigger: float            # underlying falls to breakeven * 0.97
    scenarios: list[ScenarioPnL]   # 4 scenarios in order: Bull, Base, Bear, Crash
    probability_weighted_ev: float # sum(s.weighted_pnl for s in scenarios)
    slippage_adj_ev: float         # EV after slippage adjustment (per contract, dollars)
    kelly_dollars: float           # position size in dollars
    kelly_contracts: int           # floor(kelly_dollars / (100 * spot))
    kelly_pct: float               # kelly_dollars / portfolio_value
    kelly_breakdown: dict          # {"base": 0.25, "regime_mult": x, "vov_mult": x, "gex_mult": x, "final_f": x}
    regime_label: str = "Normal"   # regime label used for scenario prob selection (A1)
    scenario_probs: dict = field(default_factory=dict)  # probabilities used for scenarios (A1)


# ---------------------------------------------------------------------------
# compute_slippage_ev
# ---------------------------------------------------------------------------

def compute_slippage_ev(bid: float, ask: float) -> float:
    """Return per-leg slippage-adjusted credit (per share).

    Uses 75% of the bid-ask midpoint to model realistic fill quality:
        mid = (bid + ask) / 2
        adjusted = mid * 0.75

    Args:
        bid: Option bid price (per share).
        ask: Option ask price (per share).

    Returns:
        Slippage-adjusted credit per share.
    """
    mid = (bid + ask) / 2.0
    return mid * 0.75  # 75% of mid captures realistic fill


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_row(df: pd.DataFrame, target_strike: float) -> Optional[pd.Series]:
    """Return the row in df whose 'strike' column is closest to target_strike."""
    if df is None or df.empty or "strike" not in df.columns:
        return None
    idx = (df["strike"] - target_strike).abs().idxmin()
    return df.loc[idx]


def _pnl_for_scenario(
    structure: str,
    short_strike: float,
    long_strike: Optional[float],
    terminal_price: float,
    net_credit: float,
    max_loss: float,
    net_credit_contract: float,
) -> float:
    """Compute per-contract P&L for one scenario.

    Args:
        structure:            "csp", "spread", or "collar".
        short_strike:         Short put strike (or short put of spread/collar).
        long_strike:          Long put strike (spread/collar only; None for CSP).
        terminal_price:       Underlying price at expiry.
        net_credit:           Net credit per share (dollars).
        max_loss:             Maximum loss per contract (positive dollars).
        net_credit_contract:  Net credit per contract = net_credit * 100.

    Returns:
        Dollar P&L for 1 contract at the given terminal_price.
    """
    if structure == "csp":
        if terminal_price >= short_strike:
            return net_credit_contract  # put expires worthless — full credit
        return (terminal_price - short_strike + net_credit) * 100

    else:
        # Spread and Collar use identical clamped payoff formula.
        # Collar P&L approximated as spread equivalent (near zero-cost collar assumption)
        raw = (terminal_price - short_strike + net_credit) * 100
        return max(-max_loss, min(net_credit_contract, raw))


# ---------------------------------------------------------------------------
# compute_pnl_scenarios
# ---------------------------------------------------------------------------

def compute_pnl_scenarios(
    structure_result,
    chain: dict,
    analytics_result: dict,
) -> tuple[list[ScenarioPnL], float, float, float, float, float, float, str, dict]:
    """Compute four-scenario P&L and trade management levels.

    Args:
        structure_result: StructureResult from recommendations.structures.
        chain:            Options chain dict with "underlying_price" and "expirations".
        analytics_result: Dict from analytics engine; must contain "asset_class".

    Returns:
        Tuple of:
            scenarios          — list of 4 ScenarioPnL objects (Bull, Base, Bear, Crash)
            net_credit         — per-share slippage-adjusted credit
            max_loss           — per-contract maximum loss (positive dollars)
            breakeven          — breakeven underlying price
            profit_target      — per-contract profit target (50% of max profit)
            hard_stop          — per-contract hard stop (2× credit received)
            roll_trigger       — underlying price triggering roll (breakeven × 0.97)
            regime_label       — regime label used for scenario prob selection (A1)
            scenario_probs     — probability dict used for the scenarios (A1)
    """
    try:
        return _compute_pnl_scenarios_inner(structure_result, chain, analytics_result)
    except Exception as exc:  # noqa: BLE001
        logger.error("compute_pnl_scenarios: unexpected error: %s", exc, exc_info=True)
        # Safe fallback — return zeroed scenario list
        fallback_probs = {"Bull": 0.25, "Base": 0.45, "Bear": 0.20, "Crash": 0.10}
        fallback_scenarios = [
            ScenarioPnL(
                name=n, underlying_move=0.0, terminal_price=100.0,
                pnl_per_contract=0.0, probability=p, weighted_pnl=0.0,
            )
            for n, p in fallback_probs.items()
        ]
        return fallback_scenarios, 0.0, 0.0, 100.0, 0.0, 0.0, 97.0, "Normal", fallback_probs


def _compute_pnl_scenarios_inner(
    structure_result,
    chain: dict,
    analytics_result: dict,
) -> tuple[list[ScenarioPnL], float, float, float, float, float, float, str, dict]:
    """Core P&L scenario computation — may raise; caller wraps in try/except."""

    # ------------------------------------------------------------------
    # Step 1 — Determine asset class and scenario parameters
    # ------------------------------------------------------------------
    asset_class: str = analytics_result.get("asset_class", "us_equity")
    is_crypto: bool = asset_class == "crypto_etf"

    if is_crypto:
        moves = {"Bull": +0.50, "Base": 0.0, "Bear": -0.30, "Crash": -0.50}
        # Crypto always uses fixed probs (regime table is calibrated for equities)
        probs = {"Bull": 0.25, "Base": 0.40, "Bear": 0.20, "Crash": 0.15}
        regime_label_used = "Normal"  # not regime-adjusted for crypto
    else:
        moves = {"Bull": +0.15, "Base": 0.0, "Bear": -0.10, "Crash": -0.25}
        # A1: Regime-conditional scenario probabilities
        regime_label_used: str = (
            analytics_result.get("regime", {}).get("label", "Normal") or "Normal"
        )
        probs = dict(
            REGIME_SCENARIO_PROBS.get(regime_label_used, REGIME_SCENARIO_PROBS["Normal"])
        )
        # A1: Beta adjustment to Crash probability
        ticker_beta: float = float(
            analytics_result.get("signals", {}).get("beta", 1.0) or 1.0
        )
        base_crash = probs["Crash"]
        adjusted_crash = min(base_crash * max(ticker_beta, 0.5), 0.40)  # cap at 40%
        probs["Crash"] = adjusted_crash
        # Re-normalize: reduce Bear proportionally so all probs sum to 1.0
        excess = adjusted_crash - base_crash
        probs["Bear"] = max(probs["Bear"] - excess * 0.5, 0.05)
        probs["Base"] = max(probs["Base"] - excess * 0.5, 0.10)
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}

    structure: str = structure_result.structure
    spot: float = float(chain.get("underlying_price", structure_result.spot))
    short_strike: float = float(structure_result.short_strike)
    long_strike: Optional[float] = (
        float(structure_result.long_strike) if structure_result.long_strike is not None else None
    )

    # ------------------------------------------------------------------
    # Step 2 — Extract contract prices from chain for selected expiration
    # ------------------------------------------------------------------
    expirations: list[dict] = chain.get("expirations", [])
    if expirations:
        exp = min(expirations, key=lambda e: abs(e.get("dte", 999) - structure_result.dte))
    else:
        exp = {}

    puts_df: pd.DataFrame = exp.get("puts", pd.DataFrame())
    calls_df: pd.DataFrame = exp.get("calls", pd.DataFrame())

    # ------------------------------------------------------------------
    # Step 3 — Compute net credit, max loss, breakeven per structure
    # ------------------------------------------------------------------
    net_credit: float
    net_credit_contract: float
    max_loss: float
    breakeven: float

    if structure == "csp":
        short_row = _find_row(puts_df, short_strike)
        if short_row is not None and "bid" in short_row and "ask" in short_row:
            bid = float(short_row["bid"])
            ask = float(short_row["ask"])
        else:
            # Fallback: use strike-proportional synthetic prices
            bid = short_strike * 0.012
            ask = short_strike * 0.016

        net_credit = compute_slippage_ev(bid, ask)
        net_credit_contract = net_credit * 100
        max_loss = (short_strike - net_credit) * 100  # max loss if put exercised to zero
        breakeven = short_strike - net_credit

    elif structure == "spread":
        short_row = _find_row(puts_df, short_strike)
        long_s = long_strike if long_strike is not None else short_strike - 5.0
        long_row = _find_row(puts_df, long_s)

        if short_row is not None and "bid" in short_row and "ask" in short_row:
            short_ev = compute_slippage_ev(float(short_row["bid"]), float(short_row["ask"]))
        else:
            short_ev = compute_slippage_ev(short_strike * 0.012, short_strike * 0.016)

        if long_row is not None and "bid" in long_row and "ask" in long_row:
            # Buy the long put: pay ask
            long_ev = compute_slippage_ev(float(long_row["ask"]), float(long_row["bid"]))
        else:
            long_ev = compute_slippage_ev(long_s * 0.008, long_s * 0.012)

        spread_width = short_strike - long_s
        net_credit = short_ev - long_ev  # per share; sell short, buy long
        net_credit = max(net_credit, 0.01)  # floor at $0.01 to avoid degenerate math
        net_credit_contract = net_credit * 100
        max_loss = (spread_width - net_credit) * 100
        max_loss = max(max_loss, 0.0)
        breakeven = short_strike - net_credit

    else:
        # Collar: short call + long put (protective collar)
        # Collar P&L approximated as spread equivalent (near zero-cost collar assumption)
        collar_call_strike = (
            float(structure_result.collar_call_strike)
            if getattr(structure_result, "collar_call_strike", None) is not None
            else spot * 1.10
        )
        long_s = long_strike if long_strike is not None else short_strike - 5.0

        put_row = _find_row(puts_df, short_strike)   # protective put (long put at short_strike role)
        call_row = _find_row(calls_df, collar_call_strike)  # short call leg

        if call_row is not None and "bid" in call_row and "ask" in call_row:
            call_ev = compute_slippage_ev(float(call_row["bid"]), float(call_row["ask"]))
        else:
            call_ev = compute_slippage_ev(collar_call_strike * 0.012, collar_call_strike * 0.016)

        if put_row is not None and "bid" in put_row and "ask" in put_row:
            put_ev = compute_slippage_ev(float(put_row["bid"]), float(put_row["ask"]))
        else:
            put_ev = compute_slippage_ev(short_strike * 0.012, short_strike * 0.016)

        net_credit = max(call_ev - put_ev, 0.0)  # treat as zero-cost collar if net debit
        net_credit_contract = net_credit * 100
        spread_width = short_strike - long_s
        max_loss = (spread_width - net_credit) * 100
        max_loss = max(max_loss, 0.0)
        breakeven = short_strike - net_credit

    # ------------------------------------------------------------------
    # Step 4 — Compute scenario P&L and probability-weighted EV
    # ------------------------------------------------------------------
    scenarios_out: list[ScenarioPnL] = []
    for name in ("Bull", "Base", "Bear", "Crash"):
        terminal = spot * (1.0 + moves[name])
        pnl = _pnl_for_scenario(
            structure, short_strike, long_strike,
            terminal, net_credit, max_loss, net_credit_contract,
        )
        scenarios_out.append(
            ScenarioPnL(
                name=name,
                underlying_move=moves[name],
                terminal_price=terminal,
                pnl_per_contract=pnl,
                probability=probs[name],
                weighted_pnl=pnl * probs[name],
            )
        )

    # ------------------------------------------------------------------
    # Step 5 — Trade management levels
    # ------------------------------------------------------------------
    profit_target = net_credit_contract * 0.50   # close at 50% of max profit
    hard_stop = net_credit_contract * 2.0         # close if loss = 2× credit
    roll_trigger = breakeven * 0.97               # roll if underlying drops 3% below breakeven

    return (
        scenarios_out,
        net_credit,
        max_loss,
        breakeven,
        profit_target,
        hard_stop,
        roll_trigger,
        regime_label_used,
        probs,
    )


# ---------------------------------------------------------------------------
# compute_kelly_size
# ---------------------------------------------------------------------------

def compute_kelly_size(
    analytics_result: dict,
    ticker_info,
    pnl_result,
    portfolio_value: float,
    spot: Optional[float] = None,
) -> tuple[float, int, float, dict]:
    """Compute fractional Kelly position size with regime/VoV/GEX multipliers.

    Kelly formula: base_f=0.25, scaled by stacked multipliers, clamped to
    [max_position_pct/4, max_position_pct].

    Args:
        analytics_result: Dict from analytics engine; must contain "regime" and "signals".
        ticker_info:      TickerInfo with .max_position_pct.
        pnl_result:       PnLResult (currently unused, included for future extensions).
        portfolio_value:  Total portfolio value in dollars.
        spot:             Underlying spot price; falls back to analytics_result["spot"].

    Returns:
        Tuple of (kelly_dollars, kelly_contracts, kelly_pct, kelly_breakdown).
    """
    try:
        return _compute_kelly_inner(analytics_result, ticker_info, portfolio_value, spot)
    except Exception as exc:  # noqa: BLE001
        logger.error("compute_kelly_size: unexpected error: %s", exc, exc_info=True)
        # Safe fallback
        max_pos = getattr(ticker_info, "max_position_pct", 0.05)
        min_pos = max_pos / 4.0
        kelly_pct = min_pos
        kelly_dollars = kelly_pct * portfolio_value
        s = spot if spot is not None else analytics_result.get("spot", 100.0)
        kelly_contracts = max(1, int(kelly_dollars / (100.0 * s))) if s > 0 else 1
        return kelly_dollars, kelly_contracts, kelly_pct, {
            "base": 0.25, "regime_mult": 1.0, "vov_mult": 1.0,
            "gex_mult": 1.0, "final_f": 0.25, "kelly_pct": kelly_pct,
        }


def _compute_kelly_inner(
    analytics_result: dict,
    ticker_info,
    portfolio_value: float,
    spot: Optional[float],
) -> tuple[float, int, float, dict]:
    """Core Kelly computation — may raise; caller wraps in try/except."""

    regime = analytics_result.get("regime", {})
    regime_mult = float(regime.get("multiplier", 1.0))

    vov_z = analytics_result.get("signals", {}).get("vov_z", 0.0)
    vov_mult = 0.75 if vov_z > 1.5 else 1.0

    gex_bn = analytics_result.get("gex_billions", 0.0)
    gex_mult = 0.75 if gex_bn < 0 else 1.0

    base_f = 0.25
    final_f = base_f * regime_mult * vov_mult * gex_mult

    max_pos = float(ticker_info.max_position_pct)  # e.g. 0.05 for equity, 0.02 for crypto
    min_pos = max_pos / 4.0

    kelly_pct = float(np.clip(final_f * max_pos, min_pos, max_pos))
    kelly_dollars = kelly_pct * portfolio_value

    if spot is None:
        spot = analytics_result.get("spot", 100.0)
    kelly_contracts = max(1, int(kelly_dollars / (100.0 * spot))) if spot > 0 else 1

    breakdown = {
        "base": base_f,
        "regime_mult": regime_mult,
        "vov_mult": vov_mult,
        "gex_mult": gex_mult,
        "final_f": final_f,
        "kelly_pct": kelly_pct,
    }
    return kelly_dollars, kelly_contracts, kelly_pct, breakdown
