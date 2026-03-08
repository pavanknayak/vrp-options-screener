---
phase: 05-recommendations-reasoning
plan: "01"
subsystem: recommendations
tags: [go-nogo, evaluation-matrix, disqualifiers, hard-filters, soft-filters]
dependency_graph:
  requires: [analytics/engine.py, fundamentals/engine.py, universe/loader.py]
  provides: [recommendations/gonogo.py, recommendations/__init__.py]
  affects: [recommendations/engine.py (Phase 5 downstream plans)]
tech_stack:
  added: []
  patterns: [dataclass result object, fail-fast ordered evaluation, try/except safety wrapper]
key_files:
  created:
    - recommendations/__init__.py
    - recommendations/gonogo.py
  modified: []
decisions:
  - "Evaluation stops at first failure — fail-fast approach avoids wasted downstream work"
  - "Fundamentals error key causes HARD-06 and SOFT-08 to pass through with a warning rather than blocking"
  - "Altman distress gate (HARD-06) requires both is_distress=True AND requires_fundamental_score=True to reject"
metrics:
  duration: "1 minute"
  completed: "2026-03-08"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 5 Plan 01: Go/No-Go 21-Point Evaluation Matrix Summary

## Status: COMPLETE

## One-liner

21-criterion go/no-go matrix with fail-fast evaluation — 9 hard disqualifiers then 12 soft filters — for Stage 2 VRP candidates before recommendation assembly.

## What was built

- `recommendations/__init__.py` — package marker with Phase 5 docstring
- `recommendations/gonogo.py` — `GoNoGoResult` dataclass and `evaluate_gonogo()` function

## Key behaviors

- `evaluate_gonogo()` processes all 21 checks in strict priority order; stops at first failure and returns the failing criterion ID with a human-readable reason
- `GoNoGoResult` dataclass carries: `passed`, `failed_criterion`, `failed_reason`, `permitted_structures`, `checks`
- Hard disqualifiers (HARD-01 through HARD-09): VRP percentile < 40th, earnings in window, EV <= 0, VoV Z > 2.5, Crisis regime, Altman distress (equity tiers only), jump% > 50%, China ADR CSP ban, Crypto ETF CSP ban
- Soft filters (SOFT-01 through SOFT-12): tier-based composite score floors, IVP minimum, VRP persistence 30d, fundamental gate, GEX severely negative, term structure severely inverted, VoV moderate check in High/Crisis, PCR OI extreme bearish
- A clean candidate that passes all 21 checks returns a 21-item `checks` list, all `passed=True`
- Fundamentals `error` key causes HARD-06 and SOFT-08 to pass through with a `warnings.warn()` and logger warning rather than blocking
- Entire function body wrapped in outer try/except; any unexpected exception returns `INTERNAL_ERROR` criterion

## Exports

- `GoNoGoResult` — dataclass with 5 fields
- `evaluate_gonogo(analytics_result, fundamentals_result, ticker_info, proposed_structure, slippage_adj_ev) -> GoNoGoResult`

## Verification

All plan assertions passed:
- Minimal passing candidate: `result.passed == True`, 21-check list with all IDs present
- HARD-01: `vrp_pctile=0.30` → `failed_criterion='HARD-01'`
- HARD-03: `slippage_adj_ev=0.0` → `failed_criterion='HARD-03'`
- HARD-05: `regime_label='Crisis'` → `failed_criterion='HARD-05'`
- HARD-08: `asset_class='china_adr'`, `proposed_structure='csp'` → `failed_criterion='HARD-08'`

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- recommendations/__init__.py: FOUND
- recommendations/gonogo.py: FOUND
- Task 1 commit: c5e7312
- Task 2 commit: 343119e
- All plan assertions: PASSED
- 21 check IDs verified: HARD-01..09 + SOFT-01..12
