---
phase: 06-ui-portfolio-monitor
plan: 01
subsystem: ui
tags: [streamlit, yfinance, regime, config, sidebar, session_state]

# Dependency graph
requires:
  - phase: 03-scanner-pipeline
    provides: yfinance, scan_results structure used by gex_billions aggregation
  - phase: 05-recommendations-reasoning
    provides: run_recommendation() — scan_results shape for gex_billions
  - analytics/regime.py
    provides: detect_regime() — single source of truth for VIX thresholds and multipliers

provides:
  - ui/components/regime_banner.py — render_regime_banner() Streamlit banner component
  - ui/components/config_sidebar.py — render_config_sidebar(), load_config(), save_config(), DEFAULT_CONFIG
  - config.json — seeded default configuration in repo root

affects:
  - 06-02 (scanner dashboard page)
  - 06-03 (ticker detail page)
  - 06-04 (custom lookup page)
  - 06-05 (portfolio correlation monitor)
  - 06-06 (app.py entry point)
  - 06-07 (APScheduler background scan)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Regime label/color/multiplier delegated entirely to analytics.regime.detect_regime() — no thresholds in UI layer"
    - "load_config() merges on-disk JSON with DEFAULT_CONFIG so new config keys are always present (forward-compatible)"
    - "st.session_state['config'] as single config source of truth for all pages"
    - "st.session_state['last_regime'] populated by render_regime_banner() for downstream page use"

key-files:
  created:
    - ui/__init__.py
    - ui/components/__init__.py
    - ui/components/regime_banner.py
    - ui/components/config_sidebar.py
    - config.json
  modified: []

key-decisions:
  - "regime_banner.py imports detect_regime() from analytics.regime — VIX thresholds live in one place only"
  - "REGIME_COLORS includes VOL_UNSTABLE (purple #8e44ad) in addition to the 5 standard regime labels"
  - "Actual analytics.regime.py thresholds used: Low<=15, Normal 15-20, Elevated 20-28, High 28-40, Crisis>40 (plan had incorrect 30/40 split — corrected after reading source)"
  - "min_ivp default set to 0.60 (60th percentile per PRD) not 0.50 as in plan template"

patterns-established:
  - "Banner-first pattern: render_regime_banner() called at top of every page before any content"
  - "Config sidebar pattern: render_config_sidebar() called on every page; returns cfg dict; no restart needed"

requirements-completed: [UI-04, UI-05]

# Metrics
duration: 18min
completed: 2026-03-08
---

# Phase 6 Plan 01: Shared UI Components Summary

**Streamlit regime banner (live VIX/VVIX via yfinance, colored by detect_regime()) and config sidebar (JSON-persisted, session_state-backed, no-restart updates) as Wave 1 foundations for all Phase 6 pages.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-03-08T05:46:41Z
- **Completed:** 2026-03-08T06:04:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- `render_regime_banner()` fetches live VIX and VVIX via yfinance, calls `analytics.regime.detect_regime()` for regime label and multiplier, and renders a styled Streamlit banner with VIX, VVIX, T-Bill rate, GEX, and size multiplier
- `render_config_sidebar()` renders all portfolio/screening/slippage/tier configuration fields in the Streamlit sidebar; persists to `config.json` on Save; changes take effect on next scan without restarting
- `config.json` seeded in repo root so first-clone users never hit `FileNotFoundError`; `load_config()` merges with `DEFAULT_CONFIG` for forward compatibility

## Task Commits

Each task was committed atomically:

1. **Task 1: Regime banner component** - `979e7b0` (feat)
2. **Task 2: Config sidebar component + config.json** - `3f6932d` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified

- `ui/__init__.py` — package marker
- `ui/components/__init__.py` — package marker
- `ui/components/regime_banner.py` — render_regime_banner(), REGIME_COLORS, _fetch_regime_data(); delegates all regime logic to analytics.regime
- `ui/components/config_sidebar.py` — render_config_sidebar(), load_config(), save_config(), DEFAULT_CONFIG
- `config.json` — seeded default configuration (portfolio_value=100000, all 15 tiers active)

## Decisions Made

- Imported `detect_regime()` from `analytics.regime` rather than repeating thresholds — ensures the UI banner always matches the analytics engine's regime classification with zero duplication
- Added `VOL_UNSTABLE` to `REGIME_COLORS` (purple #8e44ad) because `detect_regime()` can return that label when VVIX Z-score > 2.5; without the color entry the banner would fall through to the default blue
- Set `min_ivp` default to `0.60` (60th percentile per PRD key_implementation_notes) rather than `0.50` from the plan template

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected VIX threshold breakpoints to match analytics/regime.py**
- **Found during:** Task 1 (reading analytics/regime.py before writing)
- **Issue:** Plan template had thresholds at 30 (Elevated→High) and 40 (High→Crisis); actual `detect_regime()` uses 28 and 40 (strict greater-than), with Low multiplier 0.50 not 0.75
- **Fix:** Used the actual breakpoints from analytics/regime.py: Elevated=vix>20, High=vix>28, Crisis=vix>40
- **Files modified:** ui/components/regime_banner.py (no thresholds are embedded — calls detect_regime() directly so no hardcoded values to change)
- **Verification:** `rb.detect_regime is detect_regime` identity assertion passed; _fetch_regime_data() returned label "Elevated" at vix=22.5 matching analytics.regime output
- **Committed in:** `979e7b0` (Task 1 commit)

**2. [Rule 2 - Missing Critical] Added VOL_UNSTABLE color to REGIME_COLORS**
- **Found during:** Task 1 (reading analytics/regime.py)
- **Issue:** `detect_regime()` can return label "VOL_UNSTABLE" (when VVIX Z-score > 2.5); plan REGIME_COLORS only listed 5 labels — banner would silently render default blue for this state
- **Fix:** Added `"VOL_UNSTABLE": "#8e44ad"` (purple) to REGIME_COLORS per key_implementation_notes
- **Files modified:** ui/components/regime_banner.py
- **Verification:** `set(REGIME_COLORS.keys()) == {'Low','Normal','Elevated','High','Crisis','VOL_UNSTABLE'}` assertion passed
- **Committed in:** `979e7b0` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 bug — wrong thresholds, 1 missing critical — missing VOL_UNSTABLE color)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered

None — automated verification passed on first attempt for both tasks.

## User Setup Required

None — no external service configuration required for these components. Schwab credentials are optional (sidebar displays a warning if absent).

## Next Phase Readiness

- `render_regime_banner()` and `render_config_sidebar()` are ready for import by all Wave 2 pages (06-02 through 06-07)
- `st.session_state['config']` and `st.session_state['last_regime']` are populated by these components on first page render
- No blockers

---
*Phase: 06-ui-portfolio-monitor*
*Completed: 2026-03-08*
