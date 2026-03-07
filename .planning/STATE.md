# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 1 — Data Infrastructure

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 1: Data Infrastructure |
| Current Plan | None started |
| Status | Not started |
| Last Updated | 2026-03-06 |

**Progress**:
```
Phase 1 [          ] 0%
Phase 2 [          ] 0%
Phase 3 [          ] 0%
Phase 4 [          ] 0%
Phase 5 [          ] 0%
Phase 6 [          ] 0%
```

**Overall**: 0 / 6 phases complete

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 0 |
| Phases total | 6 |
| Phases complete | 0 |
| Plans written | 0 |
| Plans complete | 0 |

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
- Start with Phase 1 plan: `/gsd:plan-phase 1`
- Phase 1 is the largest single phase (12 requirements) — expect 4-6 plans
- Phase 4 (Fundamentals) has no dependency on Phase 2 or 3 — can be parallelized after Phase 1 completes
- SEC EDGAR integration (DATA-06) and Schwab OAuth (DATA-03) are the two highest-risk items in Phase 1

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: `/gsd:plan-phase 1` to decompose Phase 1: Data Infrastructure into executable plans
