# VRP Options Screener — Roadmap

## Phases

- [x] **Phase 1: Data Infrastructure** - App launches, fetches and caches all data sources, manages the ticker universe
- [x] **Phase 2: Analytics Engine** - App computes all volatility estimators, IV surface, VRP signals, and composite score
- [x] **Phase 3: Scanner Pipeline** - App runs two-stage scan across the full universe within performance budgets
- [x] **Phase 4: Fundamentals Engine** - App scores every Stage 2 candidate on Piotroski, Altman, quality-of-earnings, and margin-of-safety
- [ ] **Phase 5: Recommendations & Reasoning** - App produces complete, self-explaining trade plans with four-scenario P&L, Kelly sizing, and narrative paragraphs
- [ ] **Phase 6: UI & Portfolio Monitor** - App surfaces everything through a coherent Streamlit interface with portfolio correlation monitoring

---

## Phase Details

### Phase 1: Data Infrastructure

**Goal**: The app launches and reliably supplies every downstream component with fresh, cached data from all required sources — yfinance, Schwab, FRED, SEC EDGAR, and static calendars — with the ticker universe fully configured and user-editable.

**Depends on**: Nothing (foundation)

**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08, DATA-09, UNIV-01, UNIV-02, UNIV-03

**Success Criteria** (what must be TRUE when this phase completes):
1. User runs `streamlit run app.py` and the app opens in their browser on localhost within 10 seconds with no errors.
2. App authenticates with Schwab via OAuth2, auto-refreshes the token, and the connection status is visible — re-running the app does not prompt login again if the token is valid.
3. App fetches, caches, and serves OHLCV history, options chains, FRED rates, SEC EDGAR financials, earnings dates, and FOMC calendar — each at its specified TTL — so a warm-cache restart pulls zero external requests for unexpired data.
4. User can open the Configuration sidebar, add a ticker to any tier, remove a ticker from any tier, and the change persists the next time the app starts.
5. Each of the ~1,485 tickers in the universe resolves its correct tier (1A–7) at load time, with tier-specific rules (crypto spread/collar only, China ADR restrictions) correctly attached.

**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — SQLite TTL cache + OHLCV and FRED fetchers
- [x] 01-02-PLAN.md — Ticker universe loader and tier assignment
- [x] 01-03-PLAN.md — yfinance options and earnings fetchers + FOMC calendar
- [x] 01-04-PLAN.md — Schwab OAuth2 client and EDGAR XBRL fetcher

---

### Phase 2: Analytics Engine

**Goal**: The app can ingest raw OHLCV and options chain data for any ticker and produce the full suite of volatility estimates, IV surface, and all 12 VRP signals plus composite score.

**Depends on**: Phase 1

**Requirements**: ANAL-01, ANAL-02, ANAL-03, ANAL-04, ANAL-05, ANAL-06, ANAL-07, ANAL-08, ANAL-09, ANAL-10, ANAL-11, ANAL-12, ANAL-13, ANAL-14, ANAL-15, ANAL-16

**Success Criteria** (what must be TRUE when this phase completes):
1. For any ticker, the app produces Yang-Zhang, Parkinson, and Garman-Klass RV over 10d/21d/30d/60d windows, plus HAR-RV, GARCH(1,1)-GJR, and EWMA forecasts, and an ensemble average — all numerically consistent with published formulas.
2. App BSM-inverts Schwab mid-prices to per-strike IVs, fits a PCHIP smile per expiration, and interpolates a single IV30 and IV60 in total-variance space — no arbitrage violations (no negative forward variance) in the fitted surface.
3. App computes VRP (IV30 annualized minus ensemble RV forecast), all 12 individual signals (percentile, persistence, Z-score, Sharpe, momentum 5d/10d, excess VRP, IVR, IVP, skew+Z, term slope, VoV, EM ratio, jump%, GEX, PCR), and a composite VRP score 0–100.
4. App detects the current VIX regime (Low/Normal/Elevated/High/Crisis) and the regime label matches the VIX level displayed in the UI banner.
5. GEX and PCR computed from a Schwab options chain match a manual spot-check of OI × gamma × 100 × spot² and put-OI / call-OI respectively.

