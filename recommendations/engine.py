"""
recommendations/engine.py
--------------------------
Orchestrator that chains all four recommendation sub-modules into the single
public entry point for Phase 5 and the Stage 2 scanner.

Pipeline order:
    select_structure()     (pre-select for go/no-go HARD-08 / HARD-09)
    select_strikes()       (expiration + strikes for slippage EV)
    compute_pnl_scenarios() (4-scenario P&L + net credit needed for HARD-03)
    evaluate_gonogo()      (21-point go/no-go using slippage_adj_ev from above)
    compute_kelly_size()   (fractional Kelly position sizing)
    build_recommendation_card() (narratives + order text; always built for UI)

Public API:
    run_recommendation()  — never raises; returns a complete result dict
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def run_recommendation(
    ticker: str,
    analytics_result: dict,
    fundamentals_result: dict,
    ticker_info,
    chain: dict,
    portfolio_value: float = 100_000.0,
) -> dict:
    """Orchestrate the full recommendation pipeline for a single Stage 2 candidate.

    Parameters
    ----------
    ticker : str
        Ticker symbol (case-insensitive; normalised to upper-case internally).
    analytics_result : dict
        Output from run_analytics() — must contain vrp_pctile, signals, regime, etc.
    fundamentals_result : dict
        Output from run_fundamentals() — must contain gate_result, altman, qoe.
    ticker_info : TickerInfo
        Resolved tier metadata from universe.loader.get_ticker_info().
    chain : dict
        Schwab options chain dict with "underlying_price" and "expirations".
    portfolio_value : float
        Total portfolio value in dollars (default $100,000).

    Returns
    -------
    dict
        A complete result dict with all card fields plus "passed" (bool) and
        "error" (str | None).  Never raises — any unhandled exception is caught
        and returned as {"error": str(exc), "passed": False}.
    """
    ticker = ticker.upper()
    base_result: dict = {"ticker": ticker, "error": None, "passed": False}

    # Pre-build the exhaustive None-fill for the exception path
    _null_fields = [
        "gonogo_summary", "gonogo_checks", "structure", "expiration_date",
        "dte", "short_strike", "long_strike", "spot", "target_delta",
        "fomc_status", "fomc_message", "net_credit", "max_loss", "breakeven",
        "profit_target", "hard_stop", "roll_trigger", "scenarios",
        "probability_weighted_ev", "slippage_adj_ev", "kelly_dollars",
        "kelly_contracts", "kelly_pct", "kelly_breakdown",
        "paragraph_1", "paragraph_2", "paragraph_3", "order_text", "card",
    ]

    try:
        from recommendations.structures import select_structure, select_strikes
        from recommendations.pnl import (
            PnLResult,
            compute_pnl_scenarios,
            compute_kelly_size,
        )
        from recommendations.gonogo import evaluate_gonogo
        from recommendations.card import build_recommendation_card

        today = date.today()
        spot: float = float(chain.get("underlying_price", 0.0))

        # Enrich analytics_result with asset_class (needed by compute_pnl_scenarios
        # to pick crypto vs equity scenario shocks).  Never mutate caller's dict.
        analytics_result = dict(analytics_result)
        analytics_result.setdefault("asset_class", ticker_info.asset_class)

        # ------------------------------------------------------------------
        # Step 1 — Pre-select structure (needed for HARD-08 / HARD-09)
        # ------------------------------------------------------------------
        proposed_structure: str = select_structure(ticker_info, analytics_result)

        # ------------------------------------------------------------------
        # Step 2 — Select strikes and expiration (needed for slippage EV)
        # ------------------------------------------------------------------
        structure_result = select_strikes(analytics_result, ticker_info, chain, today)

        # ------------------------------------------------------------------
        # Step 3 — Compute P&L to derive slippage_adj_ev for HARD-03
        # ------------------------------------------------------------------
        pnl_scenarios_out = compute_pnl_scenarios(structure_result, chain, analytics_result)
        (
            scenarios,
            net_credit,
            max_loss,
            breakeven,
            profit_target,
            hard_stop,
            roll_trigger,
        ) = pnl_scenarios_out

        # Net credit per contract (in dollars) is the slippage-adjusted EV
        slippage_adj_ev: float = net_credit

        # ------------------------------------------------------------------
        # Step 4 — Go/No-Go evaluation
        # ------------------------------------------------------------------
        gonogo_result = evaluate_gonogo(
            analytics_result=analytics_result,
            fundamentals_result=fundamentals_result,
            ticker_info=ticker_info,
            proposed_structure=proposed_structure,
            slippage_adj_ev=slippage_adj_ev,
        )

        # ------------------------------------------------------------------
        # Step 5 — Kelly sizing
        # ------------------------------------------------------------------
        # Build an initial PnLResult so Kelly can read max_loss / net_credit
        probability_weighted_ev = float(
            np.sum([s.weighted_pnl for s in scenarios])
        )
        pnl_result = PnLResult(
            net_credit=net_credit,
            max_loss=max_loss,
            breakeven=breakeven,
            profit_target=profit_target,
            hard_stop=hard_stop,
            roll_trigger=roll_trigger,
            scenarios=scenarios,
            probability_weighted_ev=probability_weighted_ev,
            slippage_adj_ev=slippage_adj_ev,
            kelly_dollars=0.0,
            kelly_contracts=0,
            kelly_pct=0.0,
            kelly_breakdown={},
        )

        kelly_dollars, kelly_contracts, kelly_pct, kelly_breakdown = compute_kelly_size(
            analytics_result, ticker_info, pnl_result, portfolio_value, spot=spot
        )

        # Replace with Kelly values populated
        pnl_result = dataclasses.replace(
            pnl_result,
            kelly_dollars=kelly_dollars,
            kelly_contracts=kelly_contracts,
            kelly_pct=kelly_pct,
            kelly_breakdown=kelly_breakdown,
        )

        # ------------------------------------------------------------------
        # Step 6 — Build recommendation card (always, even on go/no-go fail)
        # ------------------------------------------------------------------
        card = build_recommendation_card(
            ticker=ticker,
            analytics_result=analytics_result,
            fundamentals_result=fundamentals_result,
            ticker_info=ticker_info,
            chain=chain,
            gonogo_result=gonogo_result,
            structure_result=structure_result,
            pnl_result=pnl_result,
        )

        # Convert ScenarioPnL list to plain dicts for JSON serialisation
        scenarios_dicts = [dataclasses.asdict(s) for s in scenarios]

        result = {
            "ticker": ticker,
            "error": None,
            "passed": gonogo_result.passed,

            # Go/No-Go
            "gonogo_summary": card.gonogo_summary,
            "gonogo_checks": gonogo_result.checks,

            # Trade parameters
            "structure": card.structure,
            "expiration_date": card.expiration_date,
            "dte": card.dte,
            "short_strike": card.short_strike,
            "long_strike": card.long_strike,
            "collar_call_strike": card.collar_call_strike,
            "spot": card.spot,
            "target_delta": card.target_delta,
            "fomc_status": card.fomc_status,
            "fomc_message": card.fomc_message,

            # Trade economics
            "net_credit": card.net_credit,
            "max_loss": card.max_loss,
            "breakeven": card.breakeven,
            "profit_target": card.profit_target,
            "hard_stop": card.hard_stop,
            "roll_trigger": card.roll_trigger,

            # P&L scenarios
            "scenarios": scenarios_dicts,
            "probability_weighted_ev": card.probability_weighted_ev,
            "slippage_adj_ev": card.slippage_adj_ev,

            # Kelly sizing
            "kelly_dollars": card.kelly_dollars,
            "kelly_contracts": card.kelly_contracts,
            "kelly_pct": card.kelly_pct,
            "kelly_breakdown": card.kelly_breakdown,

            # Narratives
            "paragraph_1": card.paragraph_1,
            "paragraph_2": card.paragraph_2,
            "paragraph_3": card.paragraph_3,
            "order_text": card.order_text,

            # Full card for UI
            "card": dataclasses.asdict(card),
        }

        logger.info(
            "[REC] %s passed=%s structure=%s strike=%.1f dte=%d ev=%.2f kelly=%d contracts",
            ticker,
            gonogo_result.passed,
            card.structure,
            card.short_strike or 0.0,
            card.dte or 0,
            card.slippage_adj_ev or 0.0,
            card.kelly_contracts or 0,
        )
        return result

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[REC] run_recommendation(%s) failed: %s", ticker, exc, exc_info=True
        )
        return {
            **base_result,
            "error": str(exc),
            "passed": False,
            **{k: None for k in _null_fields},
        }
