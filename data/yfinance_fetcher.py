"""
data/yfinance_fetcher.py — yfinance data fetchers with TTL cache.

Provides:
  fetch_ohlcv(ticker, period_days=252) -> pd.DataFrame
  fetch_earnings_date(ticker) -> Optional[date]
  fetch_yf_options_summary(ticker) -> dict

All functions check the cache first, log HIT/MISS, and store fetched
results before returning. No exceptions propagate to callers.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

from cache.db import TTL, get_db

logger = logging.getLogger(__name__)

_BULK_BATCH_SIZE = 200  # max tickers per yf.download() call


# ---------------------------------------------------------------------------
# OHLCV history — bulk (Stage 1 pre-fetch)
# ---------------------------------------------------------------------------

def fetch_ohlcv_bulk(tickers: list[str], period_days: int = 252) -> dict[str, pd.DataFrame]:
    """Bulk OHLCV download using yf.download() — far fewer HTTP requests than individual calls.

    Returns a dict mapping ticker -> DataFrame. Tickers already in cache are skipped.
    Uses batches of _BULK_BATCH_SIZE to avoid URL length limits.
    """
    from cache.db import TTL, get_db as _get_db
    db = _get_db()
    today = date.today().isoformat()
    result: dict[str, pd.DataFrame] = {}
    uncached: list[str] = []

    for ticker in tickers:
        cached = db.get(f"{ticker}_ohlcv_{today}")
        if cached is not None:
            result[ticker] = cached
        else:
            uncached.append(ticker)

    if not uncached:
        logger.info("[BULK OHLCV] All %d tickers served from cache", len(result))
        return result

    logger.info("[BULK OHLCV] Downloading %d tickers in batches of %d", len(uncached), _BULK_BATCH_SIZE)

    for i in range(0, len(uncached), _BULK_BATCH_SIZE):
        batch = uncached[i : i + _BULK_BATCH_SIZE]
        try:
            raw = yf.download(
                batch,
                period="1y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue

            single = len(batch) == 1
            for ticker in batch:
                try:
                    if single:
                        df = raw.copy()
                    else:
                        # MultiIndex: level 0 = price field, level 1 = ticker
                        cols = {f: raw[f][ticker] for f in ["Open", "High", "Low", "Close", "Volume"] if f in raw.columns.get_level_values(0)}
                        df = pd.DataFrame(cols)

                    df = df.dropna(how="all")
                    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
                    df = df[keep].tail(period_days)

                    if len(df) >= 50:
                        db.set(f"{ticker}_ohlcv_{today}", df, TTL["ohlcv_history"])
                        result[ticker] = df
                except Exception:
                    pass  # individual parse failure — ticker will fall through to single fetch
        except Exception as exc:
            logger.warning("[BULK OHLCV] Batch %d-%d failed: %s", i, i + len(batch), exc)

    logger.info("[BULK OHLCV] Done — %d/%d tickers fetched", len(result), len(tickers))
    return result


# ---------------------------------------------------------------------------
# OHLCV history — single ticker (Stage 2 fallback)
# ---------------------------------------------------------------------------

def fetch_ohlcv(ticker: str, period_days: int = 252) -> pd.DataFrame:
    """Return a DataFrame of OHLCV data for *ticker* covering *period_days* trading days.

    Columns: Open, High, Low, Close, Volume (adjusted via auto_adjust=True).
    Result is cached for TTL['ohlcv_history'] (3600 seconds).
    Returns an empty DataFrame on any error.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_ohlcv_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.info("[CACHE HIT] ohlcv %s", ticker)
        return cached

    logger.info("[CACHE MISS] ohlcv %s — fetching yfinance", ticker)

    try:
        df: pd.DataFrame = yf.Ticker(ticker).history(
            period="1y", interval="1d", auto_adjust=True
        )

        if df.empty or len(df) < 50:
            raise ValueError(
                f"Insufficient OHLCV data for {ticker}: {len(df)} rows"
            )

        # Keep only the five canonical columns; drop extras like Dividends / Stock Splits
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[keep].copy()

        # Return the trailing period_days rows
        df = df.tail(period_days)

        get_db().set(cache_key, df, TTL["ohlcv_history"])
        return df

    except Exception as exc:
        logger.error("[ERROR] yfinance fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Earnings date
# ---------------------------------------------------------------------------

def fetch_earnings_date(ticker: str) -> Optional[date]:
    """Return the next upcoming earnings date for *ticker*, or None.

    Cached for TTL['earnings_dates'] (43200 seconds).
    Returns None on any error or when no upcoming date is found.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_earnings_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.info("[CACHE HIT] earnings %s", ticker)
        # Sentinel: we stored the string "NONE" when no date was found.
        return None if cached == "NONE" else cached

    logger.info("[CACHE MISS] earnings %s — fetching yfinance", ticker)

    try:
        tk = yf.Ticker(ticker)
        calendar = tk.calendar

        earnings_date: Optional[date] = None

        if calendar is not None:
            # calendar may be a dict or a DataFrame depending on yfinance version
            if isinstance(calendar, dict):
                raw = calendar.get("Earnings Date")
            elif isinstance(calendar, pd.DataFrame):
                if "Earnings Date" in calendar.index:
                    raw = calendar.loc["Earnings Date"].values.tolist()
                else:
                    raw = None
            else:
                raw = None

            if raw is not None:
                # raw can be a single value or a list
                if not isinstance(raw, (list, tuple)):
                    raw = [raw]

                today = date.today()
                future_dates: list[date] = []
                for item in raw:
                    if item is None:
                        continue
                    if isinstance(item, (datetime,)):
                        d = item.date()
                    elif isinstance(item, date):
                        d = item
                    else:
                        # Try to parse strings or Timestamp objects
                        try:
                            d = pd.Timestamp(item).date()
                        except Exception:
                            continue
                    if d >= today:
                        future_dates.append(d)

                if future_dates:
                    earnings_date = min(future_dates)

        # Cache the result; use sentinel "NONE" so a None miss is not confused
        # with a cache miss.
        get_db().set(cache_key, earnings_date if earnings_date is not None else "NONE", TTL["earnings_dates"])
        return earnings_date

    except Exception as exc:
        logger.error("[ERROR] yfinance fetch failed for %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Options summary (yfinance approximate, used in Stage 1 pre-filter)
# ---------------------------------------------------------------------------

def fetch_yf_options_summary(ticker: str) -> dict:
    """Return a dict with approximate ATM IV, OI, expiration, and bid/ask spread.

    Keys: atm_iv (float), atm_oi (int), expiration (str), bid_ask_pct (float).
    Returns {} on any error or when options data is unavailable.
    Cached for TTL['options_chain_yf'] (1800 seconds).
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_yf_options_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.info("[CACHE HIT] yf_options %s", ticker)
        return cached

    logger.info("[CACHE MISS] yf_options %s — fetching yfinance", ticker)

    try:
        tk = yf.Ticker(ticker)
        exps = tk.options
        if not exps:
            logger.warning("[WARN] No options expirations for %s", ticker)
            result: dict = {}
            get_db().set(cache_key, result, TTL["options_chain_yf"])
            return result

        nearest_exp = exps[0]
        chain = tk.option_chain(nearest_exp)
        calls = chain.calls

        if calls.empty:
            logger.warning("[WARN] Empty calls chain for %s %s", ticker, nearest_exp)
            result = {}
            get_db().set(cache_key, result, TTL["options_chain_yf"])
            return result

        # Determine current price
        try:
            current_price = tk.fast_info["last_price"]
        except Exception:
            current_price = tk.info.get("regularMarketPrice")

        if current_price is None:
            logger.warning("[WARN] Could not determine price for %s", ticker)
            result = {}
            get_db().set(cache_key, result, TTL["options_chain_yf"])
            return result

        # Find ATM strike (closest to current price)
        atm_idx = (calls["strike"] - current_price).abs().idxmin()

        atm_iv = float(calls.loc[atm_idx, "impliedVolatility"])
        atm_oi = int(calls.loc[atm_idx, "openInterest"])

        bid = calls.loc[atm_idx, "bid"]
        ask = calls.loc[atm_idx, "ask"]
        mid = (bid + ask) / 2
        bid_ask_pct = float((ask - bid) / mid) if mid > 0 else 0.0

        result = {
            "atm_iv": atm_iv,
            "atm_oi": atm_oi,
            "expiration": nearest_exp,
            "bid_ask_pct": bid_ask_pct,
        }
        get_db().set(cache_key, result, TTL["options_chain_yf"])
        return result

    except Exception as exc:
        logger.warning("[WARN] yf_options fetch failed for %s: %s", ticker, exc)
        result = {}
        get_db().set(cache_key, result, TTL["options_chain_yf"])
        return result
