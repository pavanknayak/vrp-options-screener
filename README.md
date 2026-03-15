# VRP Options Screener

A systematic options premium-selling screener that identifies statistically significant Volatility Risk Premium (VRP) opportunities across ~1,485 US-listed tickers. The application produces complete, self-explaining trade plans — including written reasoning, four-scenario P&L analysis, and Kelly-sized positions — so you spend time deciding on trades rather than hunting for them.

## What It Does

The screener exploits a well-documented phenomenon: **implied volatility (IV) systematically exceeds realized volatility (RV)** in equity options, creating a persistent premium for sellers. The application:

1. Scans ~1,485 tickers daily using a two-stage pipeline
2. Computes an ensemble realized volatility forecast (HAR-RV, GJR-GARCH, EWMA)
3. Constructs an arbitrage-checked IV surface and measures the VRP
4. Scores each opportunity across 18+ orthogonal signals
5. Gates candidates through a 21-point go/no-go matrix including fundamental health checks
6. Produces broker-ready order text (cash-secured put, vertical spread, or collar) with Kelly-optimal sizing

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| UI | Streamlit ≥ 1.36 (multi-page, `st.navigation`) |
| Options data | [schwab-py](https://github.com/alexgolec/schwab-py) — Schwab Market Data API |
| Equity/IV data | yfinance |
| Macro data | FRED API (risk-free rate, VIX history) |
| Financials | SEC EDGAR (10-K/10-Q via `data.sec.gov`) |
| Volatility models | [arch](https://github.com/bashtage/arch) (GJR-GARCH), NumPy/SciPy (HAR-RV, EWMA) |
| IV surface | SciPy Brent root-finding (BSM inversion), PCHIP monotone-cubic interpolation |
| Charts | Plotly |
| Persistence | SQLite (TTL cache + portfolio positions) |
| Scheduling | APScheduler (daily 9:45 AM ET auto-scan) |
| Numerics | NumPy, Pandas, SciPy, scikit-learn |

---

## Project Structure

```
vrp-options-screener/
│
├── app.py                          # Streamlit entry point (st.Page / st.navigation)
├── requirements.txt
│
├── analytics/                      # Core quantitative engine
│   ├── engine.py                   # Orchestrates the full analytics pipeline
│   ├── regime.py                   # VIX/VVIX regime detection (Low→Crisis, 6 states)
│   ├── iv_surface.py               # BSM IV inversion, PCHIP smile, TV interpolation
│   ├── realized_vol.py             # Yang-Zhang, Parkinson, Garman-Klass estimators
│   ├── forecasters.py              # HAR-RV, GJR-GARCH(1,1,1), EWMA ensemble
│   ├── vrp_engine.py               # 18+ VRP signals (IVP, skew, EM ratio, PCR, GEX...)
│   ├── composite_score.py          # 12-signal weighted composite score (0–100)
│   └── microstructure.py          # Dealer GEX, put-call ratio
│
├── recommendations/                # Trade recommendation pipeline
│   ├── engine.py                   # Orchestrator: structure→strikes→P&L→go/no-go→Kelly
│   ├── gonogo.py                   # 21-point go/no-go matrix (9 HARD + 12 SOFT gates)
│   ├── structures.py               # Structure selection: CSP / vertical spread / collar
│   ├── strikes.py                  # Strike & expiration selection (FOMC-aware DTE)
│   ├── pnl.py                      # 4-scenario P&L, slippage model, Kelly sizing
│   └── card.py                     # Recommendation card builder (narratives + order text)
│
├── fundamentals/                   # Four-model fundamental scoring
│   ├── engine.py                   # Orchestrator + per-tier gate enforcement
│   ├── piotroski.py                # Piotroski F-Score (9 binary factors, 0–9)
│   ├── altman.py                   # Altman Z/Z'/Z'' solvency score (auto model selection)
│   ├── quality.py                  # Quality of earnings (CFO/NI) + Margin of Safety
│   └── fomc.py                     # FOMC calendar (static, updated annually)
│
├── scanner/                        # Two-stage scan pipeline
│   ├── orchestrator.py             # Thread-safe singleton; APScheduler; Schwab fallback
│   ├── stage1.py                   # yfinance pre-filter (20 threads, 1,485 tickers→175)
│   ├── stage2.py                   # Schwab deep analysis (rate-limited, sequential)
│   └── modes.py                    # Quick refresh, event refresh, single-ticker lookup
│
├── data/                           # External data integrations
│   ├── schwab_client.py            # OAuth2 Schwab client singleton + options chain fetcher
│   ├── yfinance_fetcher.py         # OHLCV, earnings dates, options summary
│   ├── fred_fetcher.py             # Risk-free rate (10Y UST), VIX history
│   └── edgar_fetcher.py            # SEC EDGAR 10-K/10-Q financial statement parser
│
├── universe/                       # Ticker universe management
│   ├── loader.py                   # Loads tickers.json → TickerInfo dataclasses
│   └── tickers.json                # 1,485 tickers across 16 sub-tiers (1A–7)
│
├── cache/                          # SQLite TTL cache
│   └── db.py                       # Thread-safe get/set/purge; WAL mode; pickle serialization
│
├── portfolio/                      # Portfolio position tracking
│   └── db.py                       # Position dataclass, CRUD ops on vrp_cache.db
│
└── ui/                             # Streamlit pages and components
    ├── components/
    │   ├── regime_banner.py        # Live VIX/VVIX regime banner (top of every page)
    │   └── config_sidebar.py       # Configuration sidebar (all config fields + Schwab status)
    ├── pages/
    │   ├── dashboard.py            # Scanner Dashboard (13-column table, scan controls)
    │   ├── ticker_analysis.py      # Full recommendation card + 5 Plotly charts
    │   ├── custom_lookup.py        # On-demand single-ticker Stage 2 analysis
    │   ├── portfolio_monitor.py    # Position CRUD, Monte Carlo CVaR, correlation matrix
    │   └── settings.py            # Config editor, tier management, universe management
    └── charts.py                   # 5 Plotly chart builders (IV term structure, VRP history,
                                    #   skew smile, scenario P&L, GEX history)
```

---

## How It Works

### Stage 1 — Rapid Pre-filter (yfinance, ~2 min)

Runs in parallel across all ~1,485 tickers (20 worker threads):

1. Fetch 252-day OHLCV history
2. Skip if earnings fall within the 25–55 DTE options window
3. Fetch nearest-expiration options summary from yfinance
4. Apply liquidity gates: bid-ask spread < 50% of mid, OI > 10 contracts
5. Approximate VRP = `ATM_IV - realized_vol_30d`
6. Approximate IVP = percentile of ATM IV vs rolling 21-day realized vol history
7. Score = `IVP × max(VRP, 0)`

Returns the top 175 candidates by score.

### Stage 2 — Deep Analysis (Schwab, ~2–5 min)

For each of the top 175 candidates (rate-limited to 100 Schwab requests/min):

#### Analytics Pipeline

| Step | Module | What it computes |
|------|--------|-----------------|
| Regime detection | `analytics/regime.py` | VIX regime (6 states), VVIX stability, size multiplier |
| IV Surface | `analytics/iv_surface.py` | Per-expiration BSM IV inversion → PCHIP smile → total-variance interpolation → arbitrage check → IV30, IV60 |
| Realized Vol | `analytics/realized_vol.py` | Yang-Zhang (14× efficient), Parkinson (5×), Garman-Klass (8×) estimators |
| RV Forecast | `analytics/forecasters.py` | HAR-RV (OLS heterogeneous autoregression), GJR-GARCH(1,1,1) student-t (21-day horizon), EWMA (λ=0.94) → ensemble mean |
| VRP | `analytics/iv_surface.py` | `VRP = IV30_trading_day - ensemble_RV` (calendar→trading-day basis conversion applied) |
| 18+ Signals | `analytics/vrp_engine.py` | vrp_pctile, vrp_persist_30d, vrp_zscore, vrp_sharpe, excess_vrp, IVP, IVR, skew_25d, term_slope, vov_30d, em_ratio, jump_pct, GEX, PCR, momentum signals |
| Composite Score | `analytics/composite_score.py` | 12-signal weighted sum (0–100) with multiplicative penalties for event risk, jump risk, vol-of-vol instability |
| Microstructure | `analytics/microstructure.py` | Dealer gamma exposure (GEX), put-call OI ratio |

#### Fundamentals Pipeline

| Model | What it measures | Exempt tickers |
|-------|-----------------|----------------|
| **Piotroski F-Score** (0–9) | 9 binary factors across profitability, leverage, operating efficiency | ETFs, REITs, financials |
| **Altman Z'/Z''** | Solvency (distress/gray/safe zones) — auto-selects Z' (market price) or Z'' (book value) | ETFs, crypto, financials |
| **Quality of Earnings** | CFO/Net Income ratio; flags accrual anomaly and negative operating cash flow | ETFs |
| **Margin of Safety** (0–100) | 6-factor score: earnings yield premium, P/tangible BV, interest coverage, FCF yield, D/E, revenue growth | ETFs |

Combined score = `0.45 × (F-Score%) + 0.55 × MOS_score`. Per-tier gates escalate requirements from Tier 2 (S&P 500, min combined 40) to Tier 5 (micro-cap, min 75, Altman ≥ 2.99, Piotroski ≥ 7).

#### Recommendation Pipeline

1. **Structure selection** — CSP, vertical spread, or collar based on tier and asset class (China ADRs and crypto ETFs: spread/collar only)
2. **Strike selection** — nearest 30–35 DTE expiration; delta-targeted strikes; FOMC-aware DTE adjustment
3. **P&L scenarios** — four outcomes (Bull +15% / Base 0% / Bear -10% / Crash -25%) with fixed probabilities; slippage = mid × 0.75
4. **Go/No-Go matrix** — 21-point evaluation (9 HARD disqualifiers + 12 SOFT filters); fails fast on first failure
5. **Kelly sizing** — fractional Kelly (25% base) × regime multiplier × VoV multiplier × GEX multiplier, clamped to `[max_pos/4, max_pos]`
6. **Recommendation card** — three data-driven narrative paragraphs + broker-ready order text

---

## Volatility Regime System

| Regime | VIX Range | Size Multiplier | Meaning |
|--------|-----------|----------------|---------|
| Low | ≤ 15 | 0.50× | Thin premium — reduce size |
| Normal | 15–20 | 1.00× | Standard environment |
| Elevated | 20–28 | 1.25× | Rich premium — increase size |
| High | 28–40 | 0.75× | Tail risk elevated |
| Crisis | > 40 | 0.00× | Close positions, no new trades |
| VOL_UNSTABLE | VVIX Z > 2.5 | 0.25× | Vol-of-vol spike — high uncertainty |

---

## Ticker Universe — 16 Sub-tiers

| Tier | Description | Examples | CSP Allowed |
|------|-------------|---------|------------|
| 1A | US broad market ETFs | SPY, QQQ, IWM | ✓ |
| 1B | US sector ETFs | XLK, XLF, XLE | ✓ |
| 1C | US factor ETFs | VTV, MTUM | ✓ |
| 1D | Volatility ETFs | VXX, UVXY | ✓ (spread/collar) |
| 1E | Leveraged ETFs | TQQQ, SOXL | ✓ (spread/collar) |
| 1F | Bond ETFs | TLT, HYG | ✓ |
| 1G | Commodity ETFs | GLD, SLV, USO | ✓ |
| 1H | Real Estate ETFs | VNQ, IYR | ✓ |
| 1I | Thematic ETFs | ARKK, ICLN | ✓ |
| 2 | S&P 500 | AAPL, MSFT, NVDA | ✓ |
| 3 | S&P MidCap 400 | FIVE, EXLS | ✓ |
| 4 | S&P SmallCap 600 | CSWI, UFPI | ✓ |
| 5 | Micro-Cap | Various | ✓ |
| 6A | India ADRs | INFY, WIT | ✓ |
| 6B | China ADRs | BABA, JD | Spread/Collar only |
| 7 | Rest-of-World ADRs | SAP, NVO | ✓ |

---

## Go/No-Go Matrix

### HARD Disqualifiers (any one blocks the trade)

| ID | Criterion | Threshold |
|----|-----------|-----------|
| HARD-01 | VRP statistical significance | vrp_pctile < 40th percentile |
| HARD-02 | Earnings inside DTE window | Earnings date falls in 25–55 DTE range |
| HARD-03 | Positive slippage-adjusted EV | EV ≤ 0 after 75%-of-mid slippage |
| HARD-04 | IV stability | VoV Z-score > 2.5 |
| HARD-05 | Regime not Crisis | VIX > 40 |
| HARD-06 | Altman not in distress zone | Tier 2–7 with distress flag |
| HARD-07 | Jump-dominated variance | jump_pct > 50% |
| HARD-08 | China ADR structure ban | CSP on China ADR tickers |
| HARD-09 | Crypto ETF structure ban | CSP on crypto ETF tickers |

### SOFT Filters (12 additional checks)

Minimum composite scores by tier, IVP minimum (40th percentile), VRP persistence (50% of days positive), fundamental gate, GEX not severely adverse, term structure not inverted, VoV moderate in high-risk regimes, PCR not in panic territory.

---

## 5-Page Streamlit UI

### Scanner Dashboard
- Live regime banner (VIX, VVIX, T-Bill rate, GEX, size multiplier)
- 13-column sortable/filterable results table: Ticker, Tier, Score, IV30, VRP, VRP%, IVP, Persistence, Excess VRP, Skew, EM Ratio, Earnings, GO/NO-GO
- Scan controls: Full Scan, Quick Refresh (top 30), Event Refresh
- CSV export; row click → Ticker Analysis page

### Ticker Analysis
- Full recommendation card: GO/NO-GO header, trade parameters, risk levels, FOMC warning
- Three narrative paragraphs: signal context, fundamental context, entry/management guidance
- Broker-ready order text (copy-paste into Schwab)
- 5 Plotly charts: IV term structure, VRP 30-day history, skew smile, 4-scenario P&L, GEX history

### Custom Lookup
- Single-ticker on-demand Stage 2 analysis (no scan required)
- Identical recommendation card and charts as Ticker Analysis

### Portfolio Monitor
- Add/remove positions (ticker, structure, strikes, expiration, contracts, entry credit)
- Monte Carlo CVaR (10,000 samples, 30-day horizon, 95% confidence)
- 60-day rolling correlation matrix (flags ρ > 0.70 pairs)
- Short-vol exposure metric, tail hedge recommendation

### Settings
- Full configuration form (portfolio value, position limits, screening thresholds, DTE range, slippage)
- Active tiers multiselect (enable/disable any of the 16 tiers)
- Universe ticker management (add/remove tickers with tier assignment)
- Schwab connection status

---

## Installation & Setup

### Prerequisites

- Python 3.11 or higher
- A Schwab brokerage account (for Stage 2; Stage 1 runs without it)

### 1. Clone and install dependencies

```bash
git clone https://github.com/pavanknayak/vrp-options-screener.git
cd vrp-options-screener
pip install -r requirements.txt
```

### 2. Optional: Configure API keys

**Schwab (required for Stage 2 live options chain data):**

```bash
# PowerShell
$env:SCHWAB_APP_KEY = "your_app_key"
$env:SCHWAB_APP_SECRET = "your_app_secret"
```

Or set permanently via Windows System Properties → Environment Variables.

To get Schwab API credentials:
1. Go to [developer.schwab.com](https://developer.schwab.com)
2. Create an app with callback URL `https://127.0.0.1`
3. Select "Accounts and Trading Production" product
4. Wait for approval (1–3 business days)
5. Copy App Key and App Secret

**FRED API (optional — defaults to 5% risk-free rate if not set):**

```bash
$env:FRED_API_KEY = "your_fred_key"
```

Get a free key at [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)

### 3. Run the app

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`

On first launch with Schwab credentials, the app will print an OAuth URL in the terminal. Open it in a browser, authorize, paste the redirect URL back. Tokens are cached automatically for future sessions.

### 4. First scan

1. Open the app → Scanner Dashboard
2. The regime banner shows live VIX/VVIX regime
3. Click **Run Full Scan** — Stage 1 runs immediately (no Schwab needed); Stage 2 enriches with live options data if Schwab is configured
4. Results populate the table; click any row to see the full recommendation

---

## Without Schwab API Keys

The app runs fully in Stage 1-only mode:
- All ~1,485 tickers scanned via yfinance
- Approximate VRP, IVP, and composite scores shown
- A yellow banner indicates Stage 1-only mode
- GO/NO-GO evaluation requires Stage 2 (Schwab)

---

## Cache & Performance

All external API calls are TTL-cached in SQLite (`vrp_cache.db`, gitignored):

| Data | TTL |
|------|-----|
| Live Schwab options chain | 15 minutes |
| yfinance options summary | 30 minutes |
| OHLCV history | 1 hour |
| FRED rates | 6 hours |
| Earnings dates | 12 hours |
| SEC EDGAR financials | 24 hours |

A full scan of 1,485 tickers takes approximately:
- Stage 1 (yfinance, 20 parallel workers): ~2–4 minutes
- Stage 2 (Schwab, rate-limited to 100 req/min): ~2–4 minutes for top 175

Subsequent scans are faster as OHLCV and fundamentals are served from cache.

---

## Automated Scheduling

APScheduler runs automatically when the app is open:
- **9:45 AM ET, Mon–Fri:** Full scan (after market open, before most earnings releases)
- **Every 5 min, 9 AM–4 PM ET:** VIX spike check — if VIX rises ≥ 5% vs prior close, automatically triggers an event refresh of existing results

---

## Key Design Decisions

- **Read-only Schwab scope** — Market Data API only. Zero order routing. All trade execution is manual (the app produces copy-paste order text).
- **Fractional Kelly** — 25% Kelly base prevents over-sizing inherent in full Kelly during estimation error. Regime, VoV, and GEX multipliers adjust size within a `[max_pos/4, max_pos]` clamp.
- **Ensemble RV** — Three independent forecasters (HAR-RV, GJR-GARCH, EWMA) reduce single-model risk. HAR captures heterogeneous autocorrelation; GARCH captures leverage effect and volatility clustering; EWMA provides a reliable fallback.
- **PCHIP smile** — Monotone-cubic interpolation prevents spurious oscillations in the IV smile. Forward-variance arbitrage across expirations is detected and logged.
- **Calendar→trading-day IV conversion** — `IV_trading = IV_calendar × √(365/252)` ensures IV and RV are on the same annualization basis before computing VRP.
- **Tier-specific fundamental gates** — Stricter quality requirements for smaller/riskier tickers. ETFs bypass fundamentals entirely (no company financials to screen).
- **Fail-fast go/no-go** — The 21-point matrix stops at first failure, preserving computation.

---

## Disclaimer

This software is for informational and educational purposes only. It does not constitute financial advice. Options trading involves substantial risk of loss and is not suitable for all investors. Past performance of any strategy does not guarantee future results. Always consult a qualified financial advisor before making investment decisions.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
