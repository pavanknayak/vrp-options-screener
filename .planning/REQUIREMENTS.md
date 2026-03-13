# VRP Options Screener — v1 Requirements

## v1 Requirements

### DATA — Data Infrastructure
- [ ] **DATA-01**: User can launch the app with `streamlit run app.py` and it opens in the default browser on localhost
- [ ] **DATA-02**: App fetches OHLCV history (252 days) for any ticker via yfinance and caches it (TTL: 1 hr)
- [ ] **DATA-03**: App authenticates with Schwab Developer API via OAuth2 (schwab-py) using Market Data scope only; token auto-refreshes; stored locally in keyring/file
- [ ] **DATA-04**: App fetches live options chains from Schwab for 2–3 expirations bracketing 30–60 DTE
- [ ] **DATA-05**: App fetches risk-free rate (DGS3MO) and VIX history from FRED API
- [ ] **DATA-06**: App fetches fundamental financials (FCF, revenue, debt, net income, CFO) from SEC EDGAR
- [ ] **DATA-07**: All fetched data is stored in SQLite with TTL-aware cache (options chain: 15 min; OHLCV: 1 hr; fundamentals: 24 hr; FRED: 6 hr)
- [ ] **DATA-08**: App fetches earnings dates from yfinance and caches them (TTL: 12 hr)
- [ ] **DATA-09**: App maintains static FOMC calendar (updated annually) accessible without API calls

### ANALYTICS — Volatility & VRP Computation
- [ ] **ANAL-01**: App computes Yang-Zhang realized volatility over 10d, 21d, 30d, 60d windows for any ticker
- [ ] **ANAL-02**: App computes Parkinson and Garman-Klass RV estimators (secondary; displayed for context)
- [ ] **ANAL-03**: App BSM-inverts Schwab options chain mid-prices to extract per-strike implied volatility
- [ ] **ANAL-04**: App fits an arbitrage-free IV smile (PCHIP monotone cubic spline) per expiration
- [ ] **ANAL-05**: App interpolates IV30 and IV60 in total-variance space (IV² × DTE)
- [ ] **ANAL-06**: App computes HAR-RV forecast (rolling 252-day OLS; daily/weekly/monthly components)
- [ ] **ANAL-07**: App computes GARCH(1,1) with GJR asymmetry 21-day-ahead RV forecast
- [ ] **ANAL-08**: App computes EWMA (λ=0.94) RV estimate
- [ ] **ANAL-09**: App produces ensemble RV forecast = mean(HAR-RV, GARCH, EWMA)
- [ ] **ANAL-10**: App computes VRP = IV30_trading_day_annualized − ensemble_RV_forecast
- [ ] **ANAL-11**: App computes Bipower Variation and separates jump variance from diffusive variance
- [ ] **ANAL-12**: App computes all 12 VRP signals: percentile, persistence, Z-score, Sharpe, momentum (5d/10d), excess VRP, IVR, IVP, skew+Z-score, term slope, VoV, EM ratio, jump%, GEX, PCR
- [ ] **ANAL-13**: App computes GEX (Dealer Gamma Exposure) from Schwab options chain OI × gamma × 100 × spot²
- [ ] **ANAL-14**: App computes PCR (put-call ratio by OI and volume) from Schwab chain
- [ ] **ANAL-15**: App detects volatility regime from VIX level (5 regimes: Low/Normal/Elevated/High/Crisis)
- [ ] **ANAL-16**: App produces composite VRP score (0–100) weighted sum of all 12 signals

### UNIVERSE — Ticker Universe Management
- [ ] **UNIV-01**: App maintains ~1,485 tickers across 16 sub-tiers (1A–1I, 2–7) as user-editable list
- [ ] **UNIV-02**: Each ticker is assigned a tier at load time that governs liquidity filters, fundamental thresholds, and permissible trade structures
- [ ] **UNIV-03**: User can add or remove tickers from any tier via the Configuration sidebar without touching code

### SCAN — Two-Stage Scanner
- [ ] **SCAN-01**: App runs Stage 1 scan across all ~1,485 tickers in parallel (20 threads) using yfinance, computing estimated VRP and IVP for each; outputs top 175 candidates sorted by IVP × max(VRP, 0)
- [ ] **SCAN-02**: App runs Stage 2 deep analysis on top 175 candidates via Schwab API, rate-limited to 100 req/min, running all 12 signals + fundamentals + recommendation for each
- [ ] **SCAN-03**: Stage 1 runs in < 35 min cold, < 5 min warm cache; Stage 2 runs in < 25 min
- [ ] **SCAN-04**: App supports Full Scan (daily at 9:45 AM ET auto + manual), Quick Refresh (top 30, every 30 min), Single Ticker Lookup (< 30 sec), and Event Refresh (VIX +5% intraday)
- [ ] **SCAN-05**: App skips any ticker with earnings within the DTE window during Stage 1 pre-filter

