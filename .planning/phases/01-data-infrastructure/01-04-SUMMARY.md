---
phase: 01-data-infrastructure
plan: 04
subsystem: data
tags: [schwab, oauth2, options-chain, edgar, xbrl, financials, caching]
dependency_graph:
  requires: [cache/db.py, data/__init__.py]
  provides: [data/schwab_client.py, data/edgar_fetcher.py]
  affects: [phase-2 options screener, phase-4 piotroski/altman scoring]
tech_stack:
  added: []
  patterns:
    - schwab-py easy_client OAuth2 singleton
    - module-level _client guard with try/except ImportError
    - SEC EDGAR XBRL companyfacts REST API (no auth)
    - CIK map bulk-cached 7 days
    - graceful 404 handling for ETF non-filers
key_files:
  created:
    - data/schwab_client.py
    - data/edgar_fetcher.py
  modified: []
decisions:
  - "schwab import guarded at module level with try/except ImportError; app starts cleanly without the library"
  - "get_schwab_client() returns None (not raises) when env vars missing; all callers check for None"
  - "EDGAR companyfacts URL requires CIK prefix (CIK0000320193 not 0000320193) — auto-fixed during execution"
  - "SPY (ETF) returns HTTP 404 from EDGAR companyfacts endpoint; handled as graceful info-level log, returns {}"
  - "CIK map fetched once from /files/company_tickers.json and cached 7 days — avoids per-ticker lookup overhead"
metrics:
  duration_minutes: 8
  completed_date: "2026-03-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 1 Plan 04: Schwab OAuth Client and EDGAR Financials Fetcher Summary

**One-liner:** Schwab OAuth2 singleton with graceful no-credentials degradation, plus SEC EDGAR XBRL financials fetcher with CIK map caching, 404 ETF handling, and hour-granularity options chain caching.

---

## What Was Built

### Task 1 — Schwab OAuth Client (`data/schwab_client.py`)

`data/schwab_client.py` provides the authenticated Schwab market data client and a live options chain fetcher.

Key design points:

- `schwab` import is guarded at module top with `try/except ImportError`; if `schwab-py` is absent the module still imports cleanly and all functions return `None` or graceful status dicts.
- `get_schwab_client()` reads `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` from environment. If either is missing it logs a warning and returns `None` — no exception propagated.
- Client is cached in `_client` module-level singleton; `easy_client()` is called only once per process.
- `schwab_connection_status()` always returns `{"connected": bool, "message": str, "token_path": str}` — safe to call at any time regardless of credentials.
- `fetch_options_chain(ticker, min_dte=25, max_dte=55)` uses hour-granularity cache key (`%Y%m%d_%H`) with TTL 900 s. Returns `None` immediately when client is not configured.
- Rate limiting: module-level `_last_request_time` enforces 0.6 s minimum gap. On HTTP 429: sleeps 30 s and retries once.
- Response parsing converts `callExpDateMap` / `putExpDateMap` into per-expiration `{"date", "dte", "calls": DataFrame, "puts": DataFrame}` dicts.

### Task 2 — SEC EDGAR XBRL Fetcher (`data/edgar_fetcher.py`)

`data/edgar_fetcher.py` fetches audited annual financials from the SEC's public XBRL API.

Key design points:

- `_get_cik_map()` downloads `https://www.sec.gov/files/company_tickers.json` (10 412 tickers) and caches it for 7 days as `edgar_cik_map_global`. Builds `{TICKER: "0000320193"}` zero-padded map.
- `fetch_edgar_financials(ticker)` looks up CIK, fetches `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`, and extracts the most-recent 10-K value for each financial concept via `_latest_annual_value()`.
- Graceful ETF handling: tickers present in the CIK map but without XBRL data (e.g., SPY) return HTTP 404 from the companyfacts endpoint; these are handled as `logger.info` and `return {}`.
- Revenue tries two GAAP concepts in order: `Revenues` then `RevenueFromContractWithCustomerExcludingAssessedTax`.
- `total_debt` sums `LongTermDebt` and `ShortTermBorrowings` (uses whichever are available).
- `fcf = cfo - abs(PaymentsToAcquirePropertyPlantAndEquipment)`.
- Rate limiting: `time.sleep(0.15)` before each EDGAR request (~6.7 req/s, within 10 req/s limit).
- Results cached at daily granularity (`{TICKER}_edgar_{YYYY-MM-DD}`) with TTL 86400 s.
- All exceptions caught; `return {}` on any failure.

---

## Verification Results

### Task 1 — Schwab client

```
Schwab status: {'connected': False, 'message': 'Not connected — schwab-py library not installed', 'token_path': '...schwab_token.json'}
No Schwab credentials - returns None gracefully
ALL SCHWAB CLIENT TESTS PASSED
```

- `schwab_connection_status()` returns well-formed dict with `connected` and `message` keys.
- `get_schwab_client()` returns `None` without env vars.
- `fetch_options_chain('SPY')` returns `None` when unconfigured.

### Task 2 — EDGAR fetcher

```
INFO:data.edgar_fetcher:EDGAR CIK map loaded: 10412 tickers
INFO:data.edgar_fetcher:Ticker SPY (CIK 0000884394) has no EDGAR XBRL companyfacts (ETF or non-filer)
INFO:data.edgar_fetcher:Fetched EDGAR financials for AAPL (CIK 0000320193): revenue=265595000000.0, net_income=112010000000.0
SPY EDGAR result: {}
AAPL EDGAR keys: ['ticker', 'cik', 'revenue', 'net_income', 'cfo', 'fcf', 'total_debt', 'total_assets', 'book_value', 'interest_expense', 'shares_outstanding', 'fiscal_year_end']
AAPL revenue: 265595000000.0
ALL EDGAR FETCHER TESTS PASSED
```

- AAPL revenue $265.6B (well above $1B threshold, matches FY2024 reported figure).
- SPY returns `{}` gracefully (HTTP 404 from EDGAR, handled without ERROR log).
- Second call for AAPL returns identical cached result.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] EDGAR companyfacts URL missing CIK prefix**

- **Found during:** Task 2 verification
- **Issue:** Plan specified `_COMPANY_FACTS_URL = ".../companyfacts/{cik}.json"` but the SEC EDGAR API requires the CIK to be prefixed with the literal string `CIK`, yielding `CIK0000320193` — without this prefix every request returns HTTP 404.
- **Fix:** Changed URL template to `".../companyfacts/CIK{cik}.json"`. Confirmed 200 response for AAPL and correct data returned.
- **Files modified:** `data/edgar_fetcher.py`

**2. [Rule 2 - Missing critical handling] Graceful 404 for ETF non-filers**

- **Found during:** Task 2 verification (SPY, after URL fix)
- **Issue:** SPY exists in the CIK map but has no EDGAR XBRL companyfacts entry; the raw `raise_for_status()` would log a misleading ERROR. The plan says "return {} gracefully" but did not specify 404 pre-check.
- **Fix:** Added explicit `if resp.status_code == 404: logger.info(...); return {}` before `raise_for_status()`. SPY now logs an info message and returns `{}` cleanly.
- **Files modified:** `data/edgar_fetcher.py`

---

## Self-Check: PASSED

- `data/schwab_client.py` — exists
- `data/edgar_fetcher.py` — exists
- Both modules import cleanly with no side effects
- AAPL revenue ($265.6B) > $1B threshold
- SPY returns `{}` without error
- Cache hit verified: second AAPL call returns identical dict
