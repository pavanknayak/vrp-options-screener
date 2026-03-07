---
phase: 02-analytics-engine
plan: "06"
subsystem: analytics
tags: [composite-score, vrp-scoring, orchestrator, analytics-engine, run-analytics]
completed: 2026-03-07

dependency_graph:
  requires:
    - analytics/vrp_engine.py    # compute_vrp_signals(), vrp_timing_signal()
    - analytics/iv_surface.py    # compute_vrp()
    - analytics/regime.py        # detect_regime(), vov_signal()
    - analytics/microstructure.py # compute_gex(), compute_pcr()
    - analytics/forecasters.py   # bipower_variation(), jump_stats()
    - analytics/realized_vol.py  # iv_to_trading_day(), realized_vol_suite()
  provides:
    - analytics/composite_score.py  # composite_vrp_score(), normalize_signal()
    - analytics/engine.py           # run_analytics()
  affects:
    - scanner/phase3_scanner.py  # Phase 3 calls run_analytics() per ticker

tech_stack:
  added: []
  patterns:
    - Weighted-sum normalization: normalize_signal() clips to [min,max] then scales to [0,1]
    - Tiered scoring: discrete thresholds (_gex_support_score) for non-linear dealer signals
    - Multiplicative penalty chain: (1 - event_penalty) * (1 - jump_penalty) * (1 - vov_penalty)
    - VoV early-exit disqualifier: vov_z > 2.5 returns 0.0 before any computation
    - Try/except isolation per pipeline step: partial failures return structured error dicts
    - Fallback synthesis: flat history series when iv30_history / vrp_history not supplied

key_files:
  created:
    - analytics/composite_score.py
    - analytics/engine.py
  modified: []

decisions:
  - vov_z key confirmed from vrp_engine.py line 157 (signals['vov_z']) — not vov_zscore
  - VoV disqualifier placed before weighted-sum computation for fast exit (avoids unnecessary work)
  - Synthetic flat histories (30 elements) synthesised in engine.py when caller passes None — prevents crashes while signalling low historical context to downstream percentile computations
  - term_slope_pctile defaults to 0.5 (neutral) when absent — not computed in Phase 2 (requires historical term slope series, deferred to Phase 5)

metrics:
  duration_minutes: 12
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 2 Plan 6: Composite Score and Analytics Orchestrator Summary

**One-liner:** 12-signal weighted VRP composite score (0-100) with multiplicative event/jump/VoV penalties plus a single run_analytics() orchestrator that wires all six analytics modules into one dict-returning call for the Phase 3 scanner.

---

## What Was Built

### `analytics/composite_score.py`

- `normalize_signal(value, min_val, max_val)` — Clips value to [min_val, max_val] then linearly scales to [0.0, 1.0]. Returns 0.0 when max_val <= min_val.
- `_gex_support_score(gex_bn)` — Converts dealer GEX in billions to a tiered {0.0, 0.4, 0.7, 1.0} score. Positive GEX suppresses realized vol, supporting premium collection.
- `_WEIGHTS` — Module-level constant list of 12 weights summing to exactly 1.0. Module-level `assert` fires on import if the sum drifts (catches editing mistakes immediately).
- `composite_vrp_score(signals, has_earnings_in_window, near_term_earnings)` — Full PRD §6.11 formula:
  1. Fast VoV disqualifier: returns 0.0 immediately if `vov_z > 2.5`.
  2. 12-signal weighted sum (raw in [0, 1], scaled to [0, 100]).
  3. Multiplicative penalties: event (30%/15%), jump (20%/10%), VoV-elevated (25%).

Signal weights (PRD §6.11):
| Weight | Signal | Economic meaning |
|--------|--------|-----------------|
| 0.18 | vrp_pctile | Magnitude vs 252-day history |
| 0.12 | vrp_persist_30d | Reliability (days VRP > 0) |
| 0.12 | vrp_zscore | Statistical significance |
| 0.10 | em_ratio | Implied vs realized expected move |
| 0.10 | excess_vrp | Idiosyncratic premium above beta-adj index |
| 0.08 | ivp | IV elevation percentile |
| 0.08 | skew_25d | Hedging demand (put-call skew) |
| 0.07 | term_slope_pctile | Term structure support |
| 0.05 | 1 - jump_pct | Jump cleanliness (inverted) |
| 0.04 | pcr_oi | Put-buying demand |
| 0.03 | gex_billions | Dealer positioning (tiered) |
| 0.03 | 1 - vov_z/3 | IV stability (inverted VoV) |

