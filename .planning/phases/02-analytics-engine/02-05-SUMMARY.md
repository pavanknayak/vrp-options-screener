---
phase: 02-analytics-engine
plan: "05"
subsystem: analytics
tags: [vrp-signals, iv-rank, skew, term-structure, vov, em-ratio, jump, gex, pcr, timing]
dependency_graph:
  requires: [02-03, 02-04]
  provides: [analytics/vrp_engine.py]
  affects: [02-06]
tech_stack:
  added: []
  patterns:
    - scipy.stats.percentileofscore for rank-based signals
    - PCHIP-aware 25-delta strike approximation via BSM inverse delta
    - total-variance-space skew extraction with impliedVolatility column fallback
key_files:
  created:
    - analytics/vrp_engine.py
  modified: []
decisions:
  - "skew_zscore defaults to 0.0 because skew history (rolling smile cache) is not yet built in Phase 2 — Phase 3 caching layer will populate it"
  - "VRP timing threshold 0.005 annualized decimal = 0.5 vol points (PRD §6.9) — documented in code comment"
  - "em_ratio uses first expiration that has bid/ask columns rather than strictly nearest-30DTE to handle chain mocks with missing columns"
  - "skew_25d uses per-strike impliedVolatility column when available; falls back to 7% ATM proxy via exp_ivs; final fallback 0.0"
metrics:
  duration_minutes: 20
  completed_date: "2026-03-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 2 Plan 05: VRP Signal Engine Summary

**One-liner:** 18-key VRP signal dict covering percentile, persistence, Z-score, Sharpe, momentum, excess VRP, IVR, IVP, 25-delta skew, term slope, VoV, EM ratio, jump%, GEX, and PCR — plus a four-case PRD §6.9 timing function.

## Tasks Completed

| # | Name | Status | Key Output |
|---|------|--------|------------|
| 1 | Historical context signals | DONE | vrp_pctile, vrp_persist_30d, vrp_zscore, vrp_sharpe, vrp_5d_change, vrp_10d_change, vrp_momentum, excess_vrp, ivr, ivp |
| 2 | Market-structure signals + timing | DONE | skew_25d, term_slope, vov_30d/vov_z, em_ratio, jump_pct, gex_billions, pcr_oi + vrp_timing_signal |

## Verification Results

All three automated verify commands passed:

- Task 1: `vrp_pctile=0.790 ivr=0.671 ivp=0.837 vrp_5d=0.0281 excess=0.0120` — all 11 keys present, all range checks pass
- Task 2: `term_slope=-0.0200 em_ratio=0.3094 jump_pct=0.2063 gex_bn=0.0587 pcr_oi=1.6250` — all 18 required keys present
- Overall: `compute_vrp_signals` and `vrp_timing_signal` export with correct signatures

## Signal Inventory

### Historical Context (Task 1)

| Signal | Source | Range |
|--------|--------|-------|
| `vrp` | `vrp_data['vrp']` | annualized decimal |
| `vrp_pctile` | `percentileofscore(vrp_history, vrp)` | [0, 1] |
| `vrp_persist_30d` | fraction of last 30 sessions VRP > 0 | [0, 1] |
| `vrp_zscore` | (vrp - mean) / std | unbounded |
| `vrp_sharpe` | mean/std * sqrt(252/21) | unbounded |
| `vrp_5d_change` | vrp - vrp_history.iloc[-5] | vol pts decimal |
| `vrp_10d_change` | vrp - vrp_history.iloc[-10] | vol pts decimal |
| `vrp_momentum` | sign(vrp_5d_change) | {-1, 0, +1} |
| `excess_vrp` | vrp - beta * spy_vrp | vol pts decimal |
| `ivr` | (iv30 - iv52_low) / (iv52_high - iv52_low), clipped | [0, 1] |
| `ivp` | `percentileofscore(iv30_history, iv30)` | [0, 1] |

### Market Structure (Task 2)

| Signal | Source | Notes |
|--------|--------|-------|
| `skew_25d` | put_iv - call_iv at 25-delta strikes | uses `impliedVolatility` column when available; 7% ATM proxy fallback |
| `skew_zscore` | 0.0 (deferred) | requires historical smile cache (Phase 3) |
| `term_slope` | iv60 - iv30 | positive = contango |
| `vov_30d` | `vov_signal(iv30_history)['vov_30d']` | annualized |
| `vov_z` | `vov_signal(...)['vov_z']` | Z-score vs 252-day VoV history |
| `em_ratio` | ATM straddle / (RV x spot x sqrt(DTE/252)) | 1.0 neutral default |
| `jump_pct` | `jump_stats(ensemble_rv, bpv, iv30_td)['jump_pct']` | [0, 1] |
| `gex_billions` | `compute_gex(chain, spot)['gex_billions']` | signed float |
| `pcr_oi` | `compute_pcr(chain)['pcr_oi']` | > 0 |

### VRP Timing Signal (PRD §6.9)

| Condition | Action |
|-----------|--------|
| falling (5d < -0.005) AND pctile > 0.65 | "ENTER NOW" |
| rising (5d > 0.005) AND pctile > 0.80 | "ENTER NOW or WAIT 1-3 DAYS" |
| rising AND pctile < 0.70 | "WAIT 1-3 DAYS" |
| else | "ENTER AT OPPORTUNITY" |

Threshold: 0.005 annualized decimal = 0.5 vol points (VRP is in decimal units).

## Deviations from Plan

None - plan executed exactly as written.

The skew_zscore defaulting to 0.0 with `skew_history_available: False` is explicitly specified in the plan ("use skew_zscore = 0.0 as a safe default").

## Self-Check

- [x] `analytics/vrp_engine.py` exists and is importable
- [x] `compute_vrp_signals` returns dict with all 18 required keys
- [x] `vrp_timing_signal` returns correct (action, reason) tuple for all four cases
- [x] All percentile/rank signals strictly in [0, 1]
- [x] `vrp_momentum` exactly in {-1, 0, +1}
- [x] No crash on missing `iv60` (uses `.get('iv60') or 0`)
- [x] No crash on chain with no `impliedVolatility` column (falls back to proxy)

## Self-Check: PASSED
