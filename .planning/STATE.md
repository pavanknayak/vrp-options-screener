# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 3 — Scanner Pipeline

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 3: Scanner Pipeline |
| Current Plan | None started |
| Status | Phase 2 complete — Phase 3 not started |
| Last Updated | 2026-03-07 |

**Progress**:
```
Phase 1 [##########] 100% ✓
Phase 2 [##########] 100% ✓
Phase 3 [          ] 0%
Phase 4 [          ] 0%
Phase 5 [          ] 0%
Phase 6 [          ] 0%
```

**Overall**: 2 / 6 phases complete

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 28 |
| Phases total | 6 |
| Phases complete | 2 |
| Plans written | 10 |
| Plans complete | 10 |

---

## Accumulated Context

### Key Decisions Made
- Two-stage scanning pipeline: yfinance Stage 1 (1,485 tickers, 20 threads) → Schwab Stage 2 (top 175, rate-limited 100 req/min)
- Schwab Market Data OAuth scope only — zero order routing, all execution manual
- SQLite TTL cache: options 15 min, OHLCV 1 hr, fundamentals 24 hr, FRED 6 hr, earnings 12 hr
- Ensemble RV = mean(HAR-RV, GARCH-GJR, EWMA)
- Composite VRP score 0–100 weighted sum of 12 signals
- 25% fractional Kelly with regime × VoV × GEX stacked multipliers
- Crypto ETFs: Spread/Collar only (no CSP); China ADRs: Spread/Collar only
- Phase 4 (Fundamentals) depends on Phase 1 only — can be built in parallel with Phase 2/3

### Architecture Notes
- Stack: Python 3.11+, Streamlit (localhost), SQLite, schwab-py, yfinance, FRED API, SEC EDGAR, NumPy/pandas/scipy, arch (GARCH), scikit-learn, Plotly, APScheduler
- 16 sub-tiers: 1A (US broad index ETFs) through 7 (Rest-of-World ADRs)
- FOMC calendar: static, updated annually, no API needed
- Tier assignment at load time governs liquidity filters, fundamental thresholds, permissible structures

### Pending Decisions
- None at roadmap stage

### Blockers
- None

### Notes for Next Session
- Phase 2 is COMPLETE. Start Phase 3: `/gsd:plan-phase 3`
- Phase 3 covers 5 requirements (SCAN-01 through SCAN-05): two-stage scan pipeline, Stage 1 yfinance pre-filter (20 threads, top 175), Stage 2 Schwab deep analysis (100 req/min), earnings filtering, 4 scan modes (Full/Quick/Single/Event), auto-trigger at 9:45 AM ET
- Phase 4 (Fundamentals) has no dependency on Phase 2 or 3 — can be planned and parallelized now
- `run_analytics(ticker, chain, ohlc, r, vix)` is the Phase 3 entry point — Stage 2 calls this per candidate
- PCHIP fit_iv_smile deduplicates strikes (puts+calls share strikes) before fitting — already fixed in iv_surface.py
- skew_zscore defaults to 0.0 (skew_history_available: False) — rolling smile cache not yet built; will be addressed in Phase 3 warm-cache path
- FRED API key not yet configured — fetchers default gracefully (0.05 risk-free rate)
- Schwab credentials not yet configured — user must set SCHWAB_APP_KEY + SCHWAB_APP_SECRET, complete OAuth on first run

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: `/gsd:plan-phase 3` to plan Phase 3: Scanner Pipeline