### `analytics/engine.py`

- `run_analytics(ticker, chain, ohlc, r, vix, ...)` — Four-step pipeline:
  1. `detect_regime(vix, vvix=vvix)` — Regime label and position-size multiplier.
  2. `compute_vrp(chain, ohlc, r)` — IV surface + ensemble RV forecast + VRP scalar.
  3. `compute_vrp_signals(...)` — All 12+ signals including GEX, PCR, VoV, skew, jump.
  4. `composite_vrp_score(signals, ...)` — Final 0-100 score.

Each step is wrapped in `try/except`; a failure returns `{'ticker': ..., 'error': 'step_failed: reason'}` immediately — the caller never sees an exception.

Convenience flat keys exposed at top level for scanner (avoids nested `.signals['key']` access):
`vrp_pctile`, `ivp`, `gex_billions`, `pcr_oi`, `jump_pct`, `regime_label`, `regime_mult`, `timing_action`, `timing_reason`

---

## Verification Results

**Task 1 (composite_score.py):**
```
min_score=2.40  max_score=100.00
earnings_penalty: 100.00 -> 70.00
Task 1 PASSED
```
- All-minimum signals produce score < 5.0 (2.40 actual)
- All-maximum signals produce score > 95.0 (100.00 actual)
- 30% earnings penalty confirmed: 100.0 -> 70.0
- VoV Z = 3.0 returns 0.0 (DISQUALIFY confirmed)
- _WEIGHTS module assertion fires on import with no error

**Task 2 (engine.py):**
```
IV30=0.2195  VRP=0.1079  Score=55.7
Regime=Normal  Timing=ENTER AT OPPORTUNITY
Error path: Insufficient expirations for interpolation
Task 2 PASSED — full analytics pipeline wired end-to-end
```
- All required top-level keys present
- Composite score in [0, 100]
- VIX=18.0 correctly maps to regime_label='Normal'
- Empty chain returns structured error dict (not exception)

**Phase 2 final import check:**
```
ALL PHASE 2 ANALYTICS MODULES IMPORT CLEANLY
```
All 8 analytics modules (realized_vol, forecasters, iv_surface, regime, microstructure, vrp_engine, composite_score, engine) import cleanly from a fresh Python process.

---

## Decisions Made

1. **vov_z key confirmed** — Read vrp_engine.py line 157 before implementing. The key is `vov_z` (not `vov_zscore` or `vov_30d`). composite_score.py uses `s.get('vov_z', 0.0)` throughout.

2. **VoV early-exit placement** — The `if vov_z > 2.5: return 0.0` check is placed at the top of composite_vrp_score, before the 12-signal sum, to avoid unnecessary arithmetic on disqualified tickers.

3. **Synthetic history fallback in engine.py** — When `iv30_history` or `vrp_history` is None, engine.py synthesises a 30-element flat series from the current scalar values. This allows run_analytics() to run in scanner mode (no stored history) while still producing percentile-like outputs (all equal → 50th pctile from percentileofscore).

4. **term_slope_pctile defaults to 0.5** — This signal requires a historical time series of term slopes, which is not computed in Phase 2. The signal defaults to neutral (0.5) via `s.get('term_slope_pctile', 0.5)`. Full implementation deferred to Phase 5 (UI/persistence layer adds rolling storage).

---

## Deviations from Plan

None — plan executed exactly as written. The vov_z key name was verified from source before implementation, confirming the plan's guidance was correct.

---

## Self-Check

Files exist:
- analytics/composite_score.py: FOUND
- analytics/engine.py: FOUND

Task 1 automated verify: PASSED
Task 2 automated verify: PASSED
Phase 2 final import check: PASSED
All 8 Phase 2 analytics modules import cleanly: CONFIRMED
