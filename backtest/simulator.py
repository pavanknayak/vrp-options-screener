"""
backtest/simulator.py — Multi-ticker backtest runner with caching.
"""
from __future__ import annotations
import logging
from typing import Callable
from backtest.engine import run_backtest, BacktestResult

logger = logging.getLogger(__name__)


def run_portfolio_backtest(
    tickers: list[str],
    lookback_months: int = 12,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, BacktestResult]:
    """Run backtest for a list of tickers. Returns dict of ticker -> BacktestResult."""
    results = {}
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i, len(tickers))
        result = run_backtest(ticker, lookback_months=lookback_months)
        if result is not None:
            results[ticker] = result
    return results


def get_backtest_summary(results: dict[str, BacktestResult]) -> dict:
    """Aggregate backtest results across all tickers."""
    if not results:
        return {}

    all_win_rates = [r.win_rate for r in results.values()]
    all_pnls = [r.avg_pnl_pct for r in results.values()]
    all_sharpes = [r.sharpe_ratio for r in results.values()]

    import numpy as np
    return {
        "tickers_tested": len(results),
        "avg_win_rate": float(np.mean(all_win_rates)),
        "avg_pnl_pct": float(np.mean(all_pnls)),
        "avg_sharpe": float(np.mean(all_sharpes)),
        "best_ticker": max(results.items(), key=lambda x: x[1].sharpe_ratio)[0],
        "worst_ticker": min(results.items(), key=lambda x: x[1].sharpe_ratio)[0],
    }
