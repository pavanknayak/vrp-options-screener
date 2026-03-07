---
phase: 01-data-infrastructure
plan: 03
subsystem: data
tags: [yfinance, fred, ohlcv, vix, risk-free-rate, ttl-cache, options-summary]
dependency_graph:
  requires: [cache/db.py (plan 01-01)]
  provides: [data/yfinance_fetcher.py, data/fred_fetcher.py]
  affects: [Stage 1 bulk scan pipeline, BSM pricing (phase 3), regime detection (phase 4)]
tech_stack:
  added: [yfinance==1.2.0, fredapi==0.5.2]
  patterns: [cache-aside pattern, try/except sentinel returns, logging.getLogger(__name__)]
key_files:
  created:
    - data/yfinance_fetcher.py
    - data/fred_fetcher.py
  modified: []
decisions:
  - "fetch_earnings_date caches a 'NONE' sentinel string when no upcoming date found — prevents repeated yfinance misses within the TTL window"
  - "fetch_yf_options_summary caches empty dict on error — callers can test 'if result' without needing None checks"
  - "FRED_API_KEY read at module level (not inside each function) — single assignment, no repeated env lookups"
  - "get_risk_free_rate default of 0.05 chosen to match typical 5% T-bill baseline used in project PRD"
metrics:
  duration_minutes: 12
  completed_date: "2026-03-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 1 Plan 03: yfinance and FRED Fetchers Summary

**One-liner:** Cache-aware yfinance OHLCV/earnings/options fetchers and FRED risk-free rate/VIX history fetchers, all returning typed sentinels on error without propagating exceptions.

---

## What Was Built

### Task 1 — yfinance Fetcher (`data/yfinance_fetcher.py`)

Three public functions, all following the same cache-aside pattern (check `get_db().get(key)`, log HIT/MISS, fetch on miss, `get_db().set(key, value, TTL[...])` before returning):

**`fetch_ohlcv(ticker, period_days=252) -> pd.DataFrame`**
- Cache key: `{TICKER}_ohlcv_{today}`; TTL: 3600 s
- Calls `yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=True)`
- Raises `ValueError` internally if fewer than 50 rows returned; the outer `try/except` catches this and returns an empty DataFrame
- Normalises to `['Open','High','Low','Close','Volume']`, drops Dividends and Stock Splits
- Returns the trailing `period_days` rows via `.tail()`

**`fetch_earnings_date(ticker) -> Optional[date]`**
- Cache key: `{TICKER}_earnings_{today}`; TTL: 43200 s
- Reads `yf.Ticker(ticker).calendar`; handles both dict and DataFrame shapes that yfinance may return
- Filters to future dates only (>= today), returns the nearest one or `None`
- Stores the string sentinel `"NONE"` in cache when no upcoming date exists, to avoid repeated misses within the TTL window

**`fetch_yf_options_summary(ticker) -> dict`**
- Cache key: `{TICKER}_yf_options_{today}`; TTL: 1800 s
- Fetches nearest expiration via `tk.options[0]`, resolves ATM strike against `fast_info["last_price"]`
- Returns `{"atm_iv": float, "atm_oi": int, "expiration": str, "bid_ask_pct": float}` or `{}` on any error
- Empty dict is also cached to prevent repeated misses within the TTL window

### Task 2 — FRED Fetcher (`data/fred_fetcher.py`)

`FRED_API_KEY = os.environ.get("FRED_API_KEY")` read once at module level.

**`fetch_fred_rate(series_id="DGS3MO") -> Optional[float]`**
- Cache key: `fred_{series_id}_{today}`; TTL: 21600 s
- Fetches last 30 days of observations, drops NaN, takes `iloc[-1]`, divides by 100 to convert percent to decimal
- Returns `None` (with a warning log) when the API key is absent — does not raise

**`fetch_vix_history(lookback_days=252) -> Optional[pd.Series]`**
- Cache key: `fred_VIXCLS_{today}`; TTL: 21600 s
- Fetches series `"VIXCLS"` for the past `lookback_days` calendar days
- Returns `pd.Series` with DatetimeIndex and float values (NaN dropped), or `None` when no key is set

**`get_risk_free_rate() -> float`**
- Delegates to `fetch_fred_rate("DGS3MO")`
- Returns `0.05` default when result is `None`; logs that the default is being used
- Never raises — guaranteed `float` return

---

## Verification Results

### Task 1 — yfinance Fetcher

```
INFO:data.yfinance_fetcher:[CACHE MISS] ohlcv SPY — fetching yfinance
INFO:data.yfinance_fetcher:[CACHE HIT] ohlcv SPY
INFO:data.yfinance_fetcher:[CACHE MISS] earnings AAPL — fetching yfinance
OHLCV rows: 251
ALL YFINANCE FETCHER TESTS PASSED
```

Assertions verified:
- `fetch_ohlcv('SPY')` returns DataFrame with 251 rows (>= 100 required)
- Columns include Open, High, Low, Close, Volume
- Second call returns cached result (CACHE HIT logged, same row count)
- `fetch_earnings_date('AAPL')` returns `None` or a `date` — no exception

### Task 2 — FRED Fetcher

```
INFO:data.fred_fetcher:[CACHE MISS] fred DGS3MO — fetching FRED API
WARNING:data.fred_fetcher:[WARN] FRED_API_KEY not set — cannot fetch DGS3MO; returning None
INFO:data.fred_fetcher:[INFO] Using default risk-free rate of 0.05 (FRED data unavailable)
Risk-free rate: 0.05
No FRED_API_KEY set - None returned gracefully
ALL FRED FETCHER TESTS PASSED
```

Assertions verified:
- `get_risk_free_rate()` returns `float` in range `[0.0, 0.20]` (returned `0.05` default)
- `fetch_fred_rate()` returns `None` gracefully when `FRED_API_KEY` is absent (no exception raised)

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Sentinel caching for empty results**
- **Found during:** Task 1 implementation review
- **Issue:** `fetch_earnings_date` returning `None` and `fetch_yf_options_summary` returning `{}` would not have been stored in cache, causing repeated yfinance network calls within the TTL window when data is genuinely absent
- **Fix:** `fetch_earnings_date` stores the string `"NONE"` as a sentinel and converts it back to `None` on cache hit; `fetch_yf_options_summary` stores `{}` even on error paths
- **Files modified:** `data/yfinance_fetcher.py`

---

## Self-Check: PASSED

- `data/yfinance_fetcher.py` — exists
- `data/fred_fetcher.py` — exists
- Task 1 automated verification — PASSED (251 OHLCV rows, cache HIT on second call, earnings date or None)
- Task 2 automated verification — PASSED (0.05 default returned, None on missing key, no exceptions)
