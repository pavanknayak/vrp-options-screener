"""
data/schwab_client.py — Schwab OAuth2 client singleton and options chain fetcher.

Uses schwab-py library for authenticated access to Schwab's Market Data API.
Guards all schwab imports so the app starts cleanly without credentials or the library installed.

Exports:
    get_schwab_client()        -> schwab client or None
    schwab_connection_status() -> {"connected": bool, "message": str, "token_path": str}
    fetch_options_chain(ticker, min_dte, max_dte) -> dict or None
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from cache.db import TTL, get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guard schwab import — library may not be installed
# ---------------------------------------------------------------------------
try:
    import schwab  # type: ignore[import]
except ImportError:
    schwab = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_client = None          # cached Schwab client singleton
_last_request_time: float = 0.0  # epoch seconds of last API call

_TOKEN_PATH = str(Path(__file__).parent.parent / "schwab_token.json")
_CALLBACK_URL = "https://127.0.0.1"
_RATE_LIMIT_GAP = 0.6   # seconds between requests (100 req/min)


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def get_schwab_client():
    """Return the Schwab client singleton, or None if not configured/available."""
    global _client

    if _client is not None:
        return _client

    if schwab is None:
        logger.warning("schwab-py library not installed — Schwab features disabled")
        return None

    api_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")

    if not api_key or not app_secret:
        logger.warning(
            "SCHWAB_APP_KEY and/or SCHWAB_APP_SECRET not set — Schwab features disabled"
        )
        return None

    try:
        _client = schwab.auth.easy_client(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=_CALLBACK_URL,
            token_path=_TOKEN_PATH,
        )
        logger.info("Schwab client initialised successfully (token: %s)", _TOKEN_PATH)
        return _client
    except Exception as exc:
        logger.error("Failed to initialise Schwab client: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------

def schwab_connection_status() -> dict:
    """Return connection diagnostics dict.

    Keys:
        connected  (bool)
        message    (str)
        token_path (str)
    """
    token_path = _TOKEN_PATH
    token_exists = Path(token_path).exists()

    client = get_schwab_client()

    if client is not None:
        message = "Connected — token valid"
        connected = True
    elif schwab is None:
        message = "Not connected — schwab-py library not installed"
        connected = False
    elif not os.environ.get("SCHWAB_APP_KEY"):
        message = "Not connected — SCHWAB_APP_KEY not set"
        connected = False
    elif not os.environ.get("SCHWAB_APP_SECRET"):
        message = "Not connected — SCHWAB_APP_SECRET not set"
        connected = False
    elif not token_exists:
        message = "Not connected — no token file; OAuth required on first run"
        connected = False
    else:
        message = "Not connected — token expired or invalid"
        connected = False

    return {
        "connected": connected,
        "message": message,
        "token_path": token_path,
    }


# ---------------------------------------------------------------------------
# Rate limiting helper
# ---------------------------------------------------------------------------

def _enforce_rate_limit() -> None:
    """Sleep if needed to maintain the 0.6 s inter-request gap."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_GAP:
        time.sleep(_RATE_LIMIT_GAP - elapsed)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Options chain parsing
# ---------------------------------------------------------------------------

_OPTION_COLS = [
    "strike",
    "bid",
    "ask",
    "mark",
    "delta",
    "gamma",
    "theta",
    "vega",
    "impliedVolatility",
    "openInterest",
    "totalVolume",
    "daysToExpiration",
]


def _parse_exp_map(exp_date_map: dict) -> list[dict]:
    """Convert Schwab callExpDateMap / putExpDateMap into list of per-expiration dicts.

    Each entry: {"date": "2025-05-16", "dte": int, "options": [row_dict, ...]}
    """
    results = []
    for date_key, strikes in exp_date_map.items():
        # date_key looks like "2025-05-16:30" (date:dte)
        parts = date_key.split(":")
        exp_date_str = parts[0]
        dte = int(parts[1]) if len(parts) > 1 else 0

        rows = []
        for strike_str, contracts in strikes.items():
            for contract in contracts:
                row = {col: contract.get(col) for col in _OPTION_COLS}
                row["strike"] = float(strike_str)
                rows.append(row)

        results.append({"date": exp_date_str, "dte": dte, "options": rows})

    return results


