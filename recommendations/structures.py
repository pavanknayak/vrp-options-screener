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

SUPPORTED_STRUCTURES: set[str] = {"csp", "spread", "collar", "iron_condor"}


# ---------------------------------------------------------------------------
# StructureResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    """Complete trade structure selection output."""

    structure: str                          # "csp" | "spread" | "collar" | "iron_condor"
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
    ev_optimal_strike: Optional[float] = None  # EV-optimal put strike (B3); None if unavailable
    # Iron condor legs (C4) — None for non-condor structures
    ic_short_put: Optional[float] = None
    ic_long_put: Optional[float] = None
    ic_short_call: Optional[float] = None
    ic_long_call: Optional[float] = None


# ---------------------------------------------------------------------------
# B3 — EV-optimal strike selection helper
# ---------------------------------------------------------------------------

def _find_ev_optimal_strike(
    puts_df: pd.DataFrame,
    spot: float,
    dte_years: float,
) -> Optional[float]:
    """Find the put strike maximising probability-weighted EV across available strikes.

    For each candidate put strike K:
        EV(K) = P(S_T > K) * credit(K) - P(S_T <= K) * expected_loss(K)

    Uses log-normal approximation for P(S_T > K) with sigma=IV at that strike.
    Returns the EV-optimal strike, constrained to delta in [0.08, 0.38].
    Returns None if puts_df is empty or the computation fails.
    """
    if puts_df is None or puts_df.empty:
        return None
    try:
        import scipy.stats as stats  # deferred import to avoid circular issues

        best_ev = -np.inf
        best_strike = None

        for _, row in puts_df.iterrows():
            try:
                K = float(row.get("strike", 0))
                if K <= 0:
                    continue
                bid = float(row.get("bid", 0))
                ask = float(row.get("ask", bid))
                iv_val = row.get("iv", None)
                iv = float(iv_val) if iv_val is not None else 0.25
                if iv <= 0:
                    iv = 0.25
                delta_val = row.get("delta", None)
                delta = abs(float(delta_val)) if delta_val is not None else 0.20

                # Constrain to reasonable delta range
                if not (0.08 <= delta <= 0.38):
                    continue

                credit = (bid + ask) / 2 * 0.75  # slippage-adjusted
                if credit <= 0:
                    continue

                if dte_years <= 0:
                    continue

                # Log-normal probability: P(S_T > K)
                d2 = (np.log(spot / K) - 0.5 * iv ** 2 * dte_years) / (
                    iv * np.sqrt(dte_years)
                )
                p_profit = float(stats.norm.cdf(d2))
                p_loss = 1.0 - p_profit

                # Expected loss if assigned
                expected_loss = max(
                    K - spot * np.exp(-0.5 * iv ** 2 * dte_years), K * 0.10
                )

                ev = p_profit * credit * 100 - p_loss * expected_loss * 100

                if ev > best_ev:
                    best_ev = ev
                    best_strike = K
            except Exception:  # noqa: BLE001 — skip malformed rows silently
                continue

        return best_strike
    except Exception as exc:  # noqa: BLE001
        logger.warning("_find_ev_optimal_strike: computation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# C4 — Iron condor eligibility check
# ---------------------------------------------------------------------------

def _should_use_iron_condor(analytics_result: dict, ticker_info) -> bool:
    """Return True when iron condor is the appropriate structure.

    Criteria:
    - Tier is 1A-1I (liquid ETF)
    - composite_score > 65
    - vrp_persist_30d > 0.70
    - term_slope >= 0 (contango)
    - abs(pcr_oi - 1.0) < 0.5
    - regime not High or Crisis
    """
    try:
        signals = analytics_result.get("signals", {})
        regime = analytics_result.get("regime", {}).get("label", "Normal")
        tier = str(getattr(ticker_info, "tier", "2"))

        if not tier.startswith("1"):
            return False
        if regime in ("High", "Crisis"):
            return False
        if analytics_result.get("composite_score", 0) < 65:
            return False
        if signals.get("vrp_persist_30d", 0) < 0.70:
            return False
        if signals.get("term_slope", 0) < 0:
            return False
        if abs(signals.get("pcr_oi", 1.0) - 1.0) >= 0.5:
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("_should_use_iron_condor: check failed: %s", exc)
        return False


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

    # C4: Iron condor — preferred for Tier 1A-1I ETFs when conditions are met
    if _should_use_iron_condor(analytics_result, ticker_info):
        return "iron_condor"

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
        ic_short_put: Optional[float] = None
        ic_long_put: Optional[float] = None
        ic_short_call: Optional[float] = None
        ic_long_call: Optional[float] = None

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

        def _find_short_call(target_d: float) -> Optional[float]:
            """Find OTM call strike closest to target_d using delta column or BSM fallback."""
            if not calls_df.empty and "delta" in calls_df.columns and not calls_df["delta"].isna().all():
                valid_calls = calls_df.dropna(subset=["delta"])
                otm_calls = valid_calls[valid_calls["strike"] > spot]
                if otm_calls.empty:
                    otm_calls = valid_calls
                cidx = (otm_calls["delta"].abs() - target_d).abs().idxmin()
                return float(otm_calls.loc[cidx, "strike"])
            elif not calls_df.empty:
                k_approx = spot * np.exp(norm.ppf(1.0 - target_d) * iv * np.sqrt(T))
                cidx = (calls_df["strike"] - k_approx).abs().idxmin()
                return float(calls_df.loc[cidx, "strike"])
            return None

        def _compute_long_strike(short_s: float) -> float:
            """Compute long put strike approximately spread_width below short strike."""
            if spot <= 100.0:
                spread_width = max(5.0, round(spot * 0.05 / 5) * 5)
            else:
                spread_width = round(spot * 0.025 / 5) * 5
            long_s = max(short_s - spread_width, 0.0)
            return long_s

        def _compute_long_call_strike(short_call_s: float) -> float:
            """Compute long call strike approximately spread_width above short call."""
            if spot <= 100.0:
                spread_width = max(5.0, round(spot * 0.05 / 5) * 5)
            else:
                spread_width = round(spot * 0.025 / 5) * 5
            return short_call_s + spread_width

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

        # --- Iron Condor (C4) ---
        elif structure == "iron_condor":
            # Short put: ~0.15 delta OTM; Long put: ~0.10 delta OTM (5-pt below short)
            ic_short_put = _find_short_put(0.15)
            ic_long_put = _compute_long_strike(ic_short_put)
            # Short call: ~0.15 delta OTM; Long call: ~0.10 delta OTM (5-pt above short)
            ic_short_call_found = _find_short_call(0.15)
            if ic_short_call_found is None:
                ic_short_call_found = spot * 1.05  # 5% OTM fallback
            ic_short_call = ic_short_call_found
            ic_long_call = _compute_long_call_strike(ic_short_call)
            # For P&L compatibility, short_strike is the short put (put side dominates)
            short_strike = ic_short_put
            long_strike = ic_long_put
            collar_call_strike = ic_short_call
            delta_reason += "; iron_condor: short put ~0.15Δ, short call ~0.15Δ (5-pt wings)"

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

        # B3 — Compute EV-optimal strike (for put-side structures; non-blocking)
        ev_optimal_strike: Optional[float] = _find_ev_optimal_strike(puts_df, spot, T)

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
            ev_optimal_strike=ev_optimal_strike,
            ic_short_put=ic_short_put,
            ic_long_put=ic_long_put,
            ic_short_call=ic_short_call,
            ic_long_call=ic_long_call,
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
            ev_optimal_strike=None,
            ic_short_put=None,
            ic_long_put=None,
            ic_short_call=None,
            ic_long_call=None,
        )
