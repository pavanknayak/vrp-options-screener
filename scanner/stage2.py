from __future__ import annotations
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from data.schwab_client import fetch_options_chain, fetch_ohlcv_schwab
from data.yfinance_fetcher import fetch_ohlcv
from data.fred_fetcher import get_risk_free_rate, fetch_vix_history
from analytics.engine import run_analytics
from fundamentals.engine import run_fundamentals
from recommendations.engine import run_recommendation
from universe.loader import get_ticker_info
from scanner.rate_limiter import get_schwab_bucket

logger = logging.getLogger(__name__)

_RATE_LIMIT_GAP = 0.6   # 100 req/min = 1 req per 0.6s
_last_schwab_call: float = 0.0


def _schwab_wait() -> None:
    global _last_schwab_call
    elapsed = time.time() - _last_schwab_call
    if elapsed < _RATE_LIMIT_GAP:
        time.sleep(_RATE_LIMIT_GAP - elapsed)
    _last_schwab_call = time.time()


def _get_ticker(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return c["ticker"]
    return c.ticker


def _get_current_vix() -> float:
    try:
        vix_hist = fetch_vix_history(lookback_days=5)
        if vix_hist is not None and not vix_hist.empty:
            return float(vix_hist.iloc[-1])
    except Exception:
        pass
    return 20.0  # fallback


def _analyze_one(ticker: str, r: float, vix: float) -> dict:
    _schwab_wait()
    ohlc = fetch_ohlcv(ticker)
    if ohlc is None or ohlc.empty:
        return {"ticker": ticker, "error": "ohlcv_unavailable"}
    chain = fetch_options_chain(ticker, min_dte=25, max_dte=55)
    if chain is None:
        logger.warning("[STAGE2] %s — chain is None, sleeping 60s and retrying", ticker)
        time.sleep(60)
        chain = fetch_options_chain(ticker, min_dte=25, max_dte=55)
    if chain is None:
        return {"ticker": ticker, "error": "schwab_chain_unavailable"}
    analytics_result = run_analytics(ticker, chain, ohlc, r, vix)
    if analytics_result.get("error"):
        return analytics_result

    # Resolve tier metadata — fall back to a minimal stub for unknown tickers
    ticker_info = get_ticker_info(ticker)
    if ticker_info is None:
        analytics_result["recommendation"] = {"error": "ticker_not_in_universe"}
        return analytics_result

    fundamentals_result = run_fundamentals(ticker, ticker_info.tier, ticker_info.asset_class)
    recommendation = run_recommendation(
        ticker=ticker,
        analytics_result=analytics_result,
        fundamentals_result=fundamentals_result,
        ticker_info=ticker_info,
        chain=chain,
    )
    analytics_result["recommendation"] = recommendation
    analytics_result["passed"] = recommendation.get("passed", False)
    return analytics_result


def _analyze_one_parallel(ticker: str, r: float, vix: float) -> dict:
    """Like _analyze_one but uses token bucket instead of global sleep."""
    # Acquire a Schwab token before making the API call
    get_schwab_bucket().acquire()

    # Prefer Schwab price history (already authenticated, no crumb issues); fall back to yfinance
    ohlc = fetch_ohlcv_schwab(ticker)
    if ohlc is None or ohlc.empty:
        ohlc = fetch_ohlcv(ticker)
    if ohlc is None or ohlc.empty:
        return {"ticker": ticker, "error": "ohlcv_unavailable"}

    chain = fetch_options_chain(ticker, min_dte=25, max_dte=55)
    if chain is None:
        logger.warning("[STAGE2] %s — chain is None, retrying after 60s", ticker)
        time.sleep(60)
        get_schwab_bucket().acquire()
        chain = fetch_options_chain(ticker, min_dte=25, max_dte=55)
    if chain is None:
        return {"ticker": ticker, "error": "schwab_chain_unavailable"}

    analytics_result = run_analytics(ticker, chain, ohlc, r, vix)
    if analytics_result.get("error"):
        return analytics_result

    ticker_info = get_ticker_info(ticker)
    if ticker_info is None:
        analytics_result["recommendation"] = {"error": "ticker_not_in_universe"}
        return analytics_result

    fundamentals_result = run_fundamentals(ticker, ticker_info.tier, ticker_info.asset_class)
    recommendation = run_recommendation(
        ticker=ticker,
        analytics_result=analytics_result,
        fundamentals_result=fundamentals_result,
        ticker_info=ticker_info,
        chain=chain,
    )
    analytics_result["recommendation"] = recommendation
    analytics_result["passed"] = recommendation.get("passed", False)
    return analytics_result


def run_stage2(
    candidates: list,
    r: Optional[float] = None,
    vix: Optional[float] = None,
    n_workers: int = 8,
) -> list[dict]:
    """Deep analysis with parallel workers + token bucket rate limiting.

    8 workers run concurrently; each acquires a Schwab token before calling the API.
    The token bucket ensures the collective rate stays at 100 req/min.
    Analytics and fundamentals (CPU-bound) run in parallel across workers,
    reducing total scan time by ~50-60% vs sequential.
    """
    if r is None:
        r = get_risk_free_rate()
    if vix is None:
        vix = _get_current_vix()

    logger.info("[STAGE2] Starting parallel Stage 2: %d candidates, %d workers", len(candidates), n_workers)
    t_start = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_to_ticker = {
            executor.submit(_analyze_one_parallel, _get_ticker(c), r, vix): _get_ticker(c)
            for c in candidates
        }
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                result = future.result(timeout=120)  # 2 min max per ticker
                results.append(result)
                if result.get("error"):
                    logger.warning("[STAGE2] %s error: %s", ticker, result["error"])
                else:
                    logger.debug("[STAGE2] %s score=%.1f", ticker, result.get("composite_score", 0))
            except Exception as exc:
                logger.error("[STAGE2] %s raised: %s", ticker, exc)
                results.append({"ticker": ticker, "error": str(exc)})

    good = [r for r in results if not r.get("error")]
    good.sort(key=lambda r: r.get("composite_score", 0.0), reverse=True)
    elapsed = time.time() - t_start
    logger.info("[STAGE2] Complete in %.1fs — %d results, %d errors", elapsed, len(good), len(results) - len(good))
    return good
