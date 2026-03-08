from __future__ import annotations
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import pandas as pd
from data.yfinance_fetcher import fetch_ohlcv, fetch_earnings_date, fetch_yf_options_summary
from universe.loader import load_universe, TickerInfo

logger = logging.getLogger(__name__)


@dataclass
class Stage1Result:
    ticker: str
    tier: str
    asset_class: str
    score: float          # IVP * max(VRP_approx, 0)
    ivp_approx: float     # percentile of atm_iv in 30-day ohlcv-derived vol
    vrp_approx: float     # atm_iv - realized_vol_30d_approx
    atm_iv: float
    earnings_date: Optional[date]
    skip_reason: Optional[str]   # non-None means ticker was skipped


def _score_ticker(ticker: str, info: TickerInfo, min_dte: int, max_dte: int) -> Stage1Result:
    try:
        # Step 1: Fetch OHLCV
        ohlc = fetch_ohlcv(ticker)
        if ohlc is None or ohlc.empty:
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=None, skip_reason="ohlcv_unavailable")

        # Step 2: Earnings filter
        earnings = fetch_earnings_date(ticker)
        today = date.today()
        dte_window_start = today + timedelta(days=min_dte)
        dte_window_end = today + timedelta(days=max_dte)
        if earnings is not None and dte_window_start <= earnings <= dte_window_end:
            logger.warning("[STAGE1 SKIP] %s — earnings %s inside DTE window %d-%d", ticker, earnings, min_dte, max_dte)
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=earnings, skip_reason=f"earnings_in_window:{earnings}")

        # Step 3: Fetch yfinance options summary
        yf_opts = fetch_yf_options_summary(ticker)
        if not yf_opts:
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=earnings, skip_reason="options_unavailable")

        # Step 4: Liquidity gate
        atm_bid_ask_max = info.options_filter.get("atm_bid_ask_max_pct", 0.50)
        min_oi = info.options_filter.get("min_oi", 10)
        if yf_opts.get("bid_ask_pct", 1.0) > atm_bid_ask_max:
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=earnings, skip_reason="bid_ask_too_wide")
        if yf_opts.get("atm_oi", 0) < min_oi:
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=earnings, skip_reason="insufficient_oi")

        # Step 5: Approximate IVP and VRP
        atm_iv = yf_opts.get("atm_iv", 0.0)
        closes = ohlc["Close"].dropna()
        if len(closes) < 31:
            return Stage1Result(ticker=ticker, tier=info.tier, asset_class=info.asset_class, score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=atm_iv, earnings_date=earnings, skip_reason="insufficient_history")
        log_rets = closes.pct_change().dropna()
        realized_30d = float(log_rets.tail(21).std() * math.sqrt(252))
        vrp_approx = atm_iv - realized_30d
        rolling_stds = log_rets.rolling(21).std().dropna() * math.sqrt(252)
        ivp_approx = float((rolling_stds < atm_iv).mean()) if len(rolling_stds) > 10 else 0.5
        score = ivp_approx * max(vrp_approx, 0.0)

        # Step 6: Return result
        return Stage1Result(
            ticker=ticker,
            tier=info.tier,
            asset_class=info.asset_class,
            score=score,
            ivp_approx=ivp_approx,
            vrp_approx=vrp_approx,
            atm_iv=atm_iv,
            earnings_date=earnings,
            skip_reason=None,
        )
    except Exception as exc:
        logger.error("[STAGE1 ERROR] %s: %s", ticker, exc)
        return Stage1Result(ticker=ticker, tier=info.tier if hasattr(info, 'tier') else "?", asset_class=info.asset_class if hasattr(info, 'asset_class') else "?", score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=None, skip_reason=f"error:{exc}")


def run_stage1(
    universe: Optional[dict] = None,
    n_workers: int = 20,
    top_n: int = 175,
    min_dte: int = 25,
    max_dte: int = 55,
    per_ticker_timeout: float = 8.0,
) -> list[Stage1Result]:
    if universe is None:
        universe = load_universe()
    logger.info("[STAGE1] Starting Stage 1 scan: %d tickers, %d workers", len(universe), n_workers)
    t_start = time.time()
    results: list[Stage1Result] = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_to_ticker = {
            executor.submit(_score_ticker, ticker, info, min_dte, max_dte): ticker
            for ticker, info in universe.items()
        }
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                result = future.result(timeout=per_ticker_timeout)
                results.append(result)
            except FuturesTimeoutError:
                logger.warning("[STAGE1 TIMEOUT] %s exceeded %.1fs", ticker, per_ticker_timeout)
                results.append(Stage1Result(ticker=ticker, tier="?", asset_class="?", score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=None, skip_reason="timeout"))
            except Exception as exc:
                logger.error("[STAGE1 ERROR] %s: %s", ticker, exc)
                results.append(Stage1Result(ticker=ticker, tier="?", asset_class="?", score=0.0, ivp_approx=0.0, vrp_approx=0.0, atm_iv=0.0, earnings_date=None, skip_reason=f"error:{exc}"))
    candidates = [r for r in results if r.skip_reason is None]
    candidates.sort(key=lambda r: r.score, reverse=True)
    top = candidates[:top_n]
    elapsed = time.time() - t_start
    logger.info("[STAGE1] Complete in %.1fs — %d candidates (from %d scored, %d skipped)", elapsed, len(top), len(candidates), len(results) - len(candidates))
    return top