def _build_df(option_rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame from a list of option contract row dicts."""
    if not option_rows:
        return pd.DataFrame(columns=_OPTION_COLS)
    df = pd.DataFrame(option_rows)[_OPTION_COLS]
    for col in _OPTION_COLS:
        if col != "strike":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("strike").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public fetcher
# ---------------------------------------------------------------------------

def fetch_options_chain(
    ticker: str,
    min_dte: int = 25,
    max_dte: int = 55,
) -> Optional[dict]:
    """Fetch a live options chain for *ticker* bracketing min_dte to max_dte.

    Returns:
        {
            "underlying_price": float,
            "expirations": [
                {"date": str, "dte": int, "calls": DataFrame, "puts": DataFrame},
                ...
            ],
            "ticker": str,
        }
        or None if Schwab is not configured or the request fails.
    """
    ticker = ticker.upper()
    cache_key = f"{ticker}_schwab_options_{datetime.now().strftime('%Y%m%d_%H')}"

    cached = get_db().get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for %s options chain", ticker)
        return cached

    client = get_schwab_client()
    if client is None:
        return None

    exp_from = (date.today() + timedelta(days=min_dte)).isoformat()
    exp_to = (date.today() + timedelta(days=max_dte)).isoformat()

    def _do_request():
        _enforce_rate_limit()
        return client.get_option_chain(
            ticker,
            contract_type=client.Options.ContractType.ALL,
            strike_count=40,
            include_underlying_quote=True,
            strategy=client.Options.Strategy.SINGLE,
            from_date=exp_from,
            to_date=exp_to,
        )

    try:
        resp = _do_request()
    except Exception as exc:
        # Handle 429 rate limit — one retry after 30 s
        exc_str = str(exc)
        if "429" in exc_str:
            logger.warning("Schwab 429 rate limit hit; sleeping 30 s then retrying")
            time.sleep(30)
            try:
                resp = _do_request()
            except Exception as retry_exc:
                logger.error("Schwab retry failed: %s", retry_exc)
                return None
        else:
            logger.error("Schwab options chain request failed: %s", exc)
            return None

    try:
        data = resp.json()
    except Exception as exc:
        logger.error("Failed to parse Schwab JSON response: %s", exc)
        return None

    try:
        underlying = data.get("underlying", {})
        underlying_price = float(underlying.get("mark") or underlying.get("last") or 0)

        call_map = data.get("callExpDateMap", {})
        put_map = data.get("putExpDateMap", {})

        call_exps = _parse_exp_map(call_map)
        put_exps = _parse_exp_map(put_map)

        # Index put exps by date for easy lookup
        put_by_date: dict[str, list] = {e["date"]: e["options"] for e in put_exps}

        expirations = []
        for c_exp in call_exps:
            exp_date = c_exp["date"]
            dte = c_exp["dte"]
            calls_df = _build_df(c_exp["options"])
            puts_df = _build_df(put_by_date.get(exp_date, []))
            expirations.append(
                {"date": exp_date, "dte": dte, "calls": calls_df, "puts": puts_df}
            )

        if not expirations:
            logger.warning("Schwab returned no expirations for %s in DTE %d-%d", ticker, min_dte, max_dte)
            return None

        result = {
            "underlying_price": underlying_price,
            "expirations": expirations,
            "ticker": ticker,
        }

        get_db().set(cache_key, result, TTL["options_chain_live"])
        logger.info(
            "Fetched Schwab options for %s: %d expirations, underlying $%.2f",
            ticker,
            len(expirations),
            underlying_price,
        )
        return result

    except Exception as exc:
        logger.error("Failed to parse Schwab options chain response for %s: %s", ticker, exc)
        return None
