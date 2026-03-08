from __future__ import annotations
import logging
from typing import Optional
from scanner.stage2 import run_stage2
from data.fred_fetcher import fetch_vix_history, get_risk_free_rate
from data.yfinance_fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)


def run_quick_refresh(
    prev_results: list[dict],
    top_n: int = 30,
    r: Optional[float] = None,
    vix: Optional[float] = None,
) -> list[dict]:
    logger.info("[QUICK_REFRESH] Re-analyzing top %d candidates", top_n)
    sorted_prev = sorted(prev_results, key=lambda r: r.get("composite_score", 0.0), reverse=True)
    top_tickers = [r["ticker"] for r in sorted_prev[:top_n]]
    return run_stage2(top_tickers, r=r, vix=vix)


def run_single_ticker(
    ticker: str,
    r: Optional[float] = None,
    vix: Optional[float] = None,
) -> dict:
    ticker = ticker.upper().strip()
    logger.info("[SINGLE_TICKER] Analyzing %s", ticker)
    results = run_stage2([ticker], r=r, vix=vix)
    if results:
        return results[0]
    return {"ticker": ticker, "error": "no_result"}


def check_vix_event_trigger(threshold_pct: float = 5.0) -> bool:
    try:
        vix_hist = fetch_vix_history(lookback_days=5)
        if vix_hist is None or len(vix_hist) < 2:
            return False
        prior_close = float(vix_hist.iloc[-2])
        current = float(vix_hist.iloc[-1])
        rise_pct = (current - prior_close) / prior_close * 100.0
        triggered = rise_pct >= threshold_pct
        if triggered:
            logger.warning("[EVENT_REFRESH] VIX event triggered: %.1f%% rise (%.1f -> %.1f)", rise_pct, prior_close, current)
        return triggered
    except Exception as exc:
        logger.error("[EVENT_REFRESH] VIX check failed: %s", exc)
        return False


def run_event_refresh(
    prev_results: list[dict],
    top_n: int = 50,
    r: Optional[float] = None,
    vix: Optional[float] = None,
) -> list[dict]:
    logger.info("[EVENT_REFRESH] Running event-triggered refresh on top %d", top_n)
    sorted_prev = sorted(prev_results, key=lambda r: r.get("composite_score", 0.0), reverse=True)
    top_tickers = [r["ticker"] for r in sorted_prev[:top_n]]
    return run_stage2(top_tickers, r=r, vix=vix)