### RECOMMEND — Trade Recommendation Engine
- [x] **REC-01**: App evaluates each Stage 2 candidate through a 21-point go/no-go matrix with hard disqualifiers (statistical significance, earnings, EV ≤ 0, VoV Z > 2.5, Crisis regime, Altman Z distress, jump% > 50%, China/crypto structure bans)
- [ ] **REC-02**: App selects the appropriate trade structure per tier and asset-class mandate (CSP, Spread, Collar, Strangle, Condor, Covered Call)
- [ ] **REC-03**: App selects specific strikes by Kelly-optimal delta (base 25Δ ± VRP and VoV adjustments)
- [ ] **REC-04**: App selects DTE considering FOMC calendar (avoid 2 days pre-FOMC; prefer 1 day post-FOMC)
- [ ] **REC-05**: App computes slippage-adjusted expected value (per-leg bid-ask slippage × 0.75 factor)
- [ ] **REC-06**: App generates four-scenario P&L (Bull/Base/Bear/Crash) with probability-weighted EV; crypto ETFs use wider shocks (±50% crash)
- [ ] **REC-07**: App sizes positions via 25% fractional Kelly with stacked multipliers: regime × VoV × GEX sign
- [x] **REC-08**: App outputs a complete recommendation card: structure, specific strikes, DTE, net credit, max loss, breakeven, profit target, hard stop, roll trigger, 4-scenario P&L, Kelly size, and manual order text

### REASONING — Written Trade Narratives
- [x] **REAS-01**: App generates Paragraph 1 — why the premium exists (which signals are elevated, by how much, vs history)
- [x] **REAS-02**: App generates Paragraph 2 — why to enter now vs. wait (VRP momentum direction, FOMC proximity, GEX context, VoV stability)
- [x] **REAS-03**: App generates Paragraph 3 — what specifically could cause the trade to lose (earnings risk, binary events, correlation, jump risk, macro regime)
- [x] **REAS-04**: App outputs manual order text the user can type directly into their broker

