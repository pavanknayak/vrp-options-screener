# VRP Options Screener

## Overview

A **local desktop application** for individual options traders to systematically find, evaluate, and plan Variance Risk Premium (VRP) trades. Runs entirely on the user's machine — Streamlit serves a browser UI on localhost, all data stays on-device.

## Core Value

Surface statistically-significant VRP opportunities with complete, self-explaining trade plans — including written reasoning, four-scenario P&L, and Kelly-sized positions — across ~1,485 US-listed tickers, so the user spends time deciding on trades rather than hunting for them.

## Users

- Individual retail options trader with a Schwab brokerage account
- Comfortable with options mechanics (puts, spreads, collars)
- Wants edge identification + trade plans, not just raw data
- Executes all trades manually in their own broker interface

## Architecture

**Two-stage scanning pipeline:**
1. **Stage 1 (yfinance)** — bulk pre-filter all ~1,485 tickers in parallel (20 threads), compute estimated VRP and IVP, return top 175 candidates. No rate limit issues.
2. **Stage 2 (Schwab Market Data API)** — deep analysis of top 175 via live options chains. Rate-limited to 100 req/min. 175 × 4 calls = 700 calls ≈ 7 min.

**Schwab API constraint (absolute, architectural):** Market Data OAuth scope only. Zero order-routing logic. All execution is manual by the user.

**Stack:** Python 3.11+, Streamlit (local browser UI), SQLite (TTL cache), schwab-py (OAuth2), yfinance, FRED API, SEC EDGAR, NumPy/pandas/scipy, arch (GARCH), scikit-learn, Plotly, APScheduler.

## Universe (~1,485 tickers, 16 sub-tiers)

| Tier | Description | Count |
|------|-------------|-------|
| 1A | US Broad Index ETFs | ~20 |
| 1B | US Sector & Thematic ETFs | ~55 |
| 1C | International Developed ETFs | ~20 |
| 1D | India ETFs | ~8 |
| 1E | China ETFs (Spread/Collar only) | ~10 |
| 1F | EM ex-India/China ETFs | ~15 |
| 1G | Fixed Income ETFs | ~12 |
| 1H | Commodity ETFs | ~12 |
| 1I | Crypto ETFs (Spread/Collar, 2% max, no Thu/Fri) | ~10 |
| 2 | S&P 500 Large-Caps | ~500 |
| 3 | S&P MidCap 400 | ~400 |
| 4 | SmallCap 600 + Russell 2000 | ~300 |
| 5 | Micro-Cap | ~80 |
| 6A | India ADRs | ~8 |
| 6B | China ADRs (Spread/Collar only — no CSP) | ~15 |
| 7 | Rest-of-World ADRs | ~20 |

## Key Features

**Statistical Edge Engine (12 signals):**
- VRP percentile, persistence, Z-score, Sharpe (252-day history)
- Excess VRP (beta-adjusted vs SPY)
- IV Rank, IV Percentile
- 25Δ put skew + Z-score
- IV term structure slope
- Dealer Gamma Exposure (GEX) — computed from Schwab chain OI × gamma
- Put-Call Ratio (PCR) — from Schwab chain
- Vol of Vol (VoV) — rolling std of IV30
- VRP Momentum (5d/10d rate of change)
- Expected Move Ratio (ATM straddle / historical realized move)
- Jump % of implied variance (Bipower Variation)
- Composite VRP Score (0–100 weighted sum)

**RV Forecasting (ensemble):**
- HAR-RV (Heterogeneous Autoregressive — multi-scale persistence)
- GARCH(1,1) with GJR asymmetry (volatility clustering + leverage effect)
- EWMA (RiskMetrics λ=0.94 — fast-adapting)
- Yang-Zhang primary estimator (~14× efficiency vs close-to-close)

**Trade Recommendation Engine:**
- 21-point go/no-go matrix with hard disqualifiers
- 6 trade structures (CSP, Spread, Collar, Strangle, Condor, Covered Call)
- Asset-class structural mandates (crypto, China ADR, leveraged ETF restrictions)
- Four-scenario P&L (Bull/Base/Bear/Crash) with probability-weighted EV
- Fractional Kelly (25%) with regime × VoV × GEX stacked multipliers
- CVaR Monte Carlo portfolio overlay

**Reasoning Narratives (3 paragraphs per trade):**
1. Why the premium exists
2. Why to enter now vs. wait
3. What specifically could cause the trade to lose

**Fundamentals Scoring:**
- Piotroski F-Score (9 binary factors from SEC EDGAR)
- Altman Z / Z' / Z'' (by company type)
- Quality of Earnings (CFO/Net Income accrual anomaly)
- Margin of Safety (6-factor: earnings yield, P/TBV, FCF yield, interest coverage, D/E, revenue growth)

**Portfolio Monitor:**
- 60-day rolling correlation matrix (flag pairs ρ > 0.70)
- CVaR display, tail hedge recommendation
- Manual position entry (no account reads)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Streamlit on localhost = "desktop app" | No packaging complexity; Python-native; user just runs `streamlit run app.py` | Adopted |
| Schwab Market Data scope only | User's broker; best free real-time options data with brokerage account | Adopted |
| yfinance for Stage 1 bulk pre-filter | No rate limit, parallelizable, sufficient for ranking 1,485 tickers | Adopted |
| SQLite for caching | Simple, zero-config, local-only persistence; TTL-aware | Adopted |
| Ensemble RV forecast (3 models) | Reduces forecast RMSE 15–25% vs single model | Adopted |
| Crypto ETF Spread/Collar only | Weekend gap risk (24/7 underlying vs market-hours options) | Adopted |
| China ADR Spread/Collar only | VIE structure + SEC delisting risk makes assignment unacceptable | Adopted |

## Constraints

- Schwab API: read-only Market Data scope; 120 req/min hard limit
- All data free (Schwab brokerage account + yfinance + FRED + SEC EDGAR)
- Local-only: no cloud, no external server, no data egress
- No trade execution through any API
- Python 3.11+ required

## Out of Scope (v1)

- Trade execution, order routing, any broker write operations
- Real-time streaming (TTL cache: options 15 min, OHLCV 1 hr, fundamentals 24 hr)
- Portfolio P&L tracking / brokerage balance reads
- Backtesting engine
- Options on futures (VIX futures, commodity futures)

## Requirements

### Validated
(None yet — this is greenfield)

### Active
- [ ] [See REQUIREMENTS.md for full REQ-ID list]

### Out of Scope
- Trade execution — absolute constraint, architectural
- Real-time streaming — TTL cache sufficient
- Backtesting — deferred to future milestone
- Options on futures — out of universe scope

---
*Last updated: 2026-03-06 after initialization*
