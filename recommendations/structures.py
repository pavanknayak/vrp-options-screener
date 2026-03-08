"""
recommendations/structures.py
------------------------------
Trade structure selection, Kelly-optimal delta selection, and FOMC-aware
DTE selection for the VRP Options Screener recommendation engine.

Public API:
    SUPPORTED_STRUCTURES  — module-level constant of implemented structures
    StructureResult       — dataclass returned by select_strikes()
    select_structure()    — picks the best structure for a ticker
    select_strikes()      — picks expiration + specific strikes from the chain
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from data.fomc import fomc_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported structures — source of truth for Phase 5
# ---------------------------------------------------------------------------

SUPPORTED_STRUCTURES: set[str] = {"csp", "spread", "collar"}


# ---------------------------------------------------------------------------
# StructureResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    """Complete trade structure selection output."""

    structure: str                          # "csp" | "spread" | "collar"
    expiration_date: str                    # ISO date string "YYYY-MM-DD"
    dte: int                                # actual DTE of selected expiration
    target_delta: float                     # Kelly-optimal delta [0.10, 0.35]
    short_strike: float                     # short put/call strike
    long_strike: Optional[float]            # long put strike for spread/collar; None for CSP
    collar_call_strike: Optional[float]     # short call strike for collar leg; None for CSP/Spread
    spot: float                             # underlying price at time of selection
    fomc_status: str                        # "CLEAR" | "FOMC_IN_WINDOW" | "AVOID" | "PRIORITY_ENTRY"
    fomc_message: str                       # human-readable fomc_context message
    delta_adjustment_reason: str            # explains why delta was shifted from 0.25


# ---------------------------------------------------------------------------
# select_structure
# ---------------------------------------------------------------------------

def select_structure(ticker_info, analytics_result) -> str:
    """Choose the best trade structure for the given ticker.

    Logic:
      1. Filter ticker_info.permitted_structures to SUPPORTED_STRUCTURES,
         silently dropping unsupported values (e.g., "strangle", "condor").
      2. Prefer "csp" for equity asset classes (not crypto_etf or china_adr).
      3. Prefer "spread" for crypto_etf / china_adr.
      4. Fall back to "collar" if neither csp nor spread is permitted.
      5. If no supported structure is available, warn and return "spread".

    Args:
        ticker_info:      TickerInfo with .permitted_structures and .asset_class.
        analytics_result: Dict from the analytics engine (currently unused here).

    Returns:
        A structure string: "csp", "spread", or "collar".
    """
    raw_permitted: list[str] = ticker_info.permitted_structures
    permitted: list[str] = [s for s in raw_permitted if s in SUPPORTED_STRUCTURES]

    if not permitted:
        logger.warning(
            "Ticker %s has no supported structures after filtering (raw=%s). "
            "Defaulting to 'spread'.",
            getattr(ticker_info, "symbol", "UNKNOWN"),
            raw_permitted,
        )
        return "spread"

    asset_class: str = ticker_info.asset_class

    # Prefer CSP for equity tiers (not crypto or china ADR)
    if "csp" in permitted and asset_class not in {"crypto_etf", "china_adr"}:
        return "csp"

    # Prefer Spread for crypto/china ADR (or equity without CSP)
    if "spread" in permitted:
        return "spread"

    # Collar as final fallback among supported structures
    if "collar" in permitted:
        return "collar"

    # Should not reach here given the empty-permitted guard above, but be safe
    return permitted[0]


# ---------------------------------------------------------------------------
# select_strikes
# ---------------------------------------------------------------------------

def select_strikes(analytics_result: dict, ticker_info, chain: dict, today_date: date) -> StructureResult:
    """Select expiration and strikes from an options chain.

    Steps:
      1. Compute target delta (0.25 baseline, adjusted for VRP/VoV signals).
      2. Find expiration nearest to 45 DTE, skipping FOMC AVOID windows.
      3. Identify short/long put strikes (and collar call strike if applicable).
      4. Return a StructureResult.

    Args:
        analytics_result: Dict with keys like "vrp_pctile", "iv30", "signals".
        ticker_info:      TickerInfo for structure and asset class decisions.
        chain:            Options chain dict with "underlying_price" and "expirations".
        today_date:       The evaluation date (used for DTE arithmetic and FOMC checks).

    Returns:
        StructureResult with all fields populated.
    """
    spot: float = chain.get("underlying_price", 100.0)

    try:
        # ------------------------------------------------------------------
        # Step 1 — Compute target delta
        # ------------------------------------------------------------------
        base_delta = 0.25
        vrp_pctile: float = analytics_result.get("vrp_pctile", 0.5)
        vov_z: float = analytics_result.get("signals", {}).get("vov_z", 0.0)

        reasons: list[str] = []
        if vrp_pctile > 0.80:
            base_delta = min(base_delta, 0.20)
            reasons.append("VRP at 80th+ pctile — tighter delta (0.20) to improve entry price")
        if vov_z > 1.5:
            base_delta = min(base_delta, 0.20)
            reasons.append(f"VoV Z={vov_z:.2f} >1.5 — safer delta (0.20)")

        target_delta: float = float(np.clip(base_delta, 0.10, 0.35))
        delta_reason: str = (
            "; ".join(reasons) if reasons else "Base 25\u0394 — no adjustment signals triggered"
        )

        # ------------------------------------------------------------------
        # Step 2 — Select expiration nearest to 45 DTE, FOMC-aware
        # ------------------------------------------------------------------
        expirations: list[dict] = chain.get("expirations", [])
        expirations_sorted: list[dict] = sorted(
            expirations, key=lambda e: abs(e.get("dte", 999) - 45)
        )

        selected_exp: Optional[dict] = None
        fomc_status: str = "CLEAR"
        fomc_msg: str = ""
        exp_date: date = today_date + timedelta(days=45)  # default if no expirations

        for exp in expirations_sorted:
            dte_val: int = exp.get("dte", 45)
            # Prefer the chain's stored date; fall back to arithmetic if absent
            if "date" in exp:
                candidate_date = date.fromisoformat(exp["date"])
            else:
                candidate_date = today_date + timedelta(days=dte_val)

            status, msg = fomc_context(today_date, candidate_date)
            if status == "AVOID":
                # Try next expiration in sorted list
                continue

            selected_exp = exp
            fomc_status = status
            fomc_msg = msg
            exp_date = candidate_date
            break

        if selected_exp is None:
            # All expirations are AVOID — use the furthest-out one (least-bad)
            if expirations_sorted:
                selected_exp = expirations_sorted[-1]
            elif expirations:
                selected_exp = expirations[0]
            else:
                selected_exp = {}

            dte_used: int = selected_exp.get("dte", 45)
            if "date" in selected_exp:
                exp_date = date.fromisoformat(selected_exp["date"])
            else:
                exp_date = today_date + timedelta(days=dte_used)
            fomc_status, fomc_msg = fomc_context(today_date, exp_date)

        # ------------------------------------------------------------------
        # Step 3 — Determine structure, then find strikes
        # ------------------------------------------------------------------
        structure: str = select_structure(ticker_info, analytics_result)

        iv: float = analytics_result.get("iv30", 0.25)
        T: float = max(selected_exp.get("dte", 45) / 365.0, 1e-4)

        puts_df: pd.DataFrame = selected_exp.get("puts", pd.DataFrame())
        calls_df: pd.DataFrame = selected_exp.get("calls", pd.DataFrame())

        short_strike: float
        long_strike: Optional[float] = None
        collar_call_strike: Optional[float] = None

        # --- Shared put selection logic ---
        def _find_short_put(target_d: float) -> float:
            """Find put strike closest to target_d using delta column or BSM fallback."""
            if "delta" in puts_df.columns and not puts_df["delta"].isna().all():
                valid_puts = puts_df.dropna(subset=["delta"])
                idx = (valid_puts["delta"].abs() - target_d).abs().idxmin()
                return float(valid_puts.loc[idx, "strike"])
            else:
                # BSM approximate delta strike for put
                k_approx = spot * np.exp(norm.ppf(target_d) * iv * np.sqrt(T))
                if not puts_df.empty:
                    idx = (puts_df["strike"] - k_approx).abs().idxmin()
                    return float(puts_df.loc[idx, "strike"])
                return round(spot * 0.90, 0)

        def _compute_long_strike(short_s: float) -> float:
            """Compute long put strike approximately spread_width below short strike."""
            if spot <= 100.0:
                spread_width = max(5.0, round(spot * 0.05 / 5) * 5)
            else:
                spread_width = round(spot * 0.025 / 5) * 5
            long_s = max(short_s - spread_width, 0.0)
            return long_s

        # --- CSP ---
        if structure == "csp":
            short_strike = _find_short_put(target_delta)
            long_strike = None
            collar_call_strike = None

        # --- Spread ---
        elif structure == "spread":
            short_strike = _find_short_put(target_delta)
            long_strike = _compute_long_strike(short_strike)
            collar_call_strike = None

        # --- Collar ---
        else:  # "collar"
            short_strike = _find_short_put(target_delta)
            long_strike = _compute_long_strike(short_strike)

            # Select short call at 0.25-delta OTM
            if (
                not calls_df.empty
                and "delta" in calls_df.columns
                and not calls_df["delta"].isna().all()
            ):
                valid_calls = calls_df.dropna(subset=["delta"])
                # Filter to OTM calls only (strike > spot) for a proper covered call leg
                otm_calls = valid_calls[valid_calls["strike"] > spot]
                if otm_calls.empty:
                    otm_calls = valid_calls  # fallback: use all if no OTM strikes available
                cidx = (otm_calls["delta"].abs() - 0.25).abs().idxmin()
                collar_call_strike = float(otm_calls.loc[cidx, "strike"])
            else:
                # BSM fallback for call strike: OTM above spot
                if not calls_df.empty:
                    k_call_approx = spot * np.exp(norm.ppf(0.75) * iv * np.sqrt(T))
                    cidx = (calls_df["strike"] - k_call_approx).abs().idxmin()
                    collar_call_strike = float(calls_df.loc[cidx, "strike"])

            if collar_call_strike is not None:
                delta_reason += (
                    f"; collar: short call selected at {collar_call_strike:.1f} (0.25\u0394 OTM call)"
                )

        # ------------------------------------------------------------------
        # Step 4 — Assemble StructureResult
        # ------------------------------------------------------------------
        return StructureResult(
            structure=structure,
            expiration_date=exp_date.isoformat(),
            dte=selected_exp.get("dte", 45),
            target_delta=target_delta,
            short_strike=short_strike,
            long_strike=long_strike,
            collar_call_strike=collar_call_strike,
            spot=spot,
            fomc_status=fomc_status,
            fomc_message=fomc_msg,
            delta_adjustment_reason=delta_reason,
        )

    except Exception:
        logger.exception(
            "select_strikes() failed for %s — returning fallback StructureResult.",
            getattr(ticker_info, "symbol", "UNKNOWN"),
        )
        return StructureResult(
            structure=select_structure(ticker_info, analytics_result),
            expiration_date=(today_date + timedelta(days=45)).isoformat(),
            dte=45,
            target_delta=0.25,
            short_strike=round(spot * 0.90, 0),
            long_strike=None,
            collar_call_strike=None,
            spot=spot,
            fomc_status="CLEAR",
            fomc_message="",
            delta_adjustment_reason="fallback: exception during selection",
        )
