---
phase: 06-ui-portfolio-monitor
plan: "05"
subsystem: ui
tags: [streamlit, sqlite, numpy, pandas, plotly, yfinance, portfolio, risk, cvar, correlation]

requires:
  - phase: 06-01
    provides: render_regime_banner() component used at top of portfolio monitor page
  - phase: 06-02
    provides: UI patterns (regime banner, config sidebar) established for all pages

provides:
  - portfolio/db.py: SQLite persistence for open positions (save_position, load_positions, delete_position, Position dataclass)
  - ui/pages/portfolio_monitor.py: Portfolio Monitor Streamlit page with position CRUD, correlation matrix, CVaR, and tail hedge recommendation

affects:
  - 06-07 (app entry point — must register portfolio monitor page)

tech-stack:
  added: []
  patterns:
    - "DB_PATH reuses vrp_cache.db (project root) via os.path.join relative to portfolio/db.py"
    - "Monte Carlo CVaR: np.random.default_rng(42).multivariate_normal, 10,000 samples, 60-day historical cov"
    - "Correlation: returns.tail(60).corr() for consistent 60-trading-day window"
    - "Portfolio weights derived from contract-count sum per ticker, normalized to sum=1"

key-files:
  created:
    - portfolio/__init__.py
    - portfolio/db.py
    - ui/pages/portfolio_monitor.py
  modified: []

key-decisions:
  - "DB_PATH points to vrp_cache.db (not cache.db) — matches existing CacheDB._DEFAULT_DB_PATH convention"
  - "portfolio_positions table created with _ensure_table() on every call — no migration needed, idempotent"
  - "CVaR uses seed 42 for reproducibility across reruns; returns consistent metric for same positions"
  - "Weights computed proportional to contract quantity per ticker — respects position sizing"

patterns-established:
  - "Risk metrics (CVaR, correlation) are pure functions — no Streamlit dependencies — easily unit-tested"
  - "Tail hedge recommendation generated as plain-English string, displayed via st.info()"

requirements-completed: [PORT-01, PORT-02, PORT-03, PORT-04]

duration: 15min
completed: 2026-03-12
---

# Phase 6 Plan 05: Portfolio Monitor Summary

**SQLite-backed portfolio position manager with 60-day pairwise correlation heatmap, 1d 99% Monte Carlo CVaR (10,000 samples), and plain-English tail hedge recommendations surfaced via Streamlit metrics and Plotly heatmap**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-12T06:51:06Z
- **Completed:** 2026-03-12T07:06:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `portfolio/db.py` delivers full CRUD for positions: `save_position()`, `load_positions()`, `delete_position()` backed by `portfolio_positions` table in `vrp_cache.db`
- `_compute_cvar_monte_carlo()` runs 10,000 MC samples from multivariate normal using 60-day historical covariance, returning 1d 99% CVaR in dollars
- `_compute_correlation_matrix()` uses `tail(60).corr()` and flags pairs with `abs(rho) > 0.70` via `st.warning()`
- `render_portfolio_monitor()` integrates regime banner, position CRUD form, metrics row (CVaR, short-vol %, counts), Plotly heatmap, and tail hedge recommendation text

## Task Commits

1. **Task 1: Portfolio SQLite persistence (portfolio/db.py)** - `1eacc66` (feat)
2. **Task 2: Portfolio Monitor page (ui/pages/portfolio_monitor.py)** - `0f1aa76` (feat)

## Files Created/Modified
- `portfolio/__init__.py` - Package marker for portfolio module
- `portfolio/db.py` - Position dataclass + save/load/delete with `portfolio_positions` SQLite table
- `ui/pages/portfolio_monitor.py` - Full Portfolio Monitor Streamlit page (risk functions + UI rendering)

## Decisions Made
- Used `vrp_cache.db` (project root) rather than a separate `cache.db` — consistent with existing `CacheDB._DEFAULT_DB_PATH` convention; no second DB file created
- `_ensure_table()` called on every DB operation — idempotent DDL, no migration scripts needed
- CVaR seeded with `np.random.default_rng(42)` for deterministic output on repeated reruns
- Portfolio weights proportional to contract quantity per ticker (not equal-weight per position), which correctly reflects position sizing concentration

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DB_PATH corrected from cache.db to vrp_cache.db**
- **Found during:** Task 1 (portfolio/db.py)
- **Issue:** Plan's key_implementation_notes referenced `data/cache.db` but the actual project DB (per `cache/db.py`) is `vrp_cache.db` in project root
- **Fix:** Set `DB_PATH = os.path.join(os.path.dirname(__file__), "..", "vrp_cache.db")` to match existing convention
- **Files modified:** portfolio/db.py
- **Verification:** Round-trip test (save/load/delete) passes; vrp_cache.db already exists in project root
- **Committed in:** 1eacc66 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — wrong DB path)
**Impact on plan:** Required for correctness — using wrong path would create a dangling second DB file.

## Issues Encountered
- Windows file locking prevented `os.unlink(tmp)` in the Task 1 temp-file test — this is an OS behavior on Windows, not a code bug. All assertions passed before the unlink attempt.

## User Setup Required
None - no external service configuration required. Uses existing `vrp_cache.db`.

## Next Phase Readiness
- Portfolio Monitor page is complete and ready to be registered in the app entry point (06-07)
- `render_portfolio_monitor` exported from `ui/pages/portfolio_monitor.py`
- No blockers

---
*Phase: 06-ui-portfolio-monitor*
*Completed: 2026-03-12*
