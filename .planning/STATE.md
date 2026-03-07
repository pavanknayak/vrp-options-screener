# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 4 — Fundamentals Engine

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 4: Fundamentals Engine |
| Current Plan | None started |
| Status | Phase 3 complete — Phase 4 not started |
| Last Updated | 2026-03-07 |

**Progress**:
```
Phase 1 [##########] 100% ✓
Phase 2 [##########] 100% ✓
Phase 3 [##########] 100% ✓
Phase 4 [          ] 0%
Phase 5 [          ] 0%
Phase 6 [          ] 0%
```

**Overall**: 3 / 6 phases complete

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 33 |
| Phases total | 6 |
| Phases complete | 3 |
| Plans written | 13 |
| Plans complete | 13 |

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
- Phase 3 is COMPLETE. Start Phase 4: `/gsd:plan-phase 4`
- Phase 4 covers 6 requirements (FUND-01 through FUND-06): Piotroski F-Score, Altman Z-Score model selection, Quality of Earnings (CFO/NI), Margin of Safety, Combined Fundamental Score, per-tier gate enforcement
- Phase 4 depends on Phase 1 only — can be built without Phase 2/3 at runtime
- FRED API key not yet configured — fetchers default gracefully (0.05 risk-free rate)
- Schwab credentials not yet configured — user must set SCHWAB_APP_KEY + SCHWAB_APP_SECRET, complete OAuth on first run
- ScanOrchestrator singleton available via scanner.orchestrator.get_orchestrator() — Streamlit never imports stage1/stage2 directly

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: `/gsd:plan-phase 4` to plan Phase 4: Fundamentals Engine