### FUND — Fundamentals & Forensic Accounting
- [ ] **FUND-01**: App computes Piotroski F-Score (9 binary factors from EDGAR: ROA, ΔROA, CFO, accrual, leverage, liquidity, dilution, margin, asset turnover)
- [ ] **FUND-02**: App computes Altman Z-Score with correct model selection (Z for manufacturers, Z' for non-manufacturers, Z'' for non-public/private analogs)
- [ ] **FUND-03**: App computes Quality of Earnings ratio (CFO / Net Income) and flags < 0.8 as accrual anomaly
- [ ] **FUND-04**: App computes Margin of Safety score (6 factors: earnings yield vs T-bill, P/TBV, FCF yield, interest coverage, D/E, revenue growth)
- [ ] **FUND-05**: App computes Combined Fundamental Score = 0.45 × (F-Score/9 × 100) + 0.55 × MOS Score
- [ ] **FUND-06**: App enforces per-tier minimum fundamental scores and hard Altman Z disqualifiers before allowing CSP structure

### PORTFOLIO — Portfolio Correlation Monitor
- [x] **PORT-01**: User can manually enter open positions (ticker, structure, expiry, strikes) in the Portfolio Monitor page
- [x] **PORT-02**: App computes 60-day rolling pairwise correlation matrix for entered positions and flags pairs ρ > 0.70
- [x] **PORT-03**: App computes 1d 99% CVaR (Conditional VaR) for the portfolio via Monte Carlo
- [x] **PORT-04**: App displays portfolio-level short-vol exposure %, position count, and tail hedge recommendation

### UI — User Interface
- [ ] **UI-01**: Scanner Dashboard displays all Stage 2 results in a sortable/filterable table (Ticker, Tier, Score, IV30, VRP, VRP%, IVP, Persistence, Excess VRP, Skew, EM Ratio, Earnings, GO/NO-GO)
- [ ] **UI-02**: Clicking any row opens a full Ticker Analysis page with recommendation card + supplementary charts (IV term structure, VRP history, skew chart, scenario P&L bar, GEX history)
- [x] **UI-03**: Custom Ticker Lookup page runs full Stage 2 analysis on any user-entered ticker on demand
- [x] **UI-04**: Configuration sidebar lets user set portfolio value, position limits, screening thresholds, slippage factors, universe tiers, and view Schwab connection status
- [x] **UI-05**: Regime banner displays at top of every page: VIX level, VVIX, regime label (color-coded), GEX, T-bill rate, regime size multiplier
- [ ] **UI-06**: User can export scanner results to CSV

---

## v2 Requirements (Deferred)

- Backtesting engine (historical signal validation)
- Automated alerts / push notifications
- Real-time streaming (current: TTL cache)
- IBKR TWS API adapter (same interface, drop-in for IBKR users)
- Options on futures (VIX futures, commodity futures options)

## Out of Scope

- **Trade execution** — absolute architectural constraint; Schwab Market Data scope cannot place orders
- **Portfolio P&L tracking** — no brokerage account balance reads of any kind
- **Delta-hedged variance swap replication** — retail execution costs make this impractical
- **Crypto spot trading** — only crypto ETFs (IBIT, ETHA, etc.) in universe; no direct BTC/ETH options

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1: Data Infrastructure | Pending |
| DATA-02 | Phase 1: Data Infrastructure | Pending |
| DATA-03 | Phase 1: Data Infrastructure | Pending |
| DATA-04 | Phase 1: Data Infrastructure | Pending |
| DATA-05 | Phase 1: Data Infrastructure | Pending |
| DATA-06 | Phase 1: Data Infrastructure | Pending |
| DATA-07 | Phase 1: Data Infrastructure | Pending |
| DATA-08 | Phase 1: Data Infrastructure | Pending |
| DATA-09 | Phase 1: Data Infrastructure | Pending |
| UNIV-01 | Phase 1: Data Infrastructure | Pending |
| UNIV-02 | Phase 1: Data Infrastructure | Pending |
| UNIV-03 | Phase 1: Data Infrastructure | Pending |
| ANAL-01 | Phase 2: Analytics Engine | Pending |
| ANAL-02 | Phase 2: Analytics Engine | Pending |
| ANAL-03 | Phase 2: Analytics Engine | Pending |
| ANAL-04 | Phase 2: Analytics Engine | Pending |
| ANAL-05 | Phase 2: Analytics Engine | Pending |
| ANAL-06 | Phase 2: Analytics Engine | Pending |
| ANAL-07 | Phase 2: Analytics Engine | Pending |
| ANAL-08 | Phase 2: Analytics Engine | Pending |
| ANAL-09 | Phase 2: Analytics Engine | Pending |
| ANAL-10 | Phase 2: Analytics Engine | Pending |
| ANAL-11 | Phase 2: Analytics Engine | Pending |
| ANAL-12 | Phase 2: Analytics Engine | Pending |
| ANAL-13 | Phase 2: Analytics Engine | Pending |
| ANAL-14 | Phase 2: Analytics Engine | Pending |
| ANAL-15 | Phase 2: Analytics Engine | Pending |
| ANAL-16 | Phase 2: Analytics Engine | Pending |
| SCAN-01 | Phase 3: Scanner Pipeline | Pending |
| SCAN-02 | Phase 3: Scanner Pipeline | Pending |
| SCAN-03 | Phase 3: Scanner Pipeline | Pending |
| SCAN-04 | Phase 3: Scanner Pipeline | Pending |
| SCAN-05 | Phase 3: Scanner Pipeline | Pending |
| FUND-01 | Phase 4: Fundamentals Engine | Pending |
| FUND-02 | Phase 4: Fundamentals Engine | Pending |
| FUND-03 | Phase 4: Fundamentals Engine | Pending |
| FUND-04 | Phase 4: Fundamentals Engine | Pending |
| FUND-05 | Phase 4: Fundamentals Engine | Pending |
| FUND-06 | Phase 4: Fundamentals Engine | Pending |
| REC-01 | Phase 5: Recommendations & Reasoning | Complete |
| REC-02 | Phase 5: Recommendations & Reasoning | Pending |
| REC-03 | Phase 5: Recommendations & Reasoning | Pending |
| REC-04 | Phase 5: Recommendations & Reasoning | Pending |
| REC-05 | Phase 5: Recommendations & Reasoning | Pending |
| REC-06 | Phase 5: Recommendations & Reasoning | Pending |
| REC-07 | Phase 5: Recommendations & Reasoning | Pending |
| REC-08 | Phase 5: Recommendations & Reasoning | Complete |
| REAS-01 | Phase 5: Recommendations & Reasoning | Complete |
| REAS-02 | Phase 5: Recommendations & Reasoning | Complete |
| REAS-03 | Phase 5: Recommendations & Reasoning | Complete |
| REAS-04 | Phase 5: Recommendations & Reasoning | Complete |
| UI-01 | Phase 6: UI & Portfolio Monitor | Pending |
| UI-02 | Phase 6: UI & Portfolio Monitor | Pending |
| UI-03 | Phase 6: UI & Portfolio Monitor | Complete |
| UI-04 | Phase 6: UI & Portfolio Monitor | Complete |
| UI-05 | Phase 6: UI & Portfolio Monitor | Complete |
| UI-06 | Phase 6: UI & Portfolio Monitor | Pending |
| PORT-01 | Phase 6: UI & Portfolio Monitor | Complete |
| PORT-02 | Phase 6: UI & Portfolio Monitor | Complete |
| PORT-03 | Phase 6: UI & Portfolio Monitor | Complete |
| PORT-04 | Phase 6: UI & Portfolio Monitor | Complete |
