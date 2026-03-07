---
phase: 02-analytics-engine
plan: "03"
subsystem: analytics
tags: [iv-surface, bsm, implied-vol, pchip, brent-root-finding, vrp, total-variance]
completed: 2026-03-07

dependency_graph:
  requires:
    - analytics/realized_vol.py   # iv_to_trading_day used in compute_vrp
    - analytics/forecasters.py    # ensemble_rv_forecast used in compute_vrp
  provides:
    - analytics/iv_surface.py     # bsm_iv, fit_iv_smile, interpolate_iv_surface, compute_vrp, iv_smile_has_arbitrage
  affects:
    - analytics/vrp_engine.py     # plan 02-05 consumes compute_vrp dict (iv30, iv60, iv30_td, vrp, ensemble_rv)

tech_stack:
  added:
    - scipy.optimize.brentq       # Brent root-finding for BSM IV inversion
    - scipy.interpolate.PchipInterpolator  # monotone-cubic smile fitting
    - scipy.stats.norm            # normal CDF for BSM price formula
  patterns:
    - Brent root-finding over [1e-4, 20.0] for guaranteed convergence (vs Newton which can diverge)
    - PCHIP with extrapolate=False — NaN outside fitted range, caught and replaced by nearest IV
    - Total-variance-space interpolation (TV = IV^2 * DTE) prevents calendar arbitrage at IV30/IV60
    - Strike deduplication before PCHIP fit — averages IV when same strike appears in both puts and calls
    - Two-step liquidity filter: spread < 15% of mid + OI > 100 + bid > 0, then strike-range filter
    - Deferred import of iv_to_trading_day and ensemble_rv_forecast inside compute_vrp body (avoids circular imports)

key_files:
  created:
    - analytics/iv_surface.py
  modified: []

decisions:
  - PCHIP with extrapolate=False chosen over cubic spline — monotone interpolant, no oscillation, no negative forward variance within fitted range
  - Brent root-finding over Newton-Raphson — guaranteed convergence for valid options, no vega computation needed
  - Total-variance interpolation (IV^2 * DTE) not raw IV — prevents calendar arbitrage at interpolated DTE points
  - Duplicate-strike deduplication by averaging IVs — handles synthetic test data and real chains where puts and calls share strikes near ATM
  - filter_chain_options falls back to unfiltered DataFrame (with warning) when < 3 rows survive — ensures surface can still be computed from thin chains

metrics:
  duration_minutes: 15
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 2 Plan 3: IV Surface Pipeline Summary

**One-liner:** BSM IV inversion via Brent root-finding, PCHIP monotone-cubic smile fitting, total-variance-space interpolation to IV30/IV60, and top-level compute_vrp combining IV surface with ensemble RV forecast to produce the primary VRP signal.

---

## What Was Built

`analytics/iv_surface.py` — five public functions implementing the complete IV surface pipeline:

- `bsm_price(S, K, T, r, sigma, option_type)` — Internal BSM pricer using scipy.stats.norm.cdf. Returns intrinsic value when T <= 0 or sigma <= 0.

- `bsm_iv(market_price, S, K, T, r, option_type)` — BSM IV inversion via scipy.optimize.brentq over [1e-4, 20.0]. Returns None for deep ITM options (price <= intrinsic + 1e-6), T <= 0, or when Brent fails to bracket a root. Valid IVs constrained to [0.01, 15.0].

- `iv_smile_has_arbitrage(strikes, total_var)` — Checks for butterfly arbitrage by detecting any negative forward variance (diff < -1e-6) in a total-variance smile.

- `filter_chain_options(calls_df, puts_df, spot)` — Liquidity filter applying bid > 0, openInterest > 100, spread < 15% of mid; strike range 0.70x-1.05x spot for puts, 0.95x-1.30x spot for calls. Falls back to unfiltered if < 3 rows survive.

- `fit_iv_smile(strikes, ivs)` — PCHIP monotone-cubic interpolator over valid (IV > 0.01, finite) strike-IV pairs. Deduplicates strikes by averaging IVs. Returns None if < 3 unique valid strikes.

- `interpolate_iv_surface(chain, spot, r)` — Per-expiration BSM inversion + PCHIP smile + ATM IV extraction. Interpolates in total-variance space (IV^2 * DTE) to IV30 and IV60. Detects calendar arbitrage across expirations.

- `compute_vrp(chain, ohlc, r)` — Combines IV surface with ensemble_rv_forecast. Converts IV30 from calendar-day to trading-day basis via iv_to_trading_day before computing VRP = iv30_td - ensemble.

---

## Verification Results

**Task 1 (BSM IV inverter and arbitrage checker):**
```
BSM round-trip: true_iv=0.2500 recovered=0.250000
Task 1 PASSED
```

**Task 2 (PCHIP smile, total-variance interpolation, compute_vrp):**
```
IV30=0.1992  IV60=0.1723  VRP=0.0834
Task 2 PASSED
```

**Overall export verification:**
```
All 5 iv_surface exports OK
```

---

## Decisions Made

1. **PCHIP over cubic spline** — PchipInterpolator enforces local monotonicity, preventing negative forward variance within a single expiration. Cubic spline with natural boundary conditions can oscillate and create arbitrage.

2. **Brent root-finding over Newton-Raphson** — Brentq guarantees convergence (bisection fallback) within [1e-4, 20.0] without requiring vega computation. Newton can diverge for deep OTM options with near-zero vega.

3. **Total-variance interpolation** — IV30/IV60 computed in TV = IV^2 * DTE space rather than raw IV space. Linear interpolation in TV space is the standard no-arbitrage construction (Gatheral §1.2). IV interpolated in raw space can produce calendar arbitrage.

4. **Strike deduplication in fit_iv_smile** — When the same strike appears from both puts and calls iterrows(), PCHIP raises ValueError for non-strictly-increasing x. Fixed by np.unique + mean aggregation. This is the correct approach (put-call parity should produce similar IVs at overlapping strikes).

5. **Fallback to nearest-strike IV** — When PCHIP returns NaN at spot (spot outside fitted range), nearest-strike IV is used instead of propagating NaN through the surface.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate strike handling in fit_iv_smile**
- **Found during:** Task 2 verification — `ValueError: x must be strictly increasing sequence`
- **Issue:** When the same strikes appear in both puts_df and calls_df (common for near-ATM strikes), the combined ivs_list contains duplicate strike values. PchipInterpolator requires strictly increasing x.
- **Fix:** Added np.unique deduplication before constructing PchipInterpolator; IVs at duplicate strikes are averaged (consistent with put-call parity expectation near ATM). Added guard for < 3 unique valid strikes after deduplication.
- **Files modified:** analytics/iv_surface.py (fit_iv_smile function)
- **Commit:** inline fix — no separate commit per user instruction (no commit mode)

---

## Self-Check

Files exist:
- analytics/iv_surface.py: FOUND

All five public functions export correctly: PASSED
Task 1 automated verify: PASSED (BSM round-trip error < 1e-6)
Task 2 automated verify: PASSED (IV30=0.1992, IV60=0.1723, VRP=0.0834)
End-to-end import check: PASSED

## Self-Check: PASSED
