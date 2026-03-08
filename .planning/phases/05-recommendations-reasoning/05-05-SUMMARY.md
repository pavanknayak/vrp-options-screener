---
phase: 05-recommendations-reasoning
plan: "05"
subsystem: recommendations
tags: [orchestrator, engine, pipeline, recommendation, entry-point]
dependency_graph:
  requires:
    - 05-01  # evaluate_gonogo()
    - 05-02  # select_structure(), select_strikes()
    - 05-03  # compute_pnl_scenarios(), compute_kelly_size()
    - 05-04  # build_recommendation_card()
  provides:
    - run_recommendation() — single public entry point for Phase 5 and Stage 2 scanner
  affects:
    - scanner/stage2.py — calls run_recommendation() after run_analytics()
tech_stack:
  added: []
  patterns:
    - Never-raise orchestrator pattern (all exceptions caught, returned as error dict)
    - Lazy imports inside try block to isolate import errors
    - analytics_result copy-on-modify (setdefault asset_class without mutating caller)
    - dataclasses.replace() for immutable PnLResult update with Kelly values
key_files:
  created:
    - recommendations/engine.py
  modified: []
decisions:
  - run_recommendation() runs select_structure() and select_strikes() BEFORE evaluate_gonogo() so HARD-08/HARD-09 have a proposed_structure to check and HARD-03 has slippage_adj_ev
  - net_credit (per-share dollars from compute_pnl_scenarios) used as slippage_adj_ev passed to gonogo HARD-03
  - build_recommendation_card() is always called even when gonogo fails — UI needs partial card to display failure reason
metrics:
  duration_minutes: 2
  completed_date: "2026-03-08"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 5 Plan 05: Recommendations Orchestrator Engine Summary

**One-liner:** `run_recommendation()` wires gonogo, structures, P&L, and card into one never-raising entry point with correct pipeline ordering for HARD-03/HARD-08/HARD-09 dependency resolution.

## What Was Built

`recommendations/engine.py` implements `run_recommendation()`, the single public function that Stage 2 scanner and the UI call to receive a complete recommendation result for a given ticker.

### Pipeline Order

The function chains the four sub-modules in a specific dependency order that resolves inter-step data dependencies:

1. `select_structure()` — must run first so go/no-go HARD-08 (China ADR ban) and HARD-09 (Crypto ETF ban) have a `proposed_structure` to check
2. `select_strikes()` — selects expiration and put/call strikes from the options chain
3. `compute_pnl_scenarios()` — computes net credit (used as `slippage_adj_ev` for go/no-go HARD-03)
4. `evaluate_gonogo()` — runs the 21-point matrix with slippage_adj_ev now available
5. `compute_kelly_size()` — fractional Kelly sizing with regime/VoV/GEX multipliers
6. `build_recommendation_card()` — always called (even on go/no-go failure) for UI display

### Return Shape

The function returns a flat dict with 34 top-level keys covering:
- Pass/fail status (`passed`, `error`)
- Go/no-go summary and full check list
- Trade parameters (structure, strikes, DTE, FOMC status)
- Trade economics (net credit, max loss, breakeven, profit target, hard stop, roll trigger)
- Four P&L scenarios as plain dicts (JSON-serialisable)
- Kelly sizing
- Three narrative paragraphs and broker-ready order text
- Full `card` key containing `RecommendationCard` as a plain dict

### Error Handling

Any unhandled exception in the pipeline is caught by the outer `try/except` and returned as:
```python
{"ticker": ticker, "error": str(exc), "passed": False, <all other keys>: None}
```
The function never raises.

## Decisions Made

- `analytics_result` is shallow-copied (`dict(analytics_result)`) before calling `setdefault("asset_class", ...)` to avoid mutating the caller's dict — Stage 2 scanner may reuse the analytics result
- `net_credit` (per-share slippage-adjusted credit from `compute_pnl_scenarios`) serves as the `slippage_adj_ev` passed to `evaluate_gonogo` for the HARD-03 check
- Imports are deferred inside the `try` block so import-time errors in sub-modules are caught and returned as error dicts rather than crashing the caller

## Deviations from Plan

None — plan executed exactly as written.

## Verification

Both verification tests passed:
- Passing candidate (Normal regime, AAPL): `passed=True`, all 34 fields populated, 4 scenarios, non-empty narratives and order text
- Crisis regime candidate: `passed=False`, `error=None`, `gonogo_summary` contains "HARD-05"

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `recommendations/engine.py` | FOUND |
| Commit `20cef27` | FOUND |
