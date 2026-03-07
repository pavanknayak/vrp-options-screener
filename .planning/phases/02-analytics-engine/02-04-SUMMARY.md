---
phase: 02-analytics-engine
plan: "04"
subsystem: analytics
tags: [regime-detection, vix, vvix, vov, gex, pcr, microstructure]
completed: 2026-03-07

dependency_graph:
  requires:
    - data/fred_fetcher.py       # fetch_vix_history() Series passed to vov_signal
    - data/schwab_client.py      # fetch_options_chain dict consumed by compute_gex / compute_pcr
    - analytics/realized_vol.py  # iv30 series for vov_signal (plan 02-01)
  provides:
    - analytics/regime.py        # detect_regime, vov_signal
    - analytics/microstructure.py  # compute_gex, compute_pcr
  affects:
    - analytics/vrp_engine.py    # regime multiplier stacked onto Kelly sizing (plan 02-05)
    - vrp/signal_engine.py       # GEX and PCR signals feed composite VRP score (plan 02-05)

tech_stack:
  added: []
  patterns:
    - Crisis-first threshold ordering (VIX > 40 checked before any secondary signal)
    - Z-score gating with std=0 guard (vvix_z set to 0.0 when history is constant)
    - Sign convention: dealer short call = -gamma contribution, dealer short put = +gamma contribution
    - GEX dollar-scaling via OI * gamma * 100 * spot^2
    - PCR division guarded by max(denominator, 1) to avoid zero-division on empty chains

key_files:
  created:
    - analytics/regime.py
    - analytics/microstructure.py
  modified: []

decisions:
  - Crisis check (VIX > 40) is unconditionally first — VVIX instability never overrides a crisis reading
  - std=0 edge case in VVIX Z-score: treated as vvix_z=0.0 (not undefined/NaN) to prevent crashes when history is constant
  - PCR volume returns 0.0 when 'volume' column is absent from chain DataFrames (handled via column presence check rather than .get() on DataFrame)
  - GEX interpretation boundary at +/-0.5bn matches PRD §6.6 exactly

metrics:
  duration_minutes: 6
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 2 Plan 4: Regime Detection and Microstructure Signals Summary

**One-liner:** Five-regime VIX detector with VVIX Z-score override and VoV disqualifier, plus GEX (dealer gamma exposure via OI × gamma × 100 × spot²) and PCR (put-call ratio) computed directly from the Schwab options chain.

---

## What Was Built

`analytics/regime.py` — two public functions governing position sizing and go/no-go filters:

- `detect_regime(vix, vvix=None, vix3m=None, vvix_history=None)` — Classifies current environment into one of five labels (Low, Normal, Elevated, High, Crisis) with a corresponding size multiplier (0.5, 1.0, 1.25, 0.75, 0.0). Crisis (VIX > 40) is checked first and always wins. If VVIX Z-score exceeds 2.5 (and VIX is not already in Crisis), returns VOL_UNSTABLE sub-regime at 0.25× size. Also computes term slope (VIX3M − VIX) for context. Returns `is_crisis` bool for hard disqualifier downstream.

- `vov_signal(iv30_history)` — Computes annualized 30-day Vol-of-Vol from the trailing 30 IV30 observations (`std × sqrt(252)`), then Z-scores it against the 252-day rolling VoV distribution. Returns `disqualify=True` if vov_z > 2.5. Gracefully returns `flag='insufficient_history'` when fewer than 30 observations are available.

`analytics/microstructure.py` — two public functions computing market-structure inputs for sizing:

- `compute_gex(chain, spot)` — Iterates over all expirations and strikes. Calls contribute negative GEX (dealers short calls = short gamma), puts contribute positive GEX (dealers short puts = long gamma via delta hedge). Scales by `OI × gamma × 100 × spot²`. Divides raw GEX by 1e9 for human-readable billions. Interprets against PRD §6.6 thresholds (±0.5bn boundary). Returns `supports_collection` bool.

- `compute_pcr(chain)` — Aggregates put and call open interest and volume across all expirations. `pcr_oi = total_put_OI / total_call_OI` (floor 1 to prevent zero-division). `pcr_volume` computed the same way from volume columns. Interprets against PRD §6.7 thresholds (1.8 / 1.2 / 0.8 boundaries).

---

## Verification Results

**Task 1 (regime + VoV):**
```
VIX=25, VVIX=100: label=Elevated   # std=0 guard fires → no VOL_UNSTABLE
All regime thresholds PASS
VoV signal: vov_30d=0.2543  vov_z=-2.4881
Task 1 PASSED
```

**Task 2 (GEX + PCR spot-check):**
```
GEX raw=253125000  expected=253125000  match=True
PCR OI=2.0000  expected=2.0000  match=True
Task 2 PASSED
```

**Final import/export check:**
```
regime: detect_regime, vov_signal OK
microstructure: compute_gex, compute_pcr OK
```

---

## Decisions Made

1. **Crisis-first ordering** — VIX > 40 is evaluated before the VVIX Z-score gate. This matches PRD §6.12 intent: a market in crisis cannot be partially mitigated by VVIX behaviour.

2. **std=0 guard for VVIX Z-score** — When the history Series is constant (std = 0), the code sets `vvix_z = 0.0` instead of raising `ZeroDivisionError`. This occurred in the test with `np.ones(252) * 25.0`; the guard prevented a crash and the label correctly fell back to the VIX-level regime (Elevated at VIX=25).

3. **PCR volume column presence check** — Used explicit `'volume' in df.columns` rather than `df.get('volume', pd.Series([0])).sum()` (the plan pseudocode). The plan's `.get()` call on a DataFrame returns a column Series or raises if absent — not a default. The fix uses a guard that correctly handles chains where volume data is absent.

4. **GEX empty-chain safety** — Both `compute_gex` and `compute_pcr` use `chain.get('expirations', [])` so they return sensible zero-GEX / zero-PCR results on empty or malformed chains rather than raising `KeyError`.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PCR volume fallback pattern corrected**
- **Found during:** Task 2 implementation review
- **Issue:** Plan pseudocode used `exp['puts'].get('volume', pd.Series([0])).sum()` — calling `.get()` on a DataFrame returns a column Series (correct) or raises `KeyError` if absent (not a default), making it functionally different from dict `.get()`.
- **Fix:** Replaced with explicit `if 'volume' in df.columns:` guard before summing. Volume totals remain 0 when column is absent.
- **Files modified:** analytics/microstructure.py
- **Impact:** None on test results (test DataFrames include volume column); prevents KeyError on real chains lacking volume.

---

## Self-Check

Files exist:
- analytics/regime.py: FOUND
- analytics/microstructure.py: FOUND

Task 1 automated verify: PASSED
Task 2 automated verify (GEX spot-check to < 1.0 tolerance): PASSED
Final import/export check: PASSED

## Self-Check: PASSED
