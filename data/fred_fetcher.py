"""
data/fred_fetcher.py — FRED data fetchers with TTL cache.

Provides:
  fetch_fred_rate(series_id="DGS3MO") -> Optional[float]
  fetch_vix_history(lookback_days=252) -> Optional[pd.Series]
  get_risk_free_rate() -> float

Reads FRED_API_KEY from the environment at module load time.
If the key is absent, all fetch functions return None gracefully.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from cache.db import TTL, get_db

logger = logging.getLogger(__name__)

# Module-level API key — set to None when the env var is absent.
FRED_API_KEY: Optional[str] = os.environ.get("FRED_API_KEY")


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get_fred_client():
    """Return a fredapi.Fred client, or None if no API key is configured."""
    if not FRED_API_KEY:
        return None
    try:
        from fredapi import Fred  # type: ignore[import]
        return Fred(api_key=FRED_API_KEY)
    except Exception as exc:
        logger.error("[ERROR] Could not create FRED client: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Risk-free rate (DGS3MO by default)
# ---------------------------------------------------------------------------

def fetch_fred_rate(series_id: str = "DGS3MO") -> Optional[float]:
    """Return the most recent value of a FRED series as a decimal fraction.

    Example: 5.25 % is returned as 0.0525.
    Cached for TTL['fred_rates'] (21600 seconds).
    Returns None if the API key is absent, the series is unavailable, or any
    error occurs.
    """
    cache_key = f"fred_{series_id}_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.info("[CACHE HIT] fred %s", series_id)
        return cached

    logger.info("[CACHE MISS] fred %s — fetching FRED API", series_id)

    if not FRED_API_KEY:
        logger.debug(
            "[DEBUG] FRED_API_KEY not set — cannot fetch %s; returning None",
            series_id,
        )
        return None

    try:
        fred = _get_fred_client()
        if fred is None:
            return None

        today = date.today()
        # Fetch recent observations (last 30 days) to ensure we get the latest value
        start = today - timedelta(days=30)
        series: pd.Series = fred.get_series(
            series_id,
            observation_start=start.isoformat(),
            observation_end=today.isoformat(),
        )

        # Drop NaN and take the last valid value
        series = series.dropna()
        if series.empty:
            logger.warning("[WARN] FRED series %s returned no data", series_id)
            return None

        value_pct: float = float(series.iloc[-1])
        value_decimal = value_pct / 100.0

        get_db().set(cache_key, value_decimal, TTL["fred_rates"])
        return value_decimal

    except Exception as exc:
        logger.error("[ERROR] FRED fetch failed for %s: %s", series_id, exc)
        return None


# ---------------------------------------------------------------------------
# VIX history
# ---------------------------------------------------------------------------

def fetch_vix_history(lookback_days: int = 252) -> Optional[pd.Series]:
    """Return a pd.Series of daily VIX closes for the past *lookback_days* calendar days.

    Series index is a DatetimeIndex; values are floats.
    NaN values are dropped before returning.
    Cached for TTL['fred_rates'] (21600 seconds).
    Returns None if the API key is absent or any error occurs.
    """
    cache_key = f"fred_VIXCLS_{date.today().isoformat()}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.info("[CACHE HIT] fred VIXCLS")
        return cached

    logger.info("[CACHE MISS] fred VIXCLS — fetching FRED API")

    if not FRED_API_KEY:
        logger.debug("[DEBUG] FRED_API_KEY not set — cannot fetch VIX history; returning None")
        return None

    try:
        fred = _get_fred_client()
        if fred is None:
            return None

        today = date.today()
        start = today - timedelta(days=lookback_days)
        series: pd.Series = fred.get_series(
            "VIXCLS",
            observation_start=start.isoformat(),
            observation_end=today.isoformat(),
        )

        series = series.dropna().astype(float)

        if series.empty:
            logger.warning("[WARN] FRED VIXCLS returned no data")
            return None

        get_db().set(cache_key, series, TTL["fred_rates"])
        return series

    except Exception as exc:
        logger.error("[ERROR] FRED VIX history fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

def get_risk_free_rate() -> float:
    """Return the current 3-month T-bill rate as a decimal fraction.

    Falls back to 0.05 (5 %) if the FRED key is absent or the fetch fails.
    Always returns a float — never raises.
    """
    result = fetch_fred_rate("DGS3MO")
    if result is None:
        logger.info("[INFO] Using default risk-free rate of 0.05 (FRED data unavailable)")
        return 0.05
    return result
