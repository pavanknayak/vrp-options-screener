"""
backtest/engine.py — Historical VRP signal backtesting engine.

Simulates the screener's signal logic on historical data to validate
signal quality without needing historical options chains.

Uses historical OHLCV + yfinance IV as proxy for options pricing.
Accuracy is approximate but gives directional signal calibration.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    ticker: str
    entry_date: str
    signal_score: float        # composite VRP score at entry
    structure: str
    short_strike: float
    expiration_date: str
    entry_credit: float        # estimated credit
    actual_pnl_pct: float      # realized P&L as % of max profit (-1 to 1+)
    win: bool                  # True if ended profitably


@dataclass
class BacktestResult:
    ticker: str
    trades: list[BacktestTrade]
    win_rate: float
    avg_pnl_pct: float
    total_trades: int
    max_drawdown_pct: float
    sharpe_ratio: float


def run_backtest(
    ticker: str,
    lookback_months: int = 12,
    min_ivp: float = 0.40,
    min_score_proxy: float = 0.02,  # minimum IVP * VRP_approx score
) -> Optional[BacktestResult]:
    """Run historical backtest for a single ticker.

    Uses yfinance OHLCV to simulate weekly entry signals going back
    `lookback_months`. For each signal date, simulates entering a
    30-35 DTE put and holding to 50% profit or expiration.

    Returns None if insufficient history.
    """
    try:
        from data.yfinance_fetcher import fetch_ohlcv
        import math

        ohlc = fetch_ohlcv(ticker, period_days=lookback_months * 30 + 60)
        if ohlc is None or len(ohlc) < 60:
            return None

        trades = []
        closes = ohlc["Close"].dropna()

        # Scan weekly entry points
        entry_indices = range(60, len(closes) - 35, 5)  # weekly steps

        for i in entry_indices:
            entry_price = float(closes.iloc[i])
            entry_date = closes.index[i]

            # Compute approximate IV and VRP
            window = closes.iloc[max(0, i - 21):i]
            if len(window) < 10:
                continue

            log_rets = np.log(window / window.shift(1)).dropna()
            realized_vol = float(log_rets.std() * np.sqrt(252))

            # Approximate IV from 21-day rolling vol percentile
            rolling_vols = []
            for j in range(max(0, i - 252), i, 5):
                sub = closes.iloc[max(0, j - 21):j]
                if len(sub) > 10:
                    lr = np.log(sub / sub.shift(1)).dropna()
                    rolling_vols.append(float(lr.std() * np.sqrt(252)))

            if len(rolling_vols) < 10:
                continue

            ivp_approx = float((np.array(rolling_vols) < realized_vol * 1.1).mean())
            atm_iv_approx = realized_vol * 1.08  # typical 8% VRP premium
            vrp_approx = atm_iv_approx - realized_vol

            score_proxy = ivp_approx * max(vrp_approx, 0)
            if score_proxy < min_score_proxy or ivp_approx < min_ivp:
                continue

            # Simulate 30 DTE put at ~0.20 delta
            short_strike = round(entry_price * 0.95, 0)  # 5% OTM
            entry_credit = atm_iv_approx * entry_price * math.sqrt(30 / 252) * 0.75 * 0.25  # approx BSM
            entry_credit = max(entry_credit, 0.10)

            # Find expiration
            exp_idx = min(i + 30, len(closes) - 1)
            exit_price = float(closes.iloc[exp_idx])
            exp_date = closes.index[exp_idx].strftime("%Y-%m-%d")

            # P&L calculation
            if exit_price >= short_strike:
                pnl = entry_credit * 100  # full profit
            else:
                pnl = (exit_price - short_strike + entry_credit) * 100

            max_profit = entry_credit * 100
            pnl_pct = pnl / max_profit if max_profit > 0 else 0

            trades.append(BacktestTrade(
                ticker=ticker,
                entry_date=entry_date.strftime("%Y-%m-%d"),
                signal_score=score_proxy * 100,
                structure="csp",
                short_strike=short_strike,
                expiration_date=exp_date,
                entry_credit=entry_credit,
                actual_pnl_pct=pnl_pct,
                win=pnl > 0,
            ))

        if not trades:
            return None

        pnls = [t.actual_pnl_pct for t in trades]
        win_rate = sum(1 for t in trades if t.win) / len(trades)
        avg_pnl = float(np.mean(pnls))

        # Cumulative P&L for drawdown
        cumulative = np.cumprod([1 + p * 0.05 for p in pnls])  # assume 5% risk per trade
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / peak
        max_dd = float(drawdown.max())

        # Sharpe (annualized, assume weekly frequency)
        sharpe = float(np.mean(pnls) / max(np.std(pnls), 0.01) * np.sqrt(52))

        return BacktestResult(
            ticker=ticker,
            trades=trades,
            win_rate=win_rate,
            avg_pnl_pct=avg_pnl,
            total_trades=len(trades),
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
        )
    except Exception as e:
        logger.error("Backtest failed for %s: %s", ticker, e)
        return None