**Plans**: 6 plans

Plans:
- [ ] 02-01-PLAN.md — Yang-Zhang, Parkinson, Garman-Klass RV estimators (realized_vol.py)
- [ ] 02-02-PLAN.md — HAR-RV, GARCH-GJR, EWMA forecasters + Bipower Variation (forecasters.py)
- [ ] 02-03-PLAN.md — BSM IV inversion, PCHIP smile, IV30/IV60 interpolation, VRP (iv_surface.py)
- [ ] 02-04-PLAN.md — VIX regime detection + GEX + PCR microstructure (regime.py, microstructure.py)
- [ ] 02-05-PLAN.md — All 12 VRP signals + timing signal (vrp_engine.py)
- [ ] 02-06-PLAN.md — Composite VRP score 0–100 + run_analytics() orchestrator (composite_score.py, engine.py)

---

### Phase 3: Scanner Pipeline

**Goal**: The app executes the full two-stage scan — Stage 1 bulk pre-filter across all ~1,485 tickers, Stage 2 deep analysis on top 175 — within the specified time budgets, with correct earnings filtering and all four scan modes operational.

**Depends on**: Phase 1, Phase 2

**Requirements**: SCAN-01, SCAN-02, SCAN-03, SCAN-04, SCAN-05

**Success Criteria** (what must be TRUE when this phase completes):
1. Full Scan completes Stage 1 in under 35 minutes cold (under 5 minutes warm cache) using 20 parallel threads, returning exactly the top 175 candidates ranked by IVP × max(VRP, 0).
2. Stage 2 processes all 175 candidates via the Schwab API, stays within 100 req/min, and completes in under 25 minutes — any rate-limit errors are handled gracefully with retry, not a crash.
3. Any ticker with earnings falling inside its DTE window is automatically skipped during Stage 1 pre-filter, with the reason logged and visible.
4. User can trigger a Quick Refresh (top 30 re-analyzed in roughly 2–3 minutes), a Single Ticker Lookup (result returned in under 30 seconds), and an Event Refresh (triggered when VIX rises 5% intraday) — each mode surfaces updated results without restarting the app.
5. Full Scan auto-triggers at 9:45 AM ET on trading days with no user action required.

**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — Stage 1 parallel pre-filter: scanner/stage1.py (20-thread ThreadPoolExecutor, earnings skip, IVP×VRP ranking)
- [x] 03-02-PLAN.md — Stage 2 deep analysis + scan modes: scanner/stage2.py, scanner/modes.py (Schwab rate-limit, 429 retry, Quick/Single/Event)
- [x] 03-03-PLAN.md — Scan orchestrator + APScheduler: scanner/orchestrator.py (ScanOrchestrator, 9:45 AM ET auto-trigger, result cache, singleton)

---

### Phase 4: Fundamentals Engine

**Goal**: The app computes and enforces all four fundamental scoring models from SEC EDGAR data, correctly selects the Altman model by company type, and gates CSP recommendations behind per-tier score thresholds.

**Depends on**: Phase 1

**Requirements**: FUND-01, FUND-02, FUND-03, FUND-04, FUND-05, FUND-06

