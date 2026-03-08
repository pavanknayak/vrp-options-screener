# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 5 — Recommendations & Reasoning

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 5: Recommendations & Reasoning |
| Current Plan | 05-03 complete — next: 05-04 (Recommendation card assembly + narrative paragraphs) |
| Status | Phase 5 in progress (3/5 plans complete) |
| Last Updated | 2026-03-08 |

**Progress**:
```
Phase 1 [##########] 100% ✓
Phase 2 [##########] 100% ✓
Phase 3 [##########] 100% ✓
Phase 4 [##########] 100% ✓
Phase 5 [######    ] 60%
Phase 6 [          ] 0%
```

**Overall**: 4 / 6 phases complete

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 39 |
| Phases total | 6 |
| Phases complete | 4 |
| Plans written | 21 |
| Plans complete | 17 |

---

## Accumulated Context

### Key Decisions Made
- Two-stage scanning pipeline: yfinance Stage 1 (1,485 tickers, 20 threads) → Schwab Stage 2 (top 175, rate-limited 100 req/min)
- Schwab Market Data OAuth scope only — zero order routing, all execution manual
- SQLite TTL cache: options 15 min, OHLCV 1 hr, fundamentals 24 hr, FRED 6 hr, earnings 12 hr
- Ensemble RV = mean(HAR-RV, GARCH-GJR, EWMA)
- Composite VRP score 0–100 weighted sum of 12 signals
- 25% fractional Kelly with regime × VoV × GEX stacked multipliers, clamped to [max_pos/4, max_pos]
- Crypto ETFs: Spread/Collar only (no CSP); China ADRs: Spread/Collar only
- Phase 4 (Fundamentals) depends on Phase 1 only — can be built in parallel with Phase 2/3
- 05-01 COMPLETE: evaluate_gonogo() with GoNoGoResult; 21-point fail-fast matrix; HARD-01..09 + SOFT-01..12
- 05-02 COMPLETE: select_structure(), select_strikes(), StructureResult; FOMC-aware DTE selection; Kelly-optimal delta
- 05-03 COMPLETE: compute_slippage_ev() mid*0.75; compute_pnl_scenarios() 4-scenario P&L; compute_kelly_size() 0.25 base * regime*VoV*GEX multipliers
- Fundamentals error key causes HARD-06 and SOFT-08 to pass through with warning (not block)

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
- Phase 4 COMPLETE: all 3 plans executed — edgar_extended.py, piotroski.py, altman.py, quality.py, engine.py
- Phase 5 covers 12 requirements (REC-01 through REC-08, REAS-01 through REAS-04): go/no-go matrix, structure selection, Kelly sizing, four-scenario P&L, narrative paragraphs
- Phase 5 depends on Phase 2 (analytics), Phase 3 (scanner), Phase 4 (fundamentals)
- Altman Z': default for all public equity with market price (manufacturer distinction not implemented per PRD §10)
- Altman Z'': fallback when no market price available (BVE/TL instead of MVE/TL)
- Per-tier gates: Tier 3 (combined>55, Altman≥1.23, Piotroski≥5), Tier 4 (>65, ≥2.50, ≥6), Tier 5 (>75, ≥2.99, ≥7)
- FRED API key not yet configured — fetchers default gracefully (0.05 risk-free rate)
- Schwab credentials not yet configured — user must set SCHWAB_APP_KEY + SCHWAB_APP_SECRET, complete OAuth on first run
- ScanOrchestrator singleton available via scanner.orchestrator.get_orchestrator()
- run_fundamentals() is the single public entry point for Phase 5 and UI

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: Execute Phase 5 Plan 04 — Recommendation card assembly + narrative paragraphs (recommendations/card.py)
