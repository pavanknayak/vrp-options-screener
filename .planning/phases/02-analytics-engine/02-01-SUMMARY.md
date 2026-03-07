---
phase: 02-analytics-engine
plan: "01"
subsystem: analytics
tags: [realized-vol, yang-zhang, parkinson, garman-klass, rv-estimators]
completed: 2026-03-07

dependency_graph:
  requires:
    - data/yfinance_fetcher.py  # ohlc DataFrame source (252-row OHLCV)
  provides:
    - analytics/realized_vol.py  # yang_zhang_vol, parkinson_vol, garman_klass_vol, realized_vol_suite
  affects:
    - analytics/forecasters.py  # HAR-RV (plan 02-02) consumes yz_series_21d
    - vrp/signal_engine.py      # VRP signal engine (plan 02-05) consumes realized_vol_suite output

tech_stack:
  added: []
  patterns:
    - Rolling window variance/mean via pd.Series.rolling() for all three RV estimators
    - Clip-to-floor pattern (.clip(lower=0.001)) preventing log(0) in downstream consumers
    - Flat dict output from suite function for easy downstream key access

key_files:
  created:
    - analytics/__init__.py
    - analytics/realized_vol.py
  modified: []

decisions:
  - Yang-Zhang k constant uses exact PRD §6.2 formula: 0.34/(1.34+(window+1)/(window-1))
  - estimator_divergence threshold set at 0.03 (3 vol pts) per PRD spec for overnight_dominated flag
  - realized_vol_suite returns yz_series_21d full pd.Series (not just scalar) to avoid recomputation in HAR-RV

metrics:
  duration_minutes: 8
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 2 Plan 1: Realized Volatility Estimator Suite Summary

**One-liner:** Yang-Zhang, Parkinson, and Garman-Klass RV estimators over 10d/21d/30d/60d windows with multi-window suite function, IV-to-trading-day converter, and overnight-gap divergence detector.

---

## What Was Built

`analytics/realized_vol.py` — six public functions implementing the realized volatility foundation for the entire VRP analytics engine:

- `yang_zhang_vol(ohlc, window=21)` — Primary RV estimator (~14x efficiency). Combines Rogers-Satchell intraday variance, overnight return variance, and intraday return variance via k-weighted combination. Exact PRD §6.2 formula.
- `parkinson_vol(ohlc, window=21)` — High-low range estimator (~5x efficiency). Context display and divergence detection.
- `garman_klass_vol(ohlc, window=21)` — Extended Parkinson with open/close (~8x efficiency). Context display and divergence detection.
- `realized_vol_suite(ohlc)` — Runs all 3 estimators × 4 windows = 12 scalar floats, plus `yz_series_21d` full pd.Series for HAR-RV downstream consumption.
- `iv_to_trading_day(iv_calendar)` — Converts 365-day calendar IV to 252 trading-day basis via `sqrt(365/252)`.
- `estimator_divergence(yz, pk, gk)` — Flags large overnight gaps (>3 vol pts gap between YZ and range-only estimators).

`analytics/__init__.py` — Package marker with module docstring.

---

## Verification Results

All three automated verify scripts passed:

**Task 1 (three estimators):**
```
YZ=0.1720  PK=0.0978  GK=0.1122
Task 1 PASSED
```

**Task 2 (suite + helpers):**
```
Suite keys OK: ['yz_10d', 'yz_21d', 'yz_30d', 'yz_60d', 'pk_10d', 'pk_21d', 'pk_30d', 'pk_60d', 'gk_10d', 'gk_21d', 'gk_30d', 'gk_60d', 'yz_series_21d']
iv_to_trading_day(0.20) = 0.2407
Task 2 PASSED
```

**Overall export verification:**
```
yang_zhang_vol : ['ohlc', 'window']
parkinson_vol : ['ohlc', 'window']
garman_klass_vol : ['ohlc', 'window']
realized_vol_suite : ['ohlc']
iv_to_trading_day : ['iv_calendar']
estimator_divergence : ['yz', 'pk', 'gk']
ALL EXPORTS OK
```

---

## Decisions Made

1. **Yang-Zhang k constant** — Exact PRD §6.2 formula used: `k = 0.34 / (1.34 + (window+1)/(window-1))`. This is window-dependent and recalculated per call.

2. **Minimum clip at 0.001** — Applied on the output Series of all three estimators. Prevents `log(0)` and division-by-zero in downstream VRP ratio computation.

3. **yz_series_21d in suite** — Full pd.Series returned (not just `.iloc[-1]`) so HAR-RV forecasters in plan 02-02 can run rolling OLS on historical RV without recomputing the estimator.

4. **estimator_divergence threshold** — 0.03 (3 vol points) per PRD spec. Checks `abs(yz_pk_gap) > 0.03 OR abs(yz_gk_gap) > 0.03`.

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Self-Check

Files exist:
- analytics/__init__.py: FOUND
- analytics/realized_vol.py: FOUND

All six functions export with correct signatures: PASSED
All three automated verify scripts: PASSED
