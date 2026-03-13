# VRP Options Screener — Project State

## Project Reference

**Core Value**: Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

**Current Focus**: Phase 6 — UI & Portfolio Monitor

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | Phase 6: UI & Portfolio Monitor |
| Current Plan | 06-05 complete |
| Status | In progress |
| Last Updated | 2026-03-12 |

**Progress**:
```
Phase 1 [##########] 100% ✓
Phase 2 [##########] 100% ✓
Phase 3 [##########] 100% ✓
Phase 4 [##########] 100% ✓
Phase 5 [##########] 100% ✓
Phase 6 [##########] 96%
```

**Overall**: 5 / 6 phases complete (Phase 6: 7/7 plans — only 06-07 app entry point remaining but included in prior phase count)

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Requirements total | 61 |
| Requirements complete | 51 |
| Phases total | 6 |
| Phases complete | 5 |
| Plans written | 21 |
| Plans complete | 21 |

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
- 05-04 COMPLETE: build_recommendation_card(); RecommendationCard dataclass; three data-driven narrative paragraphs; broker-ready order text for CSP/Spread/Collar
- 05-05 COMPLETE: run_recommendation() orchestrator; chains gonogo->structures->pnl->card in dependency order; never raises; always builds card for UI even on gonogo fail
- Fundamentals error key causes HARD-06 and SOFT-08 to pass through with warning (not block)
- 06-01 COMPLETE: render_regime_banner() + render_config_sidebar(); regime label/color/multiplier delegated to analytics.regime.detect_regime(); config persisted to config.json; REGIME_COLORS includes VOL_UNSTABLE (purple)
- 06-02 COMPLETE: render_dashboard() + _build_dataframe(); 13-column sortable/filterable table; GO/NO-GO color styling; CSV export via st.download_button; row selection via st.dataframe(on_select='rerun'); scan triggers via _trigger_scan(mode) writing to session_state
- 06-03 COMPLETE: five Plotly chart builders in ui/charts.py (chart_iv_term_structure, chart_vrp_history, chart_skew, chart_scenario_pnl, chart_gex_history); render_ticker_analysis() reads session_state['selected_result']; recommendation card with GO/NO-GO header, 4-column trade params, 3-column risk levels, FOMC warning, three narratives, broker order text; 2-col chart grid (3 left, 2 right); go/no-go expander; analytics sub-dict fallback pattern
- 06-04 COMPLETE: render_custom_lookup() + _run_single_analysis(); on-demand single-ticker Stage 2 via get_orchestrator().run_single_ticker(); isinstance(result, list) guard for return-shape normalisation; result cleared before each analysis to prevent stale display; session_state['lookup_result'] persists result across reruns; reuses _render_recommendation_card() from ticker_analysis and all five chart_ functions
- 06-06 COMPLETE: render_settings(); full-width config form + active tier multiselect (save_config()) + universe ticker add/remove (writes tickers.json directly) + Schwab status (_schwab_status() returns (bool, bool, str)); ticker management uses direct json.load/json.dump — not loader.py — intentional write path
- 06-05 COMPLETE: portfolio/db.py (Position dataclass, save_position/load_positions/delete_position, portfolio_positions table in vrp_cache.db); ui/pages/portfolio_monitor.py (render_portfolio_monitor, _compute_cvar_monte_carlo 10k MC samples, _compute_correlation_matrix tail(60).corr(), _tail_hedge_recommendation, Plotly heatmap with rho>0.70 flagging, st.metric CVaR+short-vol%)

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
- Phase 5 COMPLETE: all 5 plans executed — gonogo.py, structures.py, pnl.py, card.py, engine.py
- Phase 6 in progress: 06-01..06-04 and 06-06 complete — regime banner, dashboard, ticker analysis+charts, custom lookup, settings
- 06-04 was back-filled (skipped in prior session that ran 06-06); now complete with SUMMARY
- Phase 6 is the final phase: Streamlit UI + Portfolio Monitor
- Altman Z': default for all public equity with market price (manufacturer distinction not implemented per PRD §10)
- Altman Z'': fallback when no market price available (BVE/TL instead of MVE/TL)
- Per-tier gates: Tier 3 (combined>55, Altman≥1.23, Piotroski≥5), Tier 4 (>65, ≥2.50, ≥6), Tier 5 (>75, ≥2.99, ≥7)
- FRED API key not yet configured — fetchers default gracefully (0.05 risk-free rate)
- Schwab credentials not yet configured — user must set SCHWAB_APP_KEY + SCHWAB_APP_SECRET, complete OAuth on first run
- ScanOrchestrator singleton available via scanner.orchestrator.get_orchestrator()
- run_recommendation() is the single public entry point for Phase 5 recommendations

---

## Session Continuity

**To resume**: Read this file + `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md`

**Next action**: Continue Phase 6 — execute 06-07 (App entry point: main.py Streamlit multi-page app wiring all pages)
