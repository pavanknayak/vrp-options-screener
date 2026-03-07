# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 1 — Data Infrastructure

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 2: Analytics Engine |
| Current Plan | None started |
| Status | Phase 1 complete — Phase 2 not started |
| Last Updated | 2026-03-07 |

**Progress**:
```
Phase 1 [##########] 100% ✓
Phase 2 [          ] 0%
Phase 3 [          ] 0%
Phase 4 [          ] 0%
Phase 5 [          ] 0%
Phase 6 [          ] 0%
```

**Overall**: 1 / 6 phases complete

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 12 |
| Phases total | 6 |
| Phases complete | 1 |
| Plans written | 4 |
| Plans complete | 4 |

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
- Phase 1 is COMPLETE. Start Phase 2: `/gsd:plan-phase 2`
- Phase 2 covers 16 requirements (ANAL-01 through ANAL-16): Yang-Zhang/Parkinson/Garman-Klass RV, HAR-RV, GARCH-GJR, EWMA, BSM IV surface, VRP signals (12), composite score 0-100, regime detection
- Phase 4 (Fundamentals) has no dependency on Phase 2 or 3 — can be parallelized after Phase 2 starts
- EDGAR CIK URL format confirmed: uses `CIK` prefix (e.g. `CIK0000320193`) not bare numeric string — already fixed in edgar_fetcher.py
- FRED API key not yet configured — fetchers default gracefully (0.05 risk-free rate); user must set FRED_API_KEY env var for live rates
- Schwab credentials not yet configured — user must set SCHWAB_APP_KEY and SCHWAB_APP_SECRET env vars, then complete OAuth flow on first run

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: `/gsd:plan-phase 1` to decompose Phase 1: Data Infrastructure into executable plans
