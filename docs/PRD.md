# Product Requirements Document
# Variance Risk Premium (VRP) Options Screener & Trade Recommendation Engine
**For Individual Use — Free APIs Only — No Automated Trading**

Version: 1.0
Date: 2026-03-06
Status: Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Core Concepts & Statistical Foundation](#3-core-concepts--statistical-foundation)
4. [Goals & Non-Goals](#4-goals--non-goals)
5. [Functional Requirements](#5-functional-requirements)
6. [Statistical Edge Engine (Hyper-Optimized)](#6-statistical-edge-engine-hyper-optimized)
7. [Free Data Sources](#7-free-data-sources)
8. [Technical Architecture](#8-technical-architecture)
9. [UI/UX Specification](#9-uiux-specification)
10. [Risk Management Framework](#10-risk-management-framework)
11. [Trade Recommendation Specification](#11-trade-recommendation-specification)
12. [Fundamentals Scoring for Assignment Quality](#12-fundamentals-scoring-for-assignment-quality)
13. [Implementation Phases](#13-implementation-phases)
14. [Success Metrics](#14-success-metrics)
15. [Appendix: Statistical Model Details](#15-appendix-statistical-model-details)

---

## 1. Executive Summary

This product is a local, Python-based application for a solo options trader to systematically identify and evaluate **Variance Risk Premium (VRP)** opportunities across US-listed stocks and ETFs. The VRP — the persistent spread between implied volatility (IV) and subsequently realized volatility (RV) — represents one of the most empirically robust and well-documented sources of edge in equity derivatives markets.

The application will:
- Continuously screen a configurable universe of stocks/ETFs for elevated, statistically-significant VRP
- Score each candidate on fundamental quality (desirability if assigned)
- Explain *why* a premium exists for each candidate using multi-factor attribution
- Generate hyper-optimized, statistically-grounded trade recommendations (structure, strike, DTE, entry, exit, position sizing)
- Provide a strict go/no-go decision with explicit rationale
- Enable on-demand analysis of any user-supplied ticker

All data is sourced from free, public APIs. The application does **not** execute trades.

---

## 2. Problem Statement & Motivation

### The Opportunity
Academic and practitioner research consistently shows that equity options are systematically overpriced relative to realized volatility. Sellers of options collect the VRP as compensation for bearing variance risk — the risk that realized volatility will exceed implied volatility. In equity markets, this premium averages 2–5 volatility points historically (IV typically running 4–6% above RV on SPY).

### The Problem for Individual Traders
1. **Discovery**: There are thousands of optionable stocks. Manually identifying where VRP is statistically elevated, persistent, and currently attractive is a multi-hour daily task.
2. **Contextualization**: Not all VRP is equal. A high VRP during a known event window (earnings, FDA decision) is *explained* — the excess IV is rational. A high VRP in a quiet, stable-earnings stock is a genuine structural premium.
3. **Assignment Risk**: Short options can result in assignment. Without fundamental vetting, a trader may end up holding a poor-quality stock.
4. **Over-trading**: VRP is not always present. Trading during low-VRP regimes destroys edge. A systematic go/no-go prevents this.
5. **Risk Sizing**: Without quantitative position sizing, even correct premium-selling signals lead to ruin via over-leverage during tail events.

### The Solution
A systematic, statistically rigorous screener that transforms raw market data into actionable, risk-managed trade recommendations grounded in the best available statistical methods — accessible to a solo trader with a standard laptop and free data.

---

## 3. Core Concepts & Statistical Foundation

### 3.1 Variance Risk Premium (VRP) Defined

```
VRP(t, τ) = IV(t, τ) − E[RV(t, t+τ)]
```

Where:
- `IV(t, τ)` = Implied volatility for tenor τ observed at time t (extracted from ATM options)
- `E[RV(t, t+τ)]` = Expected realized volatility over the same forward period
- `τ` = Time horizon (e.g., 21 trading days ≈ 30 calendar days)

The VRP is positive when options sellers receive more than fair compensation for variance risk. A persistently positive historical VRP with high consistency is the core signal.

### 3.2 Why VRP Exists (Premium Drivers)

VRP has multiple structural drivers — each is quantifiable and should be attributed:

| Driver | Description | Measurable Proxy |
|--------|-------------|-----------------|
| **Hedging demand** | Institutions pay for downside protection regardless of price | Put/Call OI skew, skew slope |
| **Left-tail fear** | Market prices in more crash risk than history warrants | Implied skew vs realized skew |
| **Uncertainty premium** | Market uncertainty about future vol causes IV to exceed RV | VIX/VX term structure slope |
| **Liquidity premium** | Illiquid options require risk premium for market makers | Bid-ask spread, OI |
| **Jump risk premium** | Fear of large discrete jumps inflates IV | IV implied kurtosis vs historical |
| **Inventory risk** | Market makers hedge imperfectly, demand spread | Dealer positioning proxies |

### 3.3 Key Volatility Metrics

- **Implied Volatility (IV)**: Volatility implied by option market prices via BSM inversion
- **Realized Volatility (RV)**: Historical annualized volatility of returns over lookback window
- **IV Rank (IVR)**: `(Current IV − 52W Low IV) / (52W High IV − 52W Low IV)` — where is IV in its annual range?
- **IV Percentile (IVP)**: % of days in past year where IV was lower than today — more robust than IVR
- **VRP Percentile**: Where is the current VRP spread relative to its own historical distribution?
- **VRP Sharpe**: Historical risk-adjusted return of selling premium on this underlying
- **RVOL Forecast**: Forward-looking realized vol estimate using multiple models

---

## 4. Goals & Non-Goals

### Goals
- [G1] Screen configurable universe of stocks/ETFs daily for VRP opportunities
- [G2] Score each candidate on VRP magnitude, consistency, statistical significance, and fundamentals quality
- [G3] Attribute each VRP signal to specific drivers (hedging demand, skew, etc.)
- [G4] Generate specific, actionable trade recommendations with entry/exit rules
- [G5] Provide explicit, rigorous risk management (position sizing, stop logic, portfolio limits)
- [G6] Render a clear go/no-go decision backed by statistical evidence
- [G7] Support on-demand analysis of any user-input ticker
- [G8] Refresh data on demand and/or on schedule
- [G9] Use only free, publicly accessible data APIs
- [G10] Run fully locally on a standard laptop

### Non-Goals
- Automated trade execution (any exchange or broker API)
- Real-time streaming data (delayed data acceptable for analysis)
- Portfolio management / P&L tracking
- Backtesting engine (Phase 2 consideration)
- Multi-leg complex strategy optimization beyond 4-legged spreads
- Earnings play specialization (VRP during earnings is different — flag but de-prioritize)
- Crypto or futures options

---

## 5. Functional Requirements

### 5.1 Market Scanner / Screener

#### 5.1.1 Universe Definition
The user configures a watchlist of tickers. Pre-loaded default universes:
- **ETF Core**: SPY, QQQ, IWM, GLD, SLV, TLT, HYG, XLF, XLE, XLK, XLV, ARKK, EEM, EFA
- **High-Liquidity Stocks**: Top 100 S&P 500 by options volume (pre-seeded list, user-editable)
- **User Custom**: Any tickers the user adds manually

#### 5.1.2 Scanner Output Table
The scanner produces a sortable, filterable table with the following columns:

| Column | Description | Source |
|--------|-------------|--------|
| Ticker | Symbol | — |
| Price | Last price | yfinance |
| Market Cap | For fundamental filtering | yfinance |
| IV (30d) | 30-day ATM implied volatility | yfinance options |
| RV (21d) | 21-day close-to-close realized vol | yfinance history |
| RV (HV) | Best-estimate realized vol (multi-estimator) | Calculated |
| VRP | IV − RV spread (annualized vol points) | Calculated |
| VRP %ile | VRP vs 1-year history | Calculated |
| IVR | IV Rank (52-week) | Calculated |
| IVP | IV Percentile (252-day) | Calculated |
| Skew | 25Δ put skew (extra premium in puts) | yfinance options |
| Term Struct. | IV30 vs IV60 slope | yfinance options |
| VRP Signal | Composite VRP score (0–100) | Model |
| VRP Persist. | Historical VRP win rate (%) | Calculated |
| Vol Regime | Current market vol regime | VIX-based |
| Earnings Risk | Days to next earnings | yfinance |
| Fundamental Score | Assignment quality score (0–100) | Fundamentals model |
| Composite Score | Weighted composite (VRP + fundamentals) | Model |
| Rec. Trade | Suggested structure | Engine |
| VRP Edge | Expected P&L per day of theta | Model |

#### 5.1.3 Scanner Filters (Default)
The default scan excludes:
- Tickers with earnings within 14 calendar days (configurable; flag separately, don't exclude)
- Tickers with IV < 15% (insufficient premium for meaningful risk/reward)
- Tickers with IVR < 30% (IV not elevated historically)
- Tickers with average daily options volume < 500 contracts (liquidity floor)
- Tickers with bid-ask spread on ATM options > 15% of mid-price (too wide to fill efficiently)
- Tickers with VRP Percentile < 40th percentile (below median historical premium)

#### 5.1.4 Refresh
- Manual "Refresh All" button
- Optional auto-refresh interval (15 min, 30 min, 1 hr) — configurable
- Refresh timestamp visible per ticker
- Data staleness indicator

---

### 5.2 Individual Ticker Analysis

When the user inputs a ticker or clicks a screener row, a full analysis panel renders with:

#### 5.2.1 Volatility Dashboard
- IV term structure curve (IV vs DTE across all available expirations)
- IV30/IV60/IV90 current vs 1-year history (line chart)
- RV21/RV30/RV60 current vs 1-year history
- VRP = IV − RV plotted historically (shaded area chart)
- VRP percentile gauge
- IV Rank gauge
- IV Percentile gauge
- Current volatility regime annotation

#### 5.2.2 Skew Analysis
- Put-call skew by expiration (25Δ put IV − 25Δ call IV)
- Skew vs historical average
- Skew interpretation: flat skew = balanced hedging demand, steep skew = fear premium dominates

#### 5.2.3 VRP Attribution
For each signal present, a labeled panel explains:
- "High IVR (72nd percentile): IV is elevated relative to its annual range"
- "Persistent VRP (78% of prior 30d had positive VRP): premium collection has been reliable"
- "Steep put skew (+4.2 vol pts at 25Δ): market paying extra for downside protection"
- "VX term structure in contango: macro vol expectations stable, supporting short vol"
- "Earnings 47 days away: no near-term event risk in this expiration cycle"

#### 5.2.4 Correlated Asset Comparison
- Show VRP of correlated assets (sector peers, same ETF basket)
- If SPY's VRP is depressed but XLF's is elevated, surface this as interesting
- Correlation-adjusted VRP: is this ticker's VRP high relative to its beta-adjusted implied VRP?

#### 5.2.5 Historical VRP Strategy Performance
- Simulated historical P&L of mechanically selling 30Δ put 30 DTE on this underlying each month
- Win rate, average P&L per trade, max drawdown, Sharpe ratio
- Compare to SPY baseline (excess premium alpha)

---

### 5.3 Trade Recommendation Engine

For each qualifying ticker, the engine outputs:

#### 5.3.1 Go / No-Go Decision
A binary recommendation with a confidence level (Low / Medium / High) and a one-paragraph rationale. No-go is issued when:
- VRP is not statistically elevated (< 40th percentile of 1-year history)
- Earnings are within the option expiration window being considered
- Implied skew is extreme, suggesting informed options buying (possible unknown event)
- Market regime is extreme fear (VIX > 35 with spiking VVIX) — do not short vol into tail risk
- Liquidity is insufficient (wide spreads make execution unfavorable)
- Fundamental score is below threshold for CSP (assignment risk unacceptable)

#### 5.3.2 Recommended Trade Structure

| Structure | When Recommended |
|-----------|-----------------|
| **Cash-Secured Put (CSP)** | High fundamentals score, elevated VRP, willing to own the stock, IVR > 40 |
| **Covered Call (CC)** | User already owns shares; elevated call premium |
| **Short Put Spread (PCS)** | High VRP but fundamental score borderline, or position too large for CSP |
| **Short Strangle** | Elevated VRP on both sides, flat skew, stable underlying |
| **Iron Condor** | Elevated VRP, range-bound expectation, prefer defined risk |
| **Short Call Spread** | Unusual call skew spike, limited directional exposure desired |

#### 5.3.3 Strike Selection
- Target 20–30Δ puts as default — this delta range has the highest VRP per unit of risk
- Adjust based on VRP percentile: > 80th → widen to 30Δ; < 50th → tighten to 20Δ
- Apply Kelly-optimal delta calculation: maximize expected log growth
- For strangles: symmetric 16Δ default unless skew asymmetric

Recommendation includes the specific strike (e.g., "Sell the $145 put (28Δ)").

#### 5.3.4 DTE Selection
- Preferred window: 30–45 DTE (best theta/vega ratio, documented in literature)
- Adjust to avoid expirations spanning earnings/FOMC/known binary events
- Output: specific expiration date with rationale

#### 5.3.5 Entry Rules
- Enter at or near IV midpoint (avoid paying > 10% above mid)
- Preferred time: first 2 hours of session (after open volatility settles)
- Prefer entry on minor intraday IV spike (sell into fear pops)
- VIX condition: prefer when VIX is at daily upper range
- Confirmation level: note key support/resistance levels for directional context

#### 5.3.6 Exit Rules

**Profit Target**: 50% of max premium received (default; user-configurable at 25%/50%/75%)

**Stop Loss (Hard)**:
- 200% of premium received (close if option value triples) — OR
- Delta stop: exit if short put reaches 50Δ (has gone ATM)

**Time Stop**: At 21 DTE, close or roll regardless of P&L if between 0%–50% profit

**Roll Rules**:
- At or near stop at > 21 DTE: roll down-and-out (lower strike, further expiration) for credit
- Roll only if additional credit received is meaningful (> $0.25/share)

---

### 5.4 Risk Management Module

Governs position sizing and portfolio constraints. Full specification in Section 10.

---

## 6. Statistical Edge Engine (Hyper-Optimized)

This section defines the analytical core. Every method is chosen for maximum statistical efficiency.

### 6.1 Realized Volatility Estimation — Multi-Estimator Approach

Close-to-close (CC) variance is the noisiest estimator — it uses only 1 data point per day. The engine computes four estimators and uses the most appropriate:

#### 6.1.1 Close-to-Close (Baseline)
```
σ²_CC = (252/N) Σ (ln(C_t / C_{t-1}))²
```
Used for: benchmark, comparison only.

#### 6.1.2 Parkinson Estimator (~5x more efficient than CC)
```
σ²_PK = (252 / (4N·ln2)) Σ (ln(H_t / L_t))²
```
Uses daily high-low range. Efficient when no jumps at open/close.

#### 6.1.3 Garman-Klass Estimator (~8x more efficient)
```
σ²_GK = 252/N Σ [0.5·(ln(H/L))² − (2ln2−1)·(ln(C/O))²]
```
Adds open and close information. Best when overnight gaps are small.

#### 6.1.4 Yang-Zhang Estimator (Most Complete — handles gaps + drift)
```
σ²_YZ = σ²_overnight + k·σ²_RS_open + (1−k)·σ²_RS_close
```
Where `k = 0.34 / (1.34 + (N+1)/(N-1))` and RS is Rogers-Satchell component.

**Primary estimator**: Yang-Zhang. Display "HV Best" as average of YZ and GK.

**Lookback windows**: 10d, 21d, 30d, 60d for all estimators. Primary comparison: 21d RV vs 30d IV.

### 6.2 Implied Volatility Extraction

For each ticker:
1. Pull all options chains from yfinance for available expirations
2. Calculate midpoint of bid-ask per option; discard zero-bid or zero-OI options
3. BSM-invert each option price to extract per-strike IV using `scipy.optimize.brentq`
4. Interpolate ATM IV at current spot using two nearest strikes (moneyness space)
5. Standardize to IV30: interpolate between expirations bracketing 30 calendar days
6. Optional: fit polynomial or SABR to smooth the IV smile before extracting metrics

### 6.3 VRP Calculation Pipeline

```python
# Core VRP (annualized vol points)
VRP_current = IV30_atm - RV21_yang_zhang      # primary (matched tenors)
VRP_alt     = IV30_atm - RV30_yang_zhang      # alternative (same horizon)

# Historical VRP series (252 trading days rolling)
VRP_history[t] = IV30_atm[t] - RV21_yz[t]

# VRP Percentile
VRP_pctile = percentileofscore(VRP_history[-252:], VRP_current)

# VRP Persistence (% of last 30 sessions where VRP was positive)
VRP_persist_30d = (VRP_history[-30:] > 0).mean()

# VRP Z-score
VRP_zscore = (VRP_current - VRP_history[-252:].mean()) / VRP_history[-252:].std()

# VRP Sharpe (annualized risk-adjusted premium)
daily_vrp = VRP_history  # the VRP series IS the daily premium P&L analog
VRP_sharpe = daily_vrp.mean() / daily_vrp.std() * sqrt(252 / 21)
```

### 6.4 IV Rank & Percentile

```python
# IV Rank: position in 52-week range (point-in-time, sensitive to outliers)
IVR = (IV_current - IV_52w_min) / (IV_52w_max - IV_52w_min)

# IV Percentile: fraction of past 252 days with lower IV (more robust)
IVP = percentileofscore(IV_history_252d, IV_current) / 100

# Both displayed; flag divergence (e.g., IVR=40% but IVP=75% implies recent spike)
```

### 6.5 Skew Metrics

```python
# 25-Delta Put-Call Skew
skew_25d = IV_put_25d - IV_call_25d

# Skew Z-score vs 1-year history
skew_zscore = (skew_25d - skew_history.mean()) / skew_history.std()

# Interpretation:
# High positive skew: hedging demand premium dominates (less structural, more event-driven)
# Flat skew: balanced demand → structural VRP more likely (better signal quality)
# Negative skew: unusual (call buyers active, e.g., meme, M&A) → reduce priority

# Skew slope (convexity)
skew_slope = (IV_put_25d - IV_put_10d) / 15  # vol points per delta unit
```

### 6.6 Term Structure Analysis

```python
# IV term structure slope (standard: IV30 vs IV60)
term_slope = IV60 - IV30          # positive = contango (normal), negative = backwardation
term_slope_norm = term_slope / IV30

# Historical percentile of term slope
term_slope_pctile = percentileofscore(term_slope_history, term_slope)

# Interpretation:
# Contango: long-dated IV > near IV → near-term premium elevated → favorable for short-term selling
# Backwardation: near-term fear spike → excellent premium but heightened risk; use tighter stops
```

### 6.7 Macro Regime Detection

```python
# VIX-based regime classification
regimes = {
    (0,  15): ("Low Vol",       0.50, "Reduce size — insufficient premium"),
    (15, 20): ("Normal",        1.00, "Ideal — consistent premium, normal sizing"),
    (20, 28): ("Elevated",      1.25, "Higher premium — increase size modestly"),
    (28, 35): ("High",          0.75, "Premium rich but tail risk elevated — smaller size"),
    (35, 99): ("Crisis",        0.00, "DO NOT short volatility — close existing positions"),
}

# VVIX override: if VVIX Z-score > 2.0, mark "Regime Uncertain" regardless of VIX level
vvix_zscore = (vvix - vvix_252d_mean) / vvix_252d_std

# VIX term structure (contango vs backwardation via ^VIX3M - ^VIX)
vix_term_slope = VIX3M - VIX  # positive = normal (futures in contango)
```

### 6.8 Composite VRP Score (0–100)

```
VRP_Score = (
    0.25 × normalize(VRP_pctile)       +   # Core: magnitude vs history
    0.15 × normalize(VRP_persist_30d)  +   # Reliability: recent persistence
    0.15 × normalize(IVP)              +   # IV elevation signal
    0.15 × normalize(clip(VRP_zscore)) +   # Statistical significance
    0.10 × normalize(skew_25d)         +   # Structural driver attribution
    0.10 × normalize(term_slope_pctile)+   # Macro support
    0.05 × normalize(liquidity_score)      # Execution quality
) × 100 × (1 − event_risk_penalty)        # Earnings/event discount
```

### 6.9 Correlated Asset VRP Analysis

```python
# Beta-adjusted VRP: how much of this stock's VRP is just index VRP?
beta = ticker_info['beta']
excess_vrp = stock_vrp - (beta * spy_vrp)

# Interpretation:
# excess_vrp >> 0: stock has structural premium beyond SPY exposure (strong signal)
# excess_vrp ≈ 0: premium explained entirely by market beta (weaker signal)
# excess_vrp < 0: stock IV is cheap relative to beta-implied (avoid selling)

# Display sector ETF VRP alongside individual ticker VRP for context
```

### 6.10 Kelly Criterion — Theoretically Optimal Position Sizing

```python
# Historical win rate from VRP persistence
p_win = VRP_persist_30d  # fraction of periods where premium was collected

# From historical strategy simulation on this underlying
avg_win = premium_received * profit_target_pct  # e.g., 50% of credit received
avg_loss = max_risk  # spread width − credit (defined risk) or 2× credit (naked)

# Full Kelly
kelly_f = (p_win / avg_loss - (1 - p_win) / avg_win)

# 25% Fractional Kelly (standard risk-management adjustment — prevents ruin)
position_fraction = max(0, kelly_f * 0.25)
position_dollars = portfolio_value * position_fraction
```

### 6.11 Expected Value Calculation

```python
# Probability of profit from option delta
pop = 1 - abs(delta_short_strike)

# EV at expiration
EV_expiry = premium_received * pop - (max_loss - premium_received) * (1 - pop)

# EV per calendar day (daily edge rate)
EV_per_day = EV_expiry / DTE

# EV as % of capital required
EV_pct = EV_expiry / capital_required * 100

# All three should be positive for a GO signal
# EV_expiry > 0 and EV_pct > 0.5% is a strong threshold
```

### 6.12 Statistical Significance of VRP Persistence

```python
from scipy import stats

vrp_series = historical_vrp_252d

# Binomial test: H₀: P(VRP > 0) = 0.5 (random)
n_positive = (vrp_series > 0).sum()
n_total = len(vrp_series)
p_value = stats.binom_test(n_positive, n_total, 0.5, alternative='greater')

# Statistically significant VRP persistence: p < 0.05
is_statistically_significant = p_value < 0.05

# Mean reversion half-life (Ornstein-Uhlenbeck via AR(1))
from scipy.stats import linregress
slope, _, _, _, _ = linregress(vrp_series[:-1], vrp_series[1:])
half_life_days = -np.log(2) / np.log(slope)
# If half_life >> DTE: VRP won't persist through trade duration — reduce score
```

---

## 7. Free Data Sources

All data is free and publicly accessible. No paid subscriptions required.

### 7.1 yfinance (Primary — Python Library)
- **Install**: `pip install yfinance`
- **Auth**: None required
- **Rate limit**: Unofficial; practical limit ~2000 calls/hour with small delays between calls
- **Provides**:
  - `.option_chain(date)`: calls and puts with bid, ask, lastPrice, impliedVolatility, delta, openInterest, volume
  - `.history(period="1y")`: daily OHLCV
  - `.info`: marketCap, trailingPE, forwardPE, beta, dividendYield, profitMargins, debtToEquity, revenueGrowth, priceToBook, currentRatio, earningsDate
  - Tickers: `^VIX`, `^VVIX`, `^SKEW`, `^VIX3M`, `^VIX6M` for macro regime signals
- **Use for**: Everything except risk-free rates

### 7.2 FRED API (Federal Reserve — Free with API Key)
- **Auth**: Free registration at fred.stlouisfed.org → API key
- **Rate limit**: 120 requests/minute
- **Install**: `pip install fredapi`
- **Key series**:
  - `DGS3MO` — 3-month T-Bill yield (BSM risk-free rate)
  - `DGS1` — 1-year yield
  - `VIXCLS` — VIX daily close history
  - `T10Y2Y` — 10Y-2Y yield spread (macro regime indicator)
  - `DTWEXBGS` — Dollar index (cross-asset macro context)
- **Use for**: Risk-free rate input to BSM, VIX long history, macro overlays

### 7.3 CBOE Public Endpoints
- **Auth**: None
- **Key endpoints** (verify availability; these are publicly documented):
  - `https://cdn.cboe.com/resources/volatility/VIX_History.csv` — full VIX history
  - `^VIX`, `^VVIX`, `^SKEW`, `^VIX3M` accessible via yfinance as backup
- **Use for**: Long-history VIX for regime calibration

### 7.4 SEC EDGAR (Company Facts API)
- **Auth**: None (free, User-Agent header required)
- **Rate limit**: 10 requests/second
- **Endpoint**: `https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json`
- **Use for**: Revenue, net income, total debt, cash — detailed fundamentals when yfinance data is sparse
- **Python**: `requests` library with `{'User-Agent': 'YourName your@email.com'}` header

### 7.5 Alpha Vantage (Free Tier — Use Sparingly)
- **Auth**: Free API key at alphavantage.co
- **Rate limit**: 25 requests/day (severely limited)
- **Install**: `pip install alpha_vantage`
- **Use for**: Earnings calendar supplementation, income statement history as fallback
- **Strategy**: Cache aggressively (24h+ TTL); use only when yfinance data is missing

### 7.6 Polygon.io (Free Tier — Supplement)
- **Auth**: Free API key at polygon.io
- **Rate limit**: 5 requests/minute (free tier)
- **Use for**: Cross-validation of options data; additional Greeks when yfinance returns gaps
- **Strategy**: Use as fallback/cross-check only due to tight rate limits

### 7.7 Local Caching Strategy (SQLite)
All fetched data is persisted in a local SQLite database with TTL:

| Data Type | Cache TTL |
|-----------|-----------|
| Options chains | 15 minutes |
| Price history (OHLCV) | 1 hour |
| Fundamental data | 24 hours |
| VIX / VVIX / SKEW | 15 minutes |
| Risk-free rates (FRED) | 6 hours |
| Earnings dates | 12 hours |

This reduces API call volume by ~80% during repeated refreshes of the same universe.

---

## 8. Technical Architecture

### 8.1 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **UI** | Streamlit | Fast Python-native interactive dashboard; no JS needed; ideal for local tool |
| **Backend** | Python 3.11+ | Rich ecosystem for financial analytics |
| **Persistence** | SQLite via SQLAlchemy | Zero-config local caching and settings store |
| **Computation** | NumPy, SciPy, pandas | Vectorized statistical calculations |
| **Options Math** | Custom BSM + py_vollib | Black-Scholes inversion, Greeks |
| **Charts** | Plotly via `st.plotly_chart` | Interactive vol surface and historical charts |
| **Scheduling** | APScheduler | In-process auto-refresh without a separate process |
| **Data Fetch** | yfinance, fredapi, requests | Multi-source data aggregation |

### 8.2 Project Structure

```
vrp_screener/
├── app.py                        # Streamlit entry point
├── config.py                     # User configuration (universe, thresholds, portfolio size)
├── requirements.txt
│
├── data/
│   ├── cache.py                  # SQLite cache manager with TTL
│   ├── fetcher.py                # yfinance, CBOE, FRED fetchers
│   ├── options_parser.py         # Options chain parsing, IV extraction, BSM inversion
│   └── fundamentals.py           # Fundamental data aggregation (yfinance + SEC EDGAR)
│
├── analytics/
│   ├── realized_vol.py           # CC, Parkinson, Garman-Klass, Yang-Zhang estimators
│   ├── implied_vol.py            # IV surface construction, ATM IV, IV30 interpolation
│   ├── vrp.py                    # VRP metrics: percentile, persistence, Z-score, Sharpe
│   ├── skew.py                   # 25Δ skew, skew Z-score, skew slope
│   ├── term_structure.py         # IV term structure, contango/backwardation
│   ├── regime.py                 # VIX-based regime detection, VVIX overlay
│   ├── correlation.py            # Cross-asset VRP, beta-adjusted excess VRP
│   └── scoring.py                # Composite VRP score (0–100)
│
├── recommender/
│   ├── go_nogo.py                # Go/No-Go decision matrix with scoring
│   ├── structure_selector.py     # Trade structure selection logic
│   ├── strike_selector.py        # Optimal strike and DTE selection
│   ├── entry_exit.py             # Entry criteria, profit/stop/time exit rules, roll rules
│   ├── risk_sizing.py            # Kelly Criterion, fractional Kelly, portfolio limits
│   └── ev_calculator.py          # Expected value at expiry, per day, per capital
│
├── fundamentals/
│   ├── scorer.py                 # Assignment quality scoring model (0–100)
│   └── filters.py                # Hard disqualification rules for CSP assignment risk
│
└── ui/
    ├── scanner_table.py          # Main screener table with sorting/filtering
    ├── ticker_panel.py           # Individual ticker deep-dive
    ├── charts.py                 # Plotly chart components (vol surface, VRP history)
    ├── recommendation.py         # Trade recommendation card display
    └── sidebar.py                # Configuration, portfolio settings, universe editor
```

### 8.3 Data Flow (Request Lifecycle)

```
User triggers scan / enters ticker
         │
         ▼
[Cache Check] ── Hit ──► return cached data
         │ Miss
         ▼
[Data Fetcher] — parallel fetch: yfinance (options + history + info) + FRED (rates)
         │
         ▼
[Options Parser] → BSM inversion → per-strike IV → ATM IV → IV30 (interpolated)
         │
         ▼
[Realized Vol] → Yang-Zhang + Garman-Klass + Parkinson estimators
         │
         ▼
[VRP Module] → VRP current + historical series + percentile + persistence + Z-score
         │
         ▼
[Skew / Term / Regime] → additional signal extraction
         │
         ▼
[Scoring] → Composite VRP score (0–100) per ticker
         │
         ▼
[Fundamentals] → Assignment quality score (from cache, TTL 24h)
         │
         ▼
[Recommender] → Go/No-Go → Trade structure → Strike + DTE → Entry/Exit → Kelly size → EV
         │
         ▼
[Streamlit UI] → Render screener table + ticker panel + recommendation card
```

### 8.4 Parallel Fetch Design

For a 50-ticker universe, fetching sequentially is too slow. Use `concurrent.futures.ThreadPoolExecutor` to fetch all tickers in parallel:

```python
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fetch_ticker, ticker): ticker for ticker in universe}
    results = {ticker: future.result() for ticker, future in futures.items()}
```

Target: full 50-ticker refresh in < 120 seconds.

---

## 9. UI/UX Specification

### 9.1 Page Structure (3 Streamlit pages)

**Page 1: Scanner Dashboard**
```
╔══════════════════════════════════════════════════════════════════╗
║  VRP Options Screener            [Last Updated: 14:32 EST]      ║
║  [Refresh All ▶]  [Auto-refresh: 30 min ▼]  [Edit Universe ⚙]   ║
╠══════════════════════════════════════════════════════════════════╣
║  MACRO REGIME: Normal  │ VIX: 18.4  │ VVIX: 87.2  │ Slope: +1.2%║
╠══════════════════════════════════════════════════════════════════╣
║  ACTIVE FILTERS  [IVR>30% ✓] [No Earnings 14d ✓] [VRP%>40 ✓]   ║
╠══════════════════════════════════════════════════════════════════╣
║  Ticker │ Price │IV30│ RV21 │ VRP  │VRP%ile│ IVR │Score│Earnings║
║  ───────────────────────────────────────────────────────────────║
║  XLE    │ 89.2  │28.4│ 18.1 │ 10.3 │  87  │ 68% │ 82  │ 51d   ║ ← green
║  IWM    │196.5  │24.1│ 16.8 │  7.3 │  74  │ 54% │ 71  │ N/A   ║ ← green
║  AAPL   │172.0  │22.3│ 17.9 │  4.4 │  51  │ 38% │ 56  │ ⚠ 8d  ║ ← yellow
║  ...                                                            ║
║  [Click any row to open full analysis]                          ║
╚══════════════════════════════════════════════════════════════════╝
```

**Page 2: Individual Ticker Analysis**
```
╔══════════════════════════════════════════════════════════════════╗
║  XLE — Energy Select Sector SPDR ETF     [← Back to Screener]  ║
╠═══════════════════╦══════════════════════════════════════════════╣
║ VOLATILITY GAUGES ║  IV TERM STRUCTURE (line chart)             ║
║                   ║                                             ║
║ IV30:   28.4%     ║  [Plotly line: IV vs DTE for all exp.]     ║
║ RV21:   18.1%     ║                                             ║
║ VRP:   +10.3 pts  ╠══════════════════════════════════════════════╣
║ VRP %: 87th pctile║  VRP HISTORY (shaded area chart)            ║
║ IVR:    68%       ║                                             ║
║ IVP:    74%       ║  [Plotly: IV30 vs RV21, VRP shaded area]   ║
║                   ║                                             ║
║ VRP Persist: 80%  ╠══════════════════════════════════════════════╣
║ VRP Sharpe:  1.42 ║  SKEW CHART  │  TERM STRUCTURE CHART        ║
║ VRP Z-score: 1.87 ║  [Plotly]    │  [Plotly]                    ║
╠═══════════════════╩══════════════════════════════════════════════╣
║  VRP ATTRIBUTION                                                ║
║  ✅ IV at 68th IVR: elevated relative to 52-week range          ║
║  ✅ 80% VRP persistence: premium collection highly reliable      ║
║  ✅ Excess VRP vs beta-adj SPY: +3.2 vol pts (structural)        ║
║  ✅ Put skew 72nd pctile: institutional hedging demand present   ║
║  ✅ Term structure in contango: macro vol expectations stable    ║
║  ⚠  ETF (no earnings event risk — sector-level events still apply)║
╠══════════════════════════════════════════════════════════════════╣
║  FUNDAMENTAL SCORE: 85/100  [ETF — STRONG FOR ASSIGNMENT]       ║
║  Type: ETF (Energy) │ AUM: $36B │ Liquidity: Excellent           ║
╠══════════════════════════════════════════════════════════════════╣
║  TRADE RECOMMENDATION                         ██████ GO (High)  ║
║                                                                  ║
║  Structure:   Cash-Secured Put (CSP)                            ║
║  Strike:      $85 Put (27Δ) — 4.7% OTM                         ║
║  Expiration:  Apr 17, 2026 (42 DTE)                             ║
║  Mid Credit:  $1.85/share ($185/contract)                       ║
║                                                                  ║
║  METRICS                                                         ║
║  PoP: 73%  │  EV: +$67/contract  │  EV/day: +$1.60  │  EV%: 0.79%║
║                                                                  ║
║  ENTRY                                                           ║
║  Sell at $1.70+ mid │ Prefer on VIX spike │ First 2hr of session ║
║                                                                  ║
║  EXITS                                                           ║
║  Profit:   Close at $0.92 debit (50% of $1.85 credit)           ║
║  Stop:     Close if premium reaches $3.70 (200% of credit)      ║
║  Time:     Close at 21 DTE if < 50% profit target reached       ║
║  Roll:     If $85 hits 50Δ with > 21 DTE: roll to $80 strike    ║
║                                                                  ║
║  POSITION SIZING                                                 ║
║  Capital required:  $8,500 (1 contract × $85 strike × 100)      ║
║  Portfolio fraction: 1.7% of $500k → WITHIN 5% LIMIT ✅         ║
║  Kelly-optimal:      6.8% → 25% fractional: 1.7% ✅             ║
║                                                                  ║
║  RATIONALE                                                       ║
║  Energy sector IV structurally elevated due to commodity price   ║
║  uncertainty. VRP at 87th percentile with 80% persistence over  ║
║  past 30 sessions. Excess VRP of +3.2 vol pts not explained by  ║
║  SPY beta — indicates structural hedging demand beyond market    ║
║  vol. ETF structure provides immediate diversification on assign.║
╚══════════════════════════════════════════════════════════════════╝
```

**Page 3: Custom Ticker Lookup**
```
╔══════════════════════════════════════════════════════════════════╗
║  Custom Ticker Analysis                                         ║
║                                                                  ║
║  Enter ticker symbol:  [ TSLA          ] [Analyze →]            ║
║                                                                  ║
║  → Renders identical to Page 2 (Individual Ticker Analysis)     ║
╚══════════════════════════════════════════════════════════════════╝
```

### 9.2 Color Coding Convention

| Color | Meaning |
|-------|---------|
| Green | Score ≥ 70, GO signal, positive VRP, within limits |
| Yellow/Amber | Score 40–69, marginal signal, monitor |
| Red | Score < 40, NO-GO, negative VRP, limit breach |
| Orange | Warning flag (earnings near, wide spread, regime uncertainty) |
| Gray | Insufficient data, loading |

### 9.3 Sidebar Configuration Panel

```
PORTFOLIO SETTINGS
├── Portfolio Value: $50,000
├── Max Short Vol Allocation: 30%
├── Max Per-Position: 5%
└── Max Positions: 10

TRADE DEFAULTS
├── Profit Target: 50%
├── Stop Multiplier: 200%
├── Target Delta: 25Δ
└── Target DTE: 30–45 days

SCREENER FILTERS
├── Min IVR: 30%
├── Min VRP Percentile: 40th
├── Min Options Volume: 500/day
├── Earnings Exclusion Window: 14 days
└── Max ATM Bid-Ask Spread: 15%

UNIVERSE EDITOR
├── Default ETFs (pre-loaded)
├── Default Stocks (pre-loaded)
└── + Add Ticker / − Remove Ticker

AUTO-REFRESH
└── Interval: [Off / 15min / 30min / 1hr]
```

---

## 10. Risk Management Framework

### 10.1 Position-Level Rules

| Rule | Default | User-Configurable |
|------|---------|------------------|
| Max credit stop (close if premium 3× entry) | 200% of credit | Yes |
| Delta stop (naked) | Exit if short put reaches 50Δ | Yes |
| Profit target | 50% of max credit | Yes (25%, 50%, 75%) |
| Time stop | Close at 21 DTE | Yes |
| Min DTE at entry | 21 days | Yes |
| Max DTE at entry | 60 days | Yes |

### 10.2 Portfolio-Level Rules

| Rule | Default | Rationale |
|------|---------|-----------|
| Max short vol exposure | 30% of portfolio | Systemic vol spike protection |
| Max single position | 5% of portfolio | Concentration risk |
| Max single sector | 10% of portfolio | Correlated vol exposure |
| Max simultaneous positions | 10 | Manageability |
| Crisis override | No new trades if VIX > 40; alert to close | Tail risk protection |

### 10.3 Regime-Based Sizing Multipliers

| VIX Level | Regime | Size Multiplier | Note |
|-----------|--------|----------------|------|
| < 15 | Low Vol | 0.50× | Premium thin; not worth full risk |
| 15–20 | Normal | 1.00× | Baseline; standard sizing |
| 20–28 | Elevated | 1.25× | Higher premium justifies more risk |
| 28–35 | High | 0.75× | Good premium but gamma risk elevated |
| > 35 | Crisis | 0.00× | No new short-vol positions |

### 10.4 Correlation Concentration Check

When adding a new position, check correlation to existing portfolio:
- If new ticker β > 0.7 vs an existing position, count both toward the same sector bucket
- Sector bucket max: 10% of portfolio total

### 10.5 Black Swan Alert Conditions

Display prominent warning banner when any of:
- VIX > 25 AND VVIX Z-score > 2.0 (volatility of volatility spiking)
- VX futures in steep backwardation (front month futures > spot VIX by > 3 pts)
- 10Y-2Y yield spread < -0.5% (deep inversion — historical recession precursor)
- SPY down > 2% on consecutive days (trend break signal)

Actions: Reduce new position sizes by 50%, tighten stops on existing, evaluate early closure.

---

## 11. Trade Recommendation Specification

### 11.1 Go/No-Go Scoring Matrix

| Condition | Max Points | Weight |
|-----------|-----------|--------|
| VRP Percentile > 60th pctile | 2 | Required for GO |
| VRP Persistence > 60% | 2 | Strong |
| No earnings within expiration DTE | 2 | Required for GO |
| IV Percentile > 50th | 1 | Moderate |
| IVR > 40% | 1 | Moderate |
| VIX Regime = Normal or Elevated | 1 | Moderate |
| Fundamental Score > 60 (CSP only) | 2 | Required for CSP GO |
| ATM Bid-Ask spread < 10% of mid | 1 | Moderate |
| Excess VRP vs beta-adj SPY > 0 | 1 | Strong |
| VVIX < 100 (vol-of-vol calm) | 1 | Moderate |
| **Total possible** | **14** | |

**Decision thresholds:**
- ≥ 10 pts AND all "Required" conditions met → **GO (High Confidence)**
- 7–9 pts AND all "Required" conditions met → **GO (Moderate Confidence)**
- 5–6 pts → **MARGINAL — Consider with 50% reduced position size**
- < 5 pts OR any Required condition fails → **NO-GO** (show reason)

### 11.2 Trade Structure Selection Logic

```python
def select_structure(data, user):
    fund_score = data['fundamental_score']
    vrp_pctile = data['vrp_pctile']
    iv = data['iv30']
    skew = data['skew_25d']
    beta = data['beta']
    price = data['price']
    max_position = user['portfolio_value'] * user['max_position_pct']

    # Prefer CSP when fundamentals are strong and contract is affordable
    if fund_score >= 65 and (price * 100) <= max_position:
        return "Cash-Secured Put", "Strong fundamentals support assignment; position size OK for CSP"

    # Spread when contract too large or fundamentals borderline
    if fund_score >= 45 or (price * 100) > max_position:
        return "Short Put Spread", "Defined risk preferred; spread manages assignment risk and capital"

    # Strangle when both sides have elevated, symmetric IV
    if abs(skew) < 2.0 and iv > 30:
        return "Short Strangle", "Symmetric elevated IV favors two-sided premium collection"

    # Iron Condor for high IV, low-beta range-bound underlyings
    if iv > 35 and beta < 1.2:
        return "Iron Condor", "High IV + low beta suggests range-bound — capture both sides defined risk"

    return "Short Put Spread", "Default: defined risk preferred"
```

### 11.3 Strike Selection

```python
def select_strike(options_chain, vrp_pctile, base_delta=0.25):
    # Adjust delta based on VRP environment
    if vrp_pctile > 80:
        target_delta = 0.30   # premium-rich: take more delta
    elif vrp_pctile < 55:
        target_delta = 0.20   # moderate premium: stay OTM

    puts = options_chain.puts
    puts['delta_diff'] = (puts['delta'].abs() - target_delta).abs()
    optimal = puts.nsmallest(3, 'delta_diff')  # top 3 closest to target

    # Select from candidates: prefer round strike ($5 increments), sufficient OI, tight spread
    for _, row in optimal.iterrows():
        mid = (row['bid'] + row['ask']) / 2
        spread_pct = (row['ask'] - row['bid']) / mid if mid > 0 else 1
        if row['openInterest'] > 100 and spread_pct < 0.15:
            return row

    return optimal.iloc[0]  # fallback: closest delta
```

### 11.4 DTE Selection

1. Find all expirations between 21 and 60 DTE
2. Eliminate any that straddle an earnings date or known binary event
3. Prefer the expiration closest to 38 DTE (center of the 30–45 range)
4. Return the specific expiration date and DTE count

---

## 12. Fundamentals Scoring for Assignment Quality

If assigned on a short put, the trader owns the underlying. This module scores how acceptable that outcome is.

### 12.1 Scoring Components (0–100)

| Category | Factor | Weight | Scoring |
|----------|--------|--------|---------|
| **Profitability** | Net income positive (TTM) | 10% | Binary: yes=full, no=0 |
| | Profit margin | 8% | 0% → 0; 20%+ → 100 (linear) |
| | Return on Equity | 7% | 0% → 0; 20%+ → 100 |
| **Financial Health** | Debt/Equity | 10% | 0 → 100; 3.0+ → 0 (inverse linear) |
| | Current Ratio | 8% | < 1 → 0; 2+ → 100 |
| | Free Cash Flow positive | 7% | Binary |
| **Valuation** | Forward P/E in 8–30 range | 10% | In range → 100; outside → scaled penalty |
| | Price/Book | 5% | < 2 → 100; > 8 → 0 (inverse linear) |
| **Growth** | Revenue growth YoY > 0% | 10% | Positive → full; negative → scaled penalty |
| | EPS growth YoY > 0% | 5% | Binary bonus |
| **Shareholder Returns** | Dividend yield | 5% | 0% → 0; 5%+ → 100 |
| | Buyback activity | 3% | Bonus if positive buybacks |
| **Stability** | Market cap > $2B | 7% | < $500M → 0; > $10B → 100 |
| | Beta 0.5–1.5 | 5% | In range → 100; outside → scaled penalty |

**ETF override**: ETFs automatically score 85/100 (diversification = low assignment risk). Leveraged ETFs: 40/100. Inverse ETFs: 10/100 (not recommended for CSP).

### 12.2 Hard Disqualifiers (Override to NO-GO for CSP)

- Net income negative for 2+ consecutive years → NO-GO (CSP)
- Debt/Equity > 3.0 → NO-GO (CSP)
- Current Ratio < 0.5 → NO-GO (CSP)
- Market cap < $500M → NO-GO (CSP)
- Revenue declining > 20% YoY → NO-GO (CSP) with warning
- Leveraged ETF (2×/3×) → NO-GO (CSP); suggest spread instead

---

## 13. Implementation Phases

### Phase 1: Core VRP Scanner (MVP) — ~2 weeks

**Goal**: A working screener that displays IV, RV, and VRP metrics.

**Deliverables:**
- [ ] yfinance + FRED data fetcher with SQLite caching
- [ ] Yang-Zhang + Garman-Klass realized vol calculators
- [ ] BSM inversion for per-strike IV, ATM IV, IV30 interpolation
- [ ] VRP calculation: current spread, IVR, IVP
- [ ] Basic Streamlit screener table (top 20 by VRP)
- [ ] VIX-based macro regime indicator
- [ ] Manual refresh button with timestamp
- [ ] Parallel fetch for full universe in < 2 minutes

**Completion Criteria**: Screener renders a ranked table with correct IV, RV, VRP for all tickers.

---

### Phase 2: Statistical Depth — ~2 weeks

**Goal**: Full VRP signal attribution and ticker deep-dive.

**Deliverables:**
- [ ] Historical VRP percentile and persistence (252-day rolling)
- [ ] VRP Z-score, Sharpe, mean-reversion half-life
- [ ] VRP statistical significance test (binomial)
- [ ] 25Δ skew metrics and Z-score
- [ ] IV term structure (contango/backwardation slope)
- [ ] Composite VRP score (0–100) with weighted components
- [ ] Beta-adjusted excess VRP (correlated asset analysis)
- [ ] VVIX overlay for regime uncertainty
- [ ] Individual ticker panel with Plotly charts (term structure, VRP history, skew)
- [ ] VRP attribution label panel
- [ ] Fundamental scoring model (yfinance data)

**Completion Criteria**: Clicking any ticker shows full attribution and fundamentals with charts.

---

### Phase 3: Trade Recommendations — ~2 weeks

**Goal**: Complete trade recommendation with risk management.

**Deliverables:**
- [ ] Go/No-Go decision matrix (all 10 scoring factors)
- [ ] Trade structure selector (CSP / spread / strangle / condor)
- [ ] Strike selection algorithm (delta-targeted, Kelly-optimal adjustment)
- [ ] DTE selection (event-calendar-aware)
- [ ] Entry criteria specification
- [ ] Exit rules: profit target, stop loss, time stop, roll rules
- [ ] Kelly Criterion position sizing (25% fractional)
- [ ] Expected value calculation (at expiry, per day, per capital)
- [ ] Full recommendation card in UI
- [ ] Custom ticker lookup page (Page 3)

**Completion Criteria**: User sees a complete, actionable trade recommendation with position size and exit rules for any qualifying ticker.

---

### Phase 4: Polish & Automation — ~1 week

**Goal**: Production-ready local tool.

**Deliverables:**
- [ ] Auto-refresh scheduling via APScheduler
- [ ] Configuration sidebar (all parameters adjustable)
- [ ] Universe editor (add/remove tickers from UI)
- [ ] Color-coded table with regime warning banners
- [ ] CSV export of screener results
- [ ] Black Swan alert conditions and banner
- [ ] Regime-based position sizing multiplier display
- [ ] Full SKEW index integration
- [ ] Performance tuning (target < 90s for 50-ticker scan with warm cache)
- [ ] Graceful error handling for missing options data (some tickers have sparse chains)

---

## 14. Success Metrics

### Analytical Correctness
- VRP metrics match manual calculation within 0.1 vol points for any given ticker
- Yang-Zhang estimator produces lower variance than close-to-close on synthetic test data (verifiable)
- Historical VRP persistence > 70% on SPY, QQQ for the prior 2 years (empirically known)
- Go signals have VRP Percentile > 60th in ≥ 85% of instances when backfilled manually

### Performance
- Full 50-ticker universe refresh: < 120 seconds cold; < 30 seconds with warm cache
- Individual ticker analysis: < 15 seconds first load; < 5 seconds from cache
- Custom ticker lookup: < 20 seconds for any valid US equity with options

### User Experience
- All configuration accessible via sidebar (no code editing required)
- Recommendation cards include enough explanation that a trader can understand the rationale without external research
- Error states are clearly displayed (e.g., "Options chain unavailable for this ticker")

---

## 15. Appendix: Statistical Model Details

### A. Black-Scholes IV Inversion

```python
from scipy.optimize import brentq
from scipy.stats import norm
import numpy as np

def bsm_call_price(S, K, r, T, sigma):
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

def implied_vol(market_price, S, K, r, T, option_type='call'):
    try:
        if option_type == 'put':
            # Convert to call via put-call parity
            market_price = market_price + S - K*np.exp(-r*T)
        iv = brentq(lambda s: bsm_call_price(S, K, r, T, s) - market_price,
                    0.001, 5.0, xtol=1e-6)
        return iv
    except:
        return np.nan
```

### B. Yang-Zhang Volatility Estimator

```python
def yang_zhang_vol(df: pd.DataFrame, window: int = 21) -> pd.Series:
    """
    Yang-Zhang (2000) volatility estimator.
    Handles overnight gaps and drift. Most efficient OHLCV estimator.
    df: DataFrame with columns ['Open', 'High', 'Low', 'Close']
    Returns annualized volatility series.
    """
    log_oc  = np.log(df['Open'] / df['Close'].shift(1))   # overnight return
    log_co  = np.log(df['Close'] / df['Open'])              # intraday return
    log_ho  = np.log(df['High'] / df['Open'])
    log_lo  = np.log(df['Low'] / df['Open'])

    # Rogers-Satchell estimator (drift-free intraday component)
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    # Weighting constant
    k = 0.34 / (1.34 + (window + 1) / (window - 1))

    vol = np.sqrt(
        252 * (
            (1 - k) * log_co.rolling(window).var() +
            k * rs.rolling(window).mean() +
            log_oc.rolling(window).var()
        )
    )
    return vol
```

### C. Garman-Klass Estimator

```python
def garman_klass_vol(df: pd.DataFrame, window: int = 21) -> pd.Series:
    """
    Garman-Klass (1980) — ~8x more efficient than close-to-close.
    Uses OHLC; assumes zero drift (appropriate for short windows).
    """
    log_hl = np.log(df['High'] / df['Low'])
    log_co = np.log(df['Close'] / df['Open'])

    gk = 0.5 * log_hl**2 - (2*np.log(2) - 1) * log_co**2
    return np.sqrt(252 * gk.rolling(window).mean())
```

### D. IV30 Interpolation Between Expirations

```python
def interpolate_iv30(exp1_iv, exp1_dte, exp2_iv, exp2_dte, target_dte=30):
    """
    Linearly interpolate ATM IV to a standardized 30-day horizon.
    exp1 is the shorter expiration, exp2 is the longer.
    """
    if exp1_dte >= target_dte or exp2_dte <= target_dte:
        return exp1_iv if exp1_dte >= target_dte else exp2_iv

    # Calendar-day weighted interpolation (in variance space)
    var1 = exp1_iv**2 * exp1_dte
    var2 = exp2_iv**2 * exp2_dte
    var30 = var1 + (var2 - var1) * (target_dte - exp1_dte) / (exp2_dte - exp1_dte)
    return np.sqrt(var30 / target_dte)
```

### E. Binomial Test for VRP Significance

```python
from scipy.stats import binomtest

def vrp_significance(vrp_series: pd.Series):
    """
    Test whether VRP is statistically significantly positive.
    H₀: P(VRP > 0) = 0.5 (random; no persistent premium)
    H₁: P(VRP > 0) > 0.5 (persistent risk premium exists)
    """
    n_pos = (vrp_series > 0).sum()
    n_total = len(vrp_series.dropna())
    result = binomtest(n_pos, n_total, p=0.5, alternative='greater')
    return {
        'n_positive': n_pos,
        'n_total': n_total,
        'win_rate': n_pos / n_total,
        'p_value': result.pvalue,
        'is_significant': result.pvalue < 0.05
    }
```

### F. Mean Reversion Half-Life (Ornstein-Uhlenbeck)

```python
from scipy.stats import linregress

def vrp_half_life(vrp_series: pd.Series) -> float:
    """
    Estimate mean-reversion half-life of VRP via AR(1) fit.
    Returns days for VRP to revert halfway to its long-run mean.
    """
    y = vrp_series.dropna()
    slope, _, _, _, _ = linregress(y[:-1], y[1:])
    if slope <= 0 or slope >= 1:
        return np.inf  # unit root or explosive — not mean-reverting
    half_life = -np.log(2) / np.log(slope)
    return half_life
    # If half_life >> DTE: VRP may not persist through trade — reduce signal weight
```

### G. Kelly Criterion with Historical Simulation

```python
def kelly_position(premium, max_loss, win_rate, profit_target_pct=0.5, kelly_fraction=0.25):
    """
    Compute Kelly-optimal position fraction.
    premium: credit received per share
    max_loss: maximum possible loss per share (spread width - credit, or 2*credit for naked)
    win_rate: historical fraction of periods with positive VRP (VRP persistence)
    profit_target_pct: fraction of premium at which we close (e.g., 0.5 = 50% profit)
    kelly_fraction: fraction of full Kelly to use (0.25 = 25% fractional Kelly, standard)
    """
    avg_win  = premium * profit_target_pct
    avg_loss = max_loss - premium  # net loss after keeping premium
    p_win = win_rate
    p_loss = 1 - win_rate

    # Kelly formula: f* = (p_win/avg_loss) - (p_loss/avg_win)
    full_kelly = (p_win / avg_loss) - (p_loss / avg_win)
    fractional_kelly = max(0, full_kelly * kelly_fraction)
    return fractional_kelly
```

---

*End of PRD — VRP Options Screener v1.0*

---
*This document represents the complete product specification for the VRP Options Screener application. All data sources are free and publicly accessible. The application performs read-only data retrieval — no trades are placed on any API.*
