---
phase: 06-ui-portfolio-monitor
plan: 03
subsystem: ui
tags: [streamlit, plotly, charts, ticker-analysis, recommendation-card]

# Dependency graph
requires:
  - phase: 06-01
    provides: render_regime_banner() component imported at page top
  - phase: 05-05
    provides: run_recommendation() result dict schema (passed, structure, strikes, DTE, credit, scenarios, paragraphs, etc.)
provides:
  - ui/charts.py with five Plotly chart builder functions (chart_iv_term_structure, chart_vrp_history, chart_skew, chart_scenario_pnl, chart_gex_history)
  - ui/pages/ticker_analysis.py with render_ticker_analysis() drill-down page
affects:
  - 06-04
  - 06-05
  - app.py (page routing)

# Tech tracking
tech-stack:
  added: [plotly]
  patterns:
    - All chart functions accept plain dict, return go.Figure, handle missing data with annotation placeholders
    - Analytics sub-dict fallback: result.get('analytics') or result for chart data sourcing
    - 2-column chart grid (3 left, 2 right) via st.columns(2) + st.plotly_chart(use_container_width=True)

key-files:
  created:
    - ui/charts.py
    - ui/pages/ticker_analysis.py
  modified: []

key-decisions:
  - "All five chart functions return go.Figure and handle missing/empty data with annotation placeholders — never raise"
  - "Chart data sourced from result.get('analytics') with fallback to top-level result dict for compatibility with varied result shapes"
  - "2-column chart grid: 3 charts left (IV term structure, skew, GEX history), 2 charts right (VRP history, scenario P&L)"
  - "NO-GO results still render narrative paragraphs so user sees reasoning even when trade is filtered out"

patterns-established:
  - "Chart builder pattern: accept dict, gracefully degrade with annotation on empty data, return go.Figure always"
  - "Ticker Analysis page pattern: regime banner -> result guard -> title + back button -> card -> charts -> expander detail"

requirements-completed: [UI-02]

# Metrics
duration: 15min
completed: 2026-03-12
---

# Phase 6 Plan 03: Ticker Analysis Page Summary

**Five Plotly chart builders (ui/charts.py) and full Ticker Analysis drill-down page (ui/pages/ticker_analysis.py) reading st.session_state['selected_result'] with GO/NO-GO card, trade metrics, three narrative paragraphs, broker order text, and 2-column chart grid**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-12T13:11:35Z
- **Completed:** 2026-03-12T13:26:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Five Plotly chart functions each returning go.Figure with graceful empty-data fallbacks: IV term structure, VRP history, IV skew, 4-scenario P&L bar chart, GEX history
- Ticker Analysis page reads `st.session_state['selected_result']` set by Dashboard row click; shows info message and dashboard redirect button when absent
- Recommendation card renders all key fields: GO/NO-GO status header, structure + strikes + DTE + net credit + max loss + Kelly contracts/%, breakeven + hard stop + roll trigger, FOMC warning, three narrative paragraphs, broker order text block
- Go/No-Go check detail in collapsible expander using st.dataframe on gonogo_checks list

## Task Commits

Each task was committed atomically:

1. **Task 1: Five Plotly chart builders** - `46efd06` (feat)
2. **Task 2: Ticker Analysis page** - `f71d588` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `ui/charts.py` - Five chart builder functions; all return go.Figure; handle missing data with annotation placeholders
- `ui/pages/ticker_analysis.py` - Ticker Analysis Streamlit page; recommendation card + 2-column chart grid + go/no-go expander

## Decisions Made
- Chart data sourced from `result.get("analytics") or result` fallback so the page works whether analytics is nested under an "analytics" key or flat in the top-level result dict
- NO-GO tickers still display narrative paragraphs (paragraphs 1-3) below the warning so user can read the reasoning
- plotly installed via pip (was missing from environment); no changes to requirements files needed beyond the existing project dependency list

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing plotly package**
- **Found during:** Task 1 (chart builder verification)
- **Issue:** `ModuleNotFoundError: No module named 'plotly'` — plotly referenced by plan but not present in the Python environment
- **Fix:** `pip install plotly`
- **Files modified:** None (environment only)
- **Verification:** All five chart functions imported and verified successfully after install
- **Committed in:** 46efd06 (Task 1 commit — no source file change needed)

---

**Total deviations:** 1 auto-fixed (1 blocking dependency install)
**Impact on plan:** Necessary environment fix; no scope changes.

## Issues Encountered
- plotly not installed in the project environment; resolved with pip install before chart verification could pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ui/charts.py and ui/pages/ticker_analysis.py fully implemented and verified
- Ticker Analysis page is ready to be wired into app.py page routing
- Dashboard row-click must set st.session_state['selected_result'] and st.session_state['selected_ticker'] before navigating to this page (that wiring belongs to the app router or dashboard page)

---
*Phase: 06-ui-portfolio-monitor*
*Completed: 2026-03-12*

## Self-Check: PASSED

- FOUND: ui/charts.py
- FOUND: ui/pages/ticker_analysis.py
- FOUND: .planning/phases/06-ui-portfolio-monitor/06-03-SUMMARY.md
- FOUND commit: 46efd06 (feat: five Plotly chart builder functions)
- FOUND commit: f71d588 (feat: Ticker Analysis page)
