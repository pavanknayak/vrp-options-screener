---
phase: 01-data-infrastructure
plan: 01
subsystem: cache, data
tags: [sqlite, ttl-cache, fomc, static-data, thread-safe]
dependency_graph:
  requires: []
  provides: [cache/db.py, data/fomc.py]
  affects: [data fetchers in plans 03 and 04, recommendation engine in phase 5]
tech_stack:
  added: []
  patterns: [sqlite3 WAL mode, pickle serialization, threading.Lock, functools.lru_cache singleton]
key_files:
  created:
    - cache/__init__.py
    - cache/db.py
    - data/__init__.py
    - data/fomc.py
  modified: []
decisions:
  - "Raw sqlite3 used (not SQLAlchemy) — key-value store is simple enough; avoids ORM overhead"
  - "threading.Lock wraps all writes; reads are lock-free (WAL mode allows concurrent readers)"
  - "get_db() singleton via lru_cache(maxsize=1) — one CacheDB per process"
  - "fomc_context() priority order: AVOID > PRIORITY_ENTRY > FOMC_IN_WINDOW > CLEAR (separate passes)"
metrics:
  duration_minutes: 10
  completed_date: "2026-03-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 0
---

# Phase 1 Plan 01: SQLite TTL Cache and FOMC Calendar Summary

**One-liner:** Thread-safe SQLite TTL cache with pickle serialization and singleton accessor, plus static FOMC calendar with priority-ordered context helper.

---

## What Was Built

### Task 1 — SQLite TTL Cache Layer (`cache/`)

`cache/db.py` implements `CacheDB`, a thread-safe SQLite-backed key-value store where every entry carries its own TTL.

Key design points:
- WAL mode (`PRAGMA journal_mode=WAL`) enables concurrent readers with a single writer.
- All write operations (`set`, `delete`, `purge_expired`) acquire a `threading.Lock`; reads are lock-free.
- Values are serialized with `pickle.dumps` / `pickle.loads`; any Python object can be stored.
- `get()` returns `None` for missing keys AND for entries where `time.time() - fetched_at > ttl_seconds`.
- `purge_expired()` bulk-deletes stale rows and returns the count removed.
- `exists()` delegates to `get()` (truthy non-None result = key live).
- `get_db()` is a `functools.lru_cache(maxsize=1)` singleton returning the default `vrp_cache.db` instance.
- `TTL` dict defines canonical TTL values for all cache categories.

DB path resolves to `{project_root}/vrp_cache.db` — created on first use by a fetcher, never during import or testing.

### Task 2 — Static FOMC Calendar (`data/`)

`data/fomc.py` contains:
- `FOMC_DATES` — 16 announcement dates (8 per year) for 2025 and 2026; pure stdlib, zero API calls.
- `fomc_context(today, expiration_date) -> (status, message)` — checks dates in priority order across three separate passes:
  1. **AVOID**: FOMC is 1–2 calendar days away — high event risk.
  2. **PRIORITY_ENTRY**: FOMC concluded exactly yesterday — vol crush window.
  3. **FOMC_IN_WINDOW**: Any FOMC date falls strictly between today and expiration.
  4. **CLEAR** (default): no relevant FOMC event.

---

## Verification Results

### Task 1 — Cache

```
ALL CACHE TESTS PASSED
```

Assertions verified:
- `set` + `get` roundtrip for a complex dict value.
- Expired entry (`ttl_seconds=0`, sleep 10 ms) returns `None`.
- Missing key returns `None`.
- `exists()` returns `True` for live key, `False` for missing key.
- `TTL['ohlcv_history'] == 3600`, `TTL['options_chain_live'] == 900`.

### Task 2 — FOMC

```
ALL FOMC TESTS PASSED
```

Assertions verified:
- `len(FOMC_DATES) >= 14` (actual: 16).
- `'2026-03-18'` present in list.
- `fomc_context` returns `AVOID` for the day before a known FOMC date.
- `fomc_context` returns `CLEAR` for April 15 – May 1 2025 (no FOMC in that window).

### Clean import check

```
All imports clean.
vrp_cache.db NOT created. OK.
```

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Self-Check: PASSED

- `cache/__init__.py` — exists
- `cache/db.py` — exists
- `data/__init__.py` — exists
- `data/fomc.py` — exists
- `vrp_cache.db` — correctly absent (created on first real use only)