**Success Criteria** (what must be TRUE when this phase completes):
1. App computes all 9 Piotroski F-Score binary factors from EDGAR financials and produces a score 0–9 that matches a manual calculation from the same filing data.
2. App selects the correct Altman model (Z, Z', or Z'') based on whether the company is a manufacturer, non-manufacturer, or private analog, and any ticker with Altman Z in the distress zone is automatically disqualified from CSP structure.
3. App computes Quality of Earnings (CFO / Net Income) and flags any ticker below 0.8 as an accrual anomaly — the flag is visible on the ticker detail page.
4. App computes the Margin of Safety score across all 6 factors and the Combined Fundamental Score (0.45 × F-Score normalized + 0.55 × MOS), consistent with the formula in the spec.
5. Per-tier minimum fundamental thresholds are enforced: a ticker that fails its tier's minimum score cannot receive a CSP recommendation, and the go/no-go matrix shows which threshold it failed.

**Plans**: 3 plans

Plans:
- [x] 04-01-PLAN.md — Extended EDGAR fetcher (prior-year fields) + Piotroski F-Score 9-factor computation (fundamentals/edgar_extended.py, fundamentals/piotroski.py)
- [x] 04-02-PLAN.md — Altman Z-Score model selection (Z/Z'/Z'') + Quality of Earnings + Margin of Safety 6-factor score (fundamentals/altman.py, fundamentals/quality.py)
- [x] 04-03-PLAN.md — Fundamentals engine orchestrator: Combined Score + per-tier gate enforcement (fundamentals/engine.py)

---

### Phase 5: Recommendations & Reasoning

**Goal**: For every Stage 2 candidate that passes the go/no-go matrix, the app produces a complete, actionable trade plan — correct structure, specific strikes, Kelly-sized position, four-scenario P&L, slippage-adjusted EV, and three narrative paragraphs — that the user can act on without additional research.

**Depends on**: Phase 2, Phase 3, Phase 4

**Requirements**: REC-01, REC-02, REC-03, REC-04, REC-05, REC-06, REC-07, REC-08, REAS-01, REAS-02, REAS-03, REAS-04

**Success Criteria** (what must be TRUE when this phase completes):
1. Every candidate passes through the full 21-point go/no-go matrix; all hard disqualifiers (earnings inside DTE, EV <= 0, VoV Z > 2.5, Crisis regime, Altman distress, jump% > 50%, China/crypto structure bans) correctly reject candidates, and the first failing criterion is shown.
2. App selects the asset-class-correct trade structure (e.g., Spread/Collar for crypto ETFs and China ADRs, no CSP), picks Kelly-optimal delta (base 25Δ with VRP and VoV adjustments), and avoids expirations within 2 days of FOMC.
3. App outputs a full recommendation card showing: structure, specific strikes, DTE, net credit, max loss, breakeven, profit target, hard stop, roll trigger, four-scenario P&L with probability-weighted EV, 25% fractional Kelly size with regime × VoV × GEX multipliers applied, and manual order text.
4. Four-scenario P&L (Bull/Base/Bear/Crash) uses slippage-adjusted EV (bid-ask × 0.75 factor per leg), and crypto ETF crash scenarios use ±50% shocks — numbers are self-consistent and match manual verification on a sample ticker.
5. Each recommendation card contains three narrative paragraphs: (1) which signals are elevated and by how much vs history, (2) why to enter now versus wait referencing VRP momentum/FOMC/GEX/VoV, (3) the specific event or condition that would cause this trade to lose — written in plain English with no generic boilerplate.

**Plans**: TBD

---

### Phase 6: UI & Portfolio Monitor

**Goal**: All analytical output is accessible through a coherent Streamlit interface — scanner dashboard, ticker detail, custom lookup, configuration, and regime banner — and the user can monitor their open positions for correlation and tail risk.

**Depends on**: Phase 2, Phase 3, Phase 4, Phase 5

**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, PORT-01, PORT-02, PORT-03, PORT-04

**Success Criteria** (what must be TRUE when this phase completes):
1. Scanner Dashboard table shows all Stage 2 results with sortable/filterable columns (Ticker, Tier, Score, IV30, VRP, VRP%, IVP, Persistence, Excess VRP, Skew, EM Ratio, Earnings, GO/NO-GO); clicking any row opens the full Ticker Analysis page with recommendation card and all five supplementary charts.
2. Regime banner is visible at the top of every page, displaying current VIX level, VVIX, regime label in the correct color, GEX, T-bill rate, and regime size multiplier — updates on each page load.
3. User can type any ticker into the Custom Ticker Lookup page and receive a full Stage 2 analysis result (recommendation card + charts) in under 30 seconds.
4. Configuration sidebar lets the user set portfolio value, position limits, screening thresholds, slippage factors, and active universe tiers — changes take effect on the next scan without restarting the app.
5. User can manually enter open positions in the Portfolio Monitor, and the app displays the 60-day pairwise correlation matrix with pairs flagged at rho > 0.70, 1d 99% CVaR, short-vol exposure percentage, and tail hedge recommendation.
6. User can export the scanner results table to a CSV file from the dashboard with one click.

**Plans**: TBD

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Infrastructure | 4/4 | Complete | 2026-03-07 |
| 2. Analytics Engine | 6/6 | Complete | 2026-03-07 |
| 3. Scanner Pipeline | 3/3 | Complete | 2026-03-07 |
| 4. Fundamentals Engine | 3/3 | Complete | 2026-03-07 |
| 5. Recommendations & Reasoning | 0/? | Not started | - |
| 6. UI & Portfolio Monitor | 0/? | Not started | - |

---

## Coverage Map

| Requirement | Phase |
|-------------|-------|
| DATA-01 | Phase 1 |
| DATA-02 | Phase 1 |
| DATA-03 | Phase 1 |
| DATA-04 | Phase 1 |
| DATA-05 | Phase 1 |
| DATA-06 | Phase 1 |
| DATA-07 | Phase 1 |
| DATA-08 | Phase 1 |
| DATA-09 | Phase 1 |
| UNIV-01 | Phase 1 |
| UNIV-02 | Phase 1 |
| UNIV-03 | Phase 1 |
| ANAL-01 | Phase 2 |
| ANAL-02 | Phase 2 |
| ANAL-03 | Phase 2 |
| ANAL-04 | Phase 2 |
| ANAL-05 | Phase 2 |
| ANAL-06 | Phase 2 |
| ANAL-07 | Phase 2 |
| ANAL-08 | Phase 2 |
| ANAL-09 | Phase 2 |
| ANAL-10 | Phase 2 |
| ANAL-11 | Phase 2 |
| ANAL-12 | Phase 2 |
| ANAL-13 | Phase 2 |
| ANAL-14 | Phase 2 |
| ANAL-15 | Phase 2 |
| ANAL-16 | Phase 2 |
| SCAN-01 | Phase 3 |
| SCAN-02 | Phase 3 |
| SCAN-03 | Phase 3 |
| SCAN-04 | Phase 3 |
| SCAN-05 | Phase 3 |
| FUND-01 | Phase 4 |
| FUND-02 | Phase 4 |
| FUND-03 | Phase 4 |
| FUND-04 | Phase 4 |
| FUND-05 | Phase 4 |
| FUND-06 | Phase 4 |
| REC-01 | Phase 5 |
| REC-02 | Phase 5 |
| REC-03 | Phase 5 |
| REC-04 | Phase 5 |
| REC-05 | Phase 5 |
| REC-06 | Phase 5 |
| REC-07 | Phase 5 |
| REC-08 | Phase 5 |
| REAS-01 | Phase 5 |
| REAS-02 | Phase 5 |
| REAS-03 | Phase 5 |
| REAS-04 | Phase 5 |
| UI-01 | Phase 6 |
| UI-02 | Phase 6 |
| UI-03 | Phase 6 |
| UI-04 | Phase 6 |
| UI-05 | Phase 6 |
| UI-06 | Phase 6 |
| PORT-01 | Phase 6 |
| PORT-02 | Phase 6 |
| PORT-03 | Phase 6 |
| PORT-04 | Phase 6 |

**Coverage: 61/61 requirements mapped**
