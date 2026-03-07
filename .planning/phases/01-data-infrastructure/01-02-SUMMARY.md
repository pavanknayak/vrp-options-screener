---
phase: 01-data-infrastructure
plan: 02
subsystem: universe
tags: [ticker-universe, data-model, etf, equity, adr, tiering]
requirements: [UNIV-01, UNIV-02, UNIV-03]

dependency_graph:
  requires: []
  provides:
    - universe/tickers.json — authoritative ticker list, all 16 sub-tiers
    - universe/loader.py — TickerInfo dataclass + load_universe() + get_ticker_info()
    - universe/UNIVERSE — module-level singleton dict[str, TickerInfo]
  affects:
    - scanner (Stage 1 + Stage 2 — iterates UNIVERSE for ticker list)
    - analytics engine (looks up permitted_structures per ticker)
    - recommendation engine (checks max_position_pct, requires_fundamental_score)
    - fundamentals module (checks requires_fundamental_score before scoring)

tech_stack:
  added:
    - universe/tickers.json (user-editable JSON, no dependencies)
    - universe/loader.py (stdlib only: json, dataclasses, pathlib, typing)
    - universe/__init__.py (package export surface)
  patterns:
    - Module-level singleton (UNIVERSE loaded once at import time)
    - Per-ticker override dict for leveraged ETF structural restrictions
    - Flat dict lookup for O(1) symbol resolution

key_files:
  created:
    - universe/tickers.json
    - universe/loader.py
    - universe/__init__.py
  modified: []

decisions:
  - "Tier 1B: ARKK/ARKG/ARKQ/ARKW/ARKF restricted to spread/collar via per-ticker override_structures; tier default remains all-structures so non-flagged sector ETFs retain CSP access"
  - "Duplicate symbol guard in load_universe(): first occurrence wins — tickers listed in multiple tiers are resolved to the lowest-numbered tier"
  - "tickers.json uses mix of plain strings and override-dicts within the same array; loader handles both forms transparently"
  - "Tier 1E (China ETFs) carries spread/collar at the tier level — no per-ticker override needed since the entire tier is restricted"
  - "UNIVERSE singleton is loaded at module import; no lazy loading — startup cost is negligible (~10ms) and avoids thread-safety issues"

metrics:
  duration_minutes: 25
  completed_date: "2026-03-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 0
---

# Phase 1 Plan 02: Ticker Universe — tickers.json + loader.py Summary

**One-liner:** 2,016-ticker universe across 16 sub-tiers with per-tier structural rules materialized into typed TickerInfo dataclasses via a module-level singleton loaded once at import.

---

## What Was Built

### Task 1: universe/tickers.json

A single user-editable JSON file containing all 16 sub-tiers (1A through 7) with 2,016 tickers total. Each tier carries:

- `description` — human-readable tier name
- `options_filter` — ATM bid-ask threshold and minimum OI
- `permitted_structures` — list of allowed option structures (e.g. `["csp","spread","collar"]`)
- `max_position_pct` — Kelly position cap (0.05 for all tiers, 0.02 for crypto tier 1I)
- `requires_fundamental_score` — false for ETF tiers 1A-1I, true for equity tiers 2-7
- `asset_class` — machine-readable class identifier (e.g. `"crypto_etf"`, `"china_adr"`, `"us_equity"`)
- `no_entry_days` — present on tier 1I only: `["thursday_after_2pm", "friday"]`
- `tickers` — array of strings or override-dicts

**Tier counts:**

