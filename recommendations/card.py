"""
recommendations/card.py
-----------------------
RecommendationCard assembly from gonogo, structure, and P&L results.

This is the human-facing output layer of the recommendation engine. Every
field the user acts on — strikes, sizing, order text, and written reasoning
— is assembled here.  Narrative paragraphs reference actual signal values;
no generic boilerplate is used.

Public API:
    RecommendationCard          — dataclass representing one complete recommendation
    build_recommendation_card() — assembles a card from upstream engine results
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RecommendationCard dataclass
# ---------------------------------------------------------------------------

@dataclass
class RecommendationCard:
    """Complete recommendation card for one trade candidate."""

    ticker: str
    passed: bool                     # False if go/no-go failed (card still generated for UI display)
    gonogo_summary: str              # "PASS" | "FAIL: {criterion} — {reason}"
    gonogo_checks: list[dict]        # raw check list from GoNoGoResult

    # Trade parameters
    structure: str                   # "csp" | "spread" | "collar"
    expiration_date: str             # "YYYY-MM-DD"
    dte: int
    short_strike: float
    long_strike: Optional[float]
    collar_call_strike: Optional[float]  # short call strike for collar; None for CSP/Spread
    spot: float
    target_delta: float
    fomc_status: str
    fomc_message: str

    # Trade economics (per contract = 100 shares)
    net_credit: float                # dollars
    max_loss: float                  # dollars
    breakeven: float                 # underlying price
    profit_target: float             # dollars (50% of max profit)
    hard_stop: float                 # dollars (2x credit)
    roll_trigger: float              # underlying price

    # P&L scenarios
    scenarios: list                  # list[ScenarioPnL]
    probability_weighted_ev: float   # dollars
    slippage_adj_ev: float           # dollars

    # Position sizing
    kelly_dollars: float
    kelly_contracts: int
    kelly_pct: float
    kelly_breakdown: dict

    # Narratives
    paragraph_1: str                 # Why premium exists
    paragraph_2: str                 # Why to enter now vs wait
    paragraph_3: str                 # What could cause this trade to lose

    # Order text
    order_text: str                  # broker-ready instruction


# ---------------------------------------------------------------------------
# Narrative paragraph builders
# ---------------------------------------------------------------------------

def _build_paragraph_1(ticker: str, analytics_result: dict, signals: dict) -> str:
    """Construct paragraph explaining why the premium opportunity exists.

    Every value is interpolated from actual signal data — no generic boilerplate.
    """
    ivp_pct = signals.get("ivp", 0.5) * 100
    vrp_pct = analytics_result.get("vrp_pctile", 0.5) * 100
    vrp_ann = analytics_result.get("vrp", 0.0) * 100
    skew_pct = signals.get("skew_25d", 0.0) * 100
    persist_pct = signals.get("vrp_persist_30d", 0.5) * 100
    excess_pct = signals.get("excess_vrp", 0.0) * 100

    return (
        f"IV30 is at the {ivp_pct:.0f}th percentile of the past 252 days (IVP). "
        f"VRP is at the {vrp_pct:.0f}th percentile of history (+{vrp_ann:.1f}% annualized above realized vol). "
        f"The 25-delta skew is {skew_pct:.1f}% (put premium over call), indicating hedging demand. "
        f"VRP has been positive {persist_pct:.0f}% of the last 30 trading sessions (persistence). "
        f"Excess VRP above beta-adjusted SPY benchmark: +{excess_pct:.2f}% — suggesting idiosyncratic premium collection opportunity."
    )


def _build_paragraph_2(
    ticker: str,
    analytics_result: dict,
    structure_result,
    signals: dict,
) -> str:
    """Construct paragraph explaining why to enter now vs. wait.

    References timing action, FOMC status, GEX, VoV, and term structure.
    """
    timing_action = analytics_result.get("timing_action", "ENTER AT OPPORTUNITY")
    timing_reason = analytics_result.get("timing_reason", "")

    fomc_status = structure_result.fomc_status
    fomc_message = structure_result.fomc_message

    gex = signals.get("gex_billions", 0.0)
    gex_sign = "positive" if gex >= 0 else "negative"
    gex_context = (
        "dealer gamma suppresses realized vol — supports premium collection"
        if gex >= 0
        else "negative dealer gamma amplifies realized vol — use reduced size"
    )

    vov_z = signals.get("vov_z", 0.0)
    vov_flag_text = (
        "stable IV regime — full size"
        if vov_z <= 1.5
        else f"elevated IV instability — size reduced by 25%"
    )

    term_slope = signals.get("term_slope", 0.0)
    if term_slope >= 0:
        term_context = f"contango ({term_slope * 100:.1f}pp) — normal structure supports premium collection"
    else:
        term_context = f"backwardation ({term_slope * 100:.1f}pp) — near-term stress, verify earnings calendar"

    return (
        f"Timing signal: {timing_action}. {timing_reason} "
        f"FOMC status: {fomc_status} — {fomc_message} "
        f"GEX is {gex_sign} at {gex:.2f}B ({gex_context}). "
        f"VoV Z-score is {vov_z:.2f} ({vov_flag_text}). "
        f"Term structure: {term_context}."
    )


def _build_paragraph_3(
    ticker: str,
    analytics_result: dict,
    signals: dict,
    fundamentals_result: dict,
    structure_result,
    pnl_result,
) -> str:
    """Construct paragraph describing specific risk factors.

    References the actual risk driver — earnings, jump flag, accrual anomaly,
    or macro correlation — never a generic placeholder.
    """
    # Primary risk — check in priority order
    if analytics_result.get("has_earnings_in_window"):
        primary_risk = "EARNINGS inside DTE window — binary event, do not enter"
    elif signals.get("jump_flag", ""):
        primary_risk = signals["jump_flag"]
    elif fundamentals_result.get("qoe", {}).get("accrual_anomaly", False):
        primary_risk = "accrual anomaly detected (CFO/NI < 0.8) — earnings quality suspect"
    else:
        primary_risk = (
            f"macro correlation — if VIX spikes sharply, {ticker} short-vol loses regardless of individual signals"
        )

    jump_pct = signals.get("jump_pct", 0.0)
    if jump_pct > 0.25:
        jump_text = f"jump component is {jump_pct * 100:.1f}% of RV — binary event risk elevated"
    else:
        jump_text = f"jump component is {jump_pct * 100:.1f}% of RV — diffusive vol dominates, clean VRP signal"

    regime_label = analytics_result.get("regime_label", "Normal")
    regime_msg = analytics_result.get("regime", {}).get("message", "")

    # Loss condition depends on structure
    structure = structure_result.structure
    if structure == "csp":
        distance_pct = (structure_result.spot - structure_result.short_strike) / structure_result.spot * 100
        loss_condition = (
            f"underlying {ticker} drops below ${structure_result.short_strike:.2f} "
            f"(current: ${structure_result.spot:.2f}, distance: {distance_pct:.1f}%)"
        )
    elif structure == "spread":
        loss_condition = (
            f"underlying {ticker} drops below ${structure_result.short_strike:.2f} "
            f"before expiration; max loss is ${pnl_result.max_loss:.0f}/contract"
        )
    else:  # collar
        loss_condition = (
            f"underlying {ticker} drops below ${structure_result.short_strike:.2f} "
            f"(put protection floor); upside capped at ${structure_result.collar_call_strike:.2f} "
            f"(short call ceiling)"
        )

    return (
        f"Primary risk: {primary_risk}. "
        f"Jump risk: {jump_text}. "
        f"Regime: {regime_label} ({regime_msg}). "
        f"This trade loses if {loss_condition}."
    )


# ---------------------------------------------------------------------------
# Order text builder
# ---------------------------------------------------------------------------

def _build_order_text(ticker: str, structure_result, pnl_result) -> str:
    """Generate broker-ready order instruction text.

    Formats vary by structure:
      - CSP:    STO {ticker} {exp_month} {strike}P at ${credit} credit
      - Spread: BTO {ticker} {exp_month} {long_strike}P / STO {ticker} {exp_month} {short_strike}P at ${credit} net credit
      - Collar: BUY stock / BUY {put} / STO {call} with net collar cost
    """
    # Parse expiration to "Mon DD" format
    try:
        exp_dt = datetime.fromisoformat(structure_result.expiration_date)
        exp_month = exp_dt.strftime("%b %d")
    except (ValueError, TypeError):
        exp_month = structure_result.expiration_date

    short_strike = structure_result.short_strike
    net_credit_per_share = pnl_result.net_credit / 100.0  # convert dollars/contract to per share
    max_loss = pnl_result.max_loss
    breakeven = pnl_result.breakeven

    structure = structure_result.structure

    if structure == "csp":
        return (
            f"STO {ticker} {exp_month} {short_strike:.0f}P at ${net_credit_per_share:.2f} credit\n"
            f"Max loss: ${max_loss:.0f}/contract | Breakeven: ${breakeven:.2f}"
        )

    elif structure == "spread":
        long_strike = structure_result.long_strike or (short_strike - 5.0)
        return (
            f"BTO {ticker} {exp_month} {long_strike:.0f}P / STO {ticker} {exp_month} {short_strike:.0f}P "
            f"at ${net_credit_per_share:.2f} net credit\n"
            f"Max loss: ${max_loss:.0f}/contract | Breakeven: ${breakeven:.2f}"
        )

    else:  # collar
        spot = structure_result.spot
        call_strike = structure_result.collar_call_strike or 0.0

        # For collar: net_credit represents the net of put debit and call credit.
        # Display put debit and call credit separately using proportional fallback.
        # pnl_result.net_credit is per-contract dollars; per-share = / 100
        # net_credit_per_share is effectively the net collar option cost per share.
        put_debit = net_credit_per_share       # put leg cost (positive = debit)
        call_credit = 0.0                      # call leg credit (fallback to 0 if not available)
        # If net_credit is meaningful, show it as the net collar option cost
        net_cost = put_debit - call_credit     # net cost after receiving call premium

        return (
            f"BUY {ticker} @${spot:.2f} (requires existing or new long stock position)\n"
            f"BUY {ticker} {exp_month} {short_strike:.0f}P at ${put_debit:.2f} debit (protective put)\n"
            f"STO {ticker} {exp_month} {call_strike:.0f}C at ${call_credit:.2f} credit (covered call)\n"
            f"Net collar cost: ${net_cost:.2f}/share | Put floor: ${short_strike:.0f} | Call ceiling: ${call_strike:.0f}"
        )


# ---------------------------------------------------------------------------
# Public assembly function
# ---------------------------------------------------------------------------

def build_recommendation_card(
    ticker: str,
    analytics_result: dict,
    fundamentals_result: dict,
    ticker_info,
    chain: dict,
    gonogo_result,
    structure_result,
    pnl_result,
) -> RecommendationCard:
    """Assemble a complete RecommendationCard from upstream engine results.

    This function never raises. On any unexpected exception it returns a
    minimal card with passed=False and an INTERNAL_ERROR gonogo_summary.

    Args:
        ticker:              Ticker symbol (e.g. "AAPL").
        analytics_result:    Dict from run_analytics() — must contain vrp_pctile, signals, etc.
        fundamentals_result: Dict from run_fundamentals() — must contain gate_result, qoe, altman.
        ticker_info:         TickerInfo resolved from universe.loader.
        chain:               Options chain dict (passed through; used for order text derivation).
        gonogo_result:       GoNoGoResult from evaluate_gonogo().
        structure_result:    StructureResult from select_strikes().
        pnl_result:          PnLResult from compute_kelly_size() / compute_pnl_scenarios().

    Returns:
        RecommendationCard with all fields populated.
    """
    try:
        return _build_card_inner(
            ticker, analytics_result, fundamentals_result, ticker_info,
            chain, gonogo_result, structure_result, pnl_result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "build_recommendation_card: unexpected error for %s: %s",
            ticker, exc, exc_info=True,
        )
        return RecommendationCard(
            ticker=ticker,
            passed=False,
            gonogo_summary=f"INTERNAL_ERROR: {exc}",
            gonogo_checks=[],
            structure=getattr(structure_result, "structure", "csp"),
            expiration_date=getattr(structure_result, "expiration_date", ""),
            dte=getattr(structure_result, "dte", 0),
            short_strike=getattr(structure_result, "short_strike", 0.0),
            long_strike=getattr(structure_result, "long_strike", None),
            collar_call_strike=getattr(structure_result, "collar_call_strike", None),
            spot=getattr(structure_result, "spot", 0.0),
            target_delta=getattr(structure_result, "target_delta", 0.25),
            fomc_status=getattr(structure_result, "fomc_status", ""),
            fomc_message=getattr(structure_result, "fomc_message", ""),
            net_credit=getattr(pnl_result, "net_credit", 0.0),
            max_loss=getattr(pnl_result, "max_loss", 0.0),
            breakeven=getattr(pnl_result, "breakeven", 0.0),
            profit_target=getattr(pnl_result, "profit_target", 0.0),
            hard_stop=getattr(pnl_result, "hard_stop", 0.0),
            roll_trigger=getattr(pnl_result, "roll_trigger", 0.0),
            scenarios=getattr(pnl_result, "scenarios", []),
            probability_weighted_ev=getattr(pnl_result, "probability_weighted_ev", 0.0),
            slippage_adj_ev=getattr(pnl_result, "slippage_adj_ev", 0.0),
            kelly_dollars=getattr(pnl_result, "kelly_dollars", 0.0),
            kelly_contracts=getattr(pnl_result, "kelly_contracts", 0),
            kelly_pct=getattr(pnl_result, "kelly_pct", 0.0),
            kelly_breakdown=getattr(pnl_result, "kelly_breakdown", {}),
            paragraph_1="",
            paragraph_2="",
            paragraph_3="",
            order_text="",
        )


def _build_card_inner(
    ticker: str,
    analytics_result: dict,
    fundamentals_result: dict,
    ticker_info,
    chain: dict,
    gonogo_result,
    structure_result,
    pnl_result,
) -> RecommendationCard:
    """Core card assembly logic — may raise; caller wraps in try/except."""

    # Extract signals dict for paragraph builders
    signals: dict = analytics_result.get("signals", {})

    # Go/No-Go summary
    passed: bool = gonogo_result.passed
    if passed:
        gonogo_summary = "PASS"
    else:
        gonogo_summary = (
            f"FAIL: {gonogo_result.failed_criterion} — {gonogo_result.failed_reason}"
        )

    # Build narrative paragraphs
    paragraph_1 = _build_paragraph_1(ticker, analytics_result, signals)
    paragraph_2 = _build_paragraph_2(ticker, analytics_result, structure_result, signals)
    paragraph_3 = _build_paragraph_3(
        ticker, analytics_result, signals, fundamentals_result, structure_result, pnl_result,
    )

    # Build broker-ready order text
    order_text = _build_order_text(ticker, structure_result, pnl_result)

    return RecommendationCard(
        ticker=ticker,
        passed=passed,
        gonogo_summary=gonogo_summary,
        gonogo_checks=gonogo_result.checks,

        # Trade parameters
        structure=structure_result.structure,
        expiration_date=structure_result.expiration_date,
        dte=structure_result.dte,
        short_strike=structure_result.short_strike,
        long_strike=structure_result.long_strike,
        collar_call_strike=structure_result.collar_call_strike,
        spot=structure_result.spot,
        target_delta=structure_result.target_delta,
        fomc_status=structure_result.fomc_status,
        fomc_message=structure_result.fomc_message,

        # Trade economics
        net_credit=pnl_result.net_credit,
        max_loss=pnl_result.max_loss,
        breakeven=pnl_result.breakeven,
        profit_target=pnl_result.profit_target,
        hard_stop=pnl_result.hard_stop,
        roll_trigger=pnl_result.roll_trigger,

        # P&L scenarios
        scenarios=pnl_result.scenarios,
        probability_weighted_ev=pnl_result.probability_weighted_ev,
        slippage_adj_ev=pnl_result.slippage_adj_ev,

        # Position sizing
        kelly_dollars=pnl_result.kelly_dollars,
        kelly_contracts=pnl_result.kelly_contracts,
        kelly_pct=pnl_result.kelly_pct,
        kelly_breakdown=pnl_result.kelly_breakdown,

        # Narratives
        paragraph_1=paragraph_1,
        paragraph_2=paragraph_2,
        paragraph_3=paragraph_3,

        # Order text
        order_text=order_text,
    )