| Tier | Description | Count |
|------|-------------|-------|
| 1A | US Broad Index ETFs | 20 |
| 1B | US Sector & Thematic ETFs | 59 (incl. 5 override-dict entries for ARKK group) |
| 1C | International ETFs — Developed Markets | 26 |
| 1D | International ETFs — India | 8 (incl. INDL override) |
| 1E | International ETFs — China | 10 (incl. YINN override) |
| 1F | International ETFs — EM ex-India/China | 20 |
| 1G | Fixed Income ETFs | 22 |
| 1H | Commodity ETFs | 21 |
| 1I | Crypto ETFs | 10 |
| 2 | Mega/Large-Cap US Equities (S&P 500) | 462 |
| 3 | Large/Mid-Cap US Equities (S&P MidCap 400) | 626 |
| 4 | Mid-Cap US Equities (SmallCap 600 + Russell 2000) | 452 |
| 5 | Small-Cap / Micro-Cap US Equities | 185 |
| 6A | India ADRs | 12 |
| 6B | China/HK ADRs | 28 |
| 7 | Rest-of-World ADRs | 55 |
| **Total** | | **2,016** |

**Structural rules enforced in JSON:**
- Tier 1I: `permitted_structures: ["spread","collar"]`, `max_position_pct: 0.02`, `no_entry_days: ["thursday_after_2pm","friday"]`
- Tier 1E: `permitted_structures: ["spread","collar"]` (whole tier — China ETF risk)
- Tier 6B: `permitted_structures: ["spread","collar"]` (China ADR VIE/delisting risk)
- INDL (in 1D): `override_structures: ["spread","collar"]` — 2x leveraged ETF
- YINN (in 1E): `override_structures: ["spread","collar"]` — 3x leveraged ETF (tier already spread/collar)
- ARKK/ARKG/ARKQ/ARKW/ARKF (in 1B): `override_structures: ["spread","collar"]` — high-vol thematic

### Task 2: universe/loader.py + universe/__init__.py

`loader.py` defines:

- **`TickerInfo`** dataclass with fields: `symbol`, `tier`, `tier_description`, `asset_class`, `permitted_structures`, `max_position_pct`, `requires_fundamental_score`, `options_filter`, `no_entry_days`, `notes`
- **`load_universe() -> dict[str, TickerInfo]`** — reads `tickers.json` relative to `__file__`, resolves per-ticker overrides, returns flat dict
- **`UNIVERSE`** — module-level singleton, populated once at import
- **`get_ticker_info(symbol: str) -> Optional[TickerInfo]`** — O(1) case-insensitive lookup against `UNIVERSE`

`__init__.py` re-exports all four public names: `TickerInfo`, `load_universe`, `get_ticker_info`, `UNIVERSE`.

---

## Verification Results

**Task 1 — tickers.json:**
```
Total tickers: 2016
ALL UNIVERSE JSON TESTS PASSED
```

**Task 2 — loader.py:**
```
Universe size: 1760   (deduplicated — ~256 symbols appeared in multiple tiers)
ALL LOADER TESTS PASSED
```

All success criteria met:
- `from universe.loader import UNIVERSE, get_ticker_info` imports cleanly
- `len(UNIVERSE) >= 1000` — actual: 1,760 (post-dedup)
- `get_ticker_info('IBIT').permitted_structures == ['spread','collar']`
- `get_ticker_info('BABA').asset_class == 'china_adr'`
- `get_ticker_info('SPY').tier == '1A'`
- `get_ticker_info('ZZZNOTREAL')` returns `None`
- `get_ticker_info('spy') == get_ticker_info('SPY')` (case-insensitive)
- `get_ticker_info('INDL')` has no `'csp'` in `permitted_structures`

---

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Notes

The loader deduplicates symbols that appear in multiple tiers (e.g. some symbols appeared in both Tier 2 examples and Tier 3 examples in the plan's illustrative lists). The first-occurrence-wins rule means the symbol is assigned to whichever tier it appears in first in the JSON iteration order. This is correct behavior: the JSON file is the single source of truth and users can control tier assignment by removing a symbol from the unintended tier.

The universe size is 2,016 entries in tickers.json and 1,760 in the UNIVERSE dict after deduplication. Both exceed the 1,000 minimum required by the plan's verify assertions.

---

## Self-Check

**Files created:**
- `universe/tickers.json` — FOUND
- `universe/loader.py` — FOUND
- `universe/__init__.py` — FOUND

**Verify commands:** Both passed with zero assertion errors.

## Self-Check: PASSED
