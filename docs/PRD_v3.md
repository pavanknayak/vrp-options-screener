# Product Requirements Document
# Variance Risk Premium (VRP) Options Screener & Trade Planner
**For Individual Use — Hybrid Data Stack — Zero Automated Execution**

Version: 3.0
Date: 2026-03-06
Status: Final Draft

---

## Preface: Critique of v2.0 and What Changed

### What v2.0 Got Right (Preserved and Extended)
- **Slippage-adjusted EV**: Critical correction from v1.0's naive midpoint math. Extended here for multi-leg structures.
- **Forensic accounting disqualifiers**: Accrual anomaly, Altman Z-Score, inventory/receivables divergence — excellent risk controls for small-cap assignment exposure. Extended with Piotroski F-Score and Quality of Earnings ratio.
- **Collar structure**: Smart capital-preservation choice for borderline fundamentals. Fully specified here.
- **Expanded universe**: S&P 1500 + micro-caps. Extended here to ~1,700 tickers with tiered filter thresholds.
- **Binary Event Anomaly filter**: Sophisticated. Quantified with explicit thresholds here.
- **Margin of Safety valuation**: Earnings yield vs risk-free rate, TBV, interest coverage — kept in full.

### Critical Regressions from v1.0 (Restored)
v2.0 dropped the following metrics that are *the* core of the statistical edge. These are non-negotiable:
- **VRP Persistence (30d win rate)**: % of recent sessions with positive VRP. The single best predictor of whether premium collection will continue. *Absent in v2.0.*
- **VRP Z-score**: How many standard deviations is today's VRP above its 1-year mean? Needed to assess statistical significance. *Absent in v2.0.*
- **VRP Sharpe ratio**: Risk-adjusted quality of the premium stream. Distinguishes a reliable 3-pt VRP from an erratic 8-pt VRP. *Absent in v2.0.*
- **Excess VRP (beta-adjusted)**: Is this ticker's premium above what SPY beta would predict? Isolates structural/idiosyncratic premium from index drag. *Absent in v2.0.*
- **Skew metrics (25Δ put skew)**: The steepness of the put skew tells you whether VRP is driven by hedging demand (structural, persistent) or fear (temporary, event-driven). *Absent in v2.0.*
- **IV term structure slope**: Contango/backwardation. If near-term IV is elevated relative to longer-dated IV, the premium is near-term — favors shorter DTE trades. *Absent in v2.0.*
- **Full go/no-go scoring matrix**: v2.0 reduces the decision to EV_real > 0, which is necessary but not sufficient. *Absent in v2.0.*
- **Kelly Criterion position sizing**: v2.0 has no position sizing specification whatsoever. *Absent in v2.0.*
- **Exit rules**: Profit target, stop loss, time stop, roll rules. *Absent in v2.0.*
- **Macro regime detection (VIX + VVIX)**: Position size multipliers by vol regime. *Absent in v2.0.*

### Items Underspecified in v2.0 (Now Specified)
- **Calendar-day vs trading-day IV/RV scaling**: Mentioned but formula omitted. Fully specified here.
- **Collar structure**: No strike selection logic, no exit strategy, no DTE guidance. Fully specified here.
- **Multi-leg slippage**: v2.0 applies a single slippage term to the trade EV. For collars (3 legs: stock + call + put) the slippage compounds. Modeled per-leg here.
- **Binary Event Anomaly**: "Massively elevated" is not quantified. Threshold defined here as IV30 > 1.75× IV60 with no earnings in the window.
- **Schwab API rate limit problem**: 120 req/min against 1,500+ tickers for options chains is infeasible. A two-stage scanning architecture (yfinance bulk pre-filter → Schwab deep analysis for top candidates) solves this.
- **Altman Z-Score model selection**: The original Z (manufacturers) is inappropriate for most tech, financial, and service companies. Z' and Z'' variants are specified here.

### New Additions in v3.0 (Neither v1.0 nor v2.0 Had These)
- **HAR-RV forward volatility model**: Better realized vol forecast than any single historical window
- **Bipower Variation (BPV)**: Separates continuous (diffusive) variance from jump variance in RV — the diffusive VRP is more predictable and persistent; jump VRP is noise
- **Piotroski F-Score**: 9-factor binary scoring for fundamental health — excellent signal for small-cap distress detection
- **Quality of Earnings ratio (CFO/Net Income)**: Quantified version of the accrual anomaly
- **Market impact model**: Slippage scales with position size relative to daily options volume
- **Two-stage scan architecture**: yfinance for bulk screening → Schwab for top-candidate deep analysis
- **Universe tiering with per-tier filters**: Mega-cap filters differ from micro-cap filters
- **Tail hedge recommendation**: Structural portfolio-level protection
- **Portfolio VaR check**: Does adding this trade push portfolio 1-day 99% VaR above threshold?
- **ADR universe**: Liquid international ADRs with high-quality options markets

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Core Concepts & Statistical Foundation](#2-core-concepts--statistical-foundation)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Universe Definition & Tiering](#4-universe-definition--tiering)
5. [Market Scanner — Two-Stage Architecture](#5-market-scanner--two-stage-architecture)
6. [Statistical Edge Engine](#6-statistical-edge-engine)
7. [Data Sources & API Stack](#7-data-sources--api-stack)
8. [Trade Recommendation Engine](#8-trade-recommendation-engine)
9. [Fundamentals Scoring: Forensic Accounting & Margin of Safety](#9-fundamentals-scoring-forensic-accounting--margin-of-safety)
10. [Risk Management Framework](#10-risk-management-framework)
11. [UI/UX Specification](#11-uiux-specification)
12. [Technical Architecture](#12-technical-architecture)
13. [Implementation Phases](#13-implementation-phases)
14. [Success Metrics](#14-success-metrics)
15. [Appendix: Statistical Model Reference Code](#15-appendix-statistical-model-reference-code)

---

## 1. Executive Summary

This product is a local, Python-based application for a solo options trader to systematically identify, score, and plan **Variance Risk Premium (VRP)** trades across a large universe of US-listed equities, ETFs, and liquid ADRs. The VRP — the persistent spread between implied volatility (IV) and realized volatility (RV) — is one of the most empirically robust sources of edge in equity derivatives markets.

The application will:
- Screen ~1,700 tickers in two stages (bulk yfinance → Schwab deep analysis) to surface top VRP candidates
- Apply forensic accounting disqualifiers and margin-of-safety valuation to every candidate
- Decompose VRP into its structural vs. event-driven components, and into diffusive vs. jump components
- Generate statistically grounded trade recommendations: structure, strike, DTE, entry timing, exit rules, and slippage-adjusted EV
- Size all positions using fractional Kelly Criterion with regime-based multipliers
- Enforce rigorous portfolio-level risk limits (sector concentration, VaR, regime shutoff)
- Output manual order specifications — all execution is by the trader

The Schwab Developer API is used strictly in Market Data read-only mode. The application places no orders.

---

## 2. Core Concepts & Statistical Foundation

### 2.1 Variance Risk Premium (VRP) Defined

```
VRP(t, τ) = IV(t, τ) − E[RV(t, t+τ)]
```

Where:
- `IV(t, τ)` = Implied volatility at tenor τ, extracted from ATM options and standardized to a fixed horizon (e.g., 30 calendar days)
- `E[RV(t, t+τ)]` = Best estimate of forward realized volatility over the same horizon
- `τ` = Time horizon

**Key insight**: VRP is positive when options sellers are compensated for bearing variance risk. A VRP that is persistently positive, statistically significant, and above beta-adjusted index VRP is the strongest possible signal.

### 2.2 VRP Driver Attribution

Every VRP signal should be attributed to its underlying driver — this determines quality and persistence:

| Driver | Quality | Measurable Proxy |
|--------|---------|-----------------|
| **Structural hedging demand** | High (persistent) | Positive 25Δ put skew vs. historical baseline |
| **Left-tail fear premium** | Medium (mean-reverting) | Skew slope steepness, SKEW index |
| **Jump risk aversion** | Medium (episodic) | IV² − BPV (jump-separated VRP, see §6.5) |
| **Liquidity premium** | Low (noise) | ATM bid-ask spread width |
| **Event uncertainty** | Low (disappears post-event) | IV30 >> IV60 with no known event |

### 2.3 Calendar-Day vs. Trading-Day Scaling — The Critical Correction

Options price in **calendar-day** variance (weekends + holidays count); OHLCV-based RV measures **trading-day** variance. Naive comparison overstates VRP.

**Correct approach**: Convert IV to an equivalent trading-day annualization before comparing to RV.

```python
# IV is quoted as annualized vol assuming 365 calendar days of variance
# RV is computed assuming 252 trading days of variance

# Step 1: Convert IV to calendar-day variance for the specific DTE window
calendar_days_in_window = DTE  # e.g., 30 calendar days
trading_days_in_window = DTE * (252 / 365)  # ≈ 20.7 trading days

# Step 2: Express IV as trading-day annualized vol
IV_td_annualized = IV_calendar * sqrt(365 / 252)

# Step 3: Compare apples-to-apples
VRP = IV_td_annualized - RV_td_annualized  # both in trading-day vol basis

# Alternatively (equivalent): keep IV on calendar basis and convert RV to calendar basis
RV_cd_annualized = RV_td_annualized * sqrt(252 / 365)
VRP_alt = IV_calendar - RV_cd_annualized

# The screener uses Method 1 (convert IV to trading-day basis) for consistency
# with all RV estimators which output trading-day annualized vol
```

Additionally, the **weekend variance effect** applies: Friday 3-DTE options have 3 calendar days (Fri + Sat + Sun) but only 1 trading day of variance. The engine discounts Friday-expiring options' IV by `sqrt(1/3)` when computing effective IV for VRP comparison.

### 2.4 Key Metrics Reference

| Metric | Formula | Significance |
|--------|---------|-------------|
| VRP | IV_td − RV_YZ | Core signal |
| VRP Percentile | Rank of VRP_current in 252d history | Premium vs history |
| VRP Persistence | (VRP > 0).mean() over 30d | Reliability |
| VRP Z-score | (VRP − μ_VRP) / σ_VRP | Statistical significance |
| VRP Sharpe | μ_VRP / σ_VRP × √(252/21) | Risk-adjusted quality |
| Excess VRP | VRP − β × VRP_SPY | Structural vs. index premium |
| IVR | (IV − IV_52wLow) / (IV_52wHigh − IV_52wLow) | IV in annual range |
| IVP | percentileofscore(IV_252d, IV_current) | More robust than IVR |
| 25Δ Put Skew | IV_put_25Δ − IV_call_25Δ | Hedging demand premium |
| Term Slope | IV60 − IV30 | Contango/backwardation |
| Diffusive VRP | IV² − BPV | Jump-cleaned VRP (most predictable) |
| Slippage-Adj EV | EV_theoretical − Σ(leg_spread × penalty) | Real-world edge |

---

## 3. Goals & Non-Goals

### Goals
- [G1] Scan ~1,700 tickers in two stages using a rate-limit-aware architecture
- [G2] Apply a full statistical VRP signal suite including persistence, significance, and jump separation
- [G3] Attribute VRP to its structural drivers for each candidate
- [G4] Apply forensic accounting disqualifiers and margin-of-safety valuation
- [G5] Generate complete trade plans: structure, strike, DTE, entry, exit, and position size
- [G6] Compute slippage-adjusted EV with per-leg modeling for multi-leg structures
- [G7] Enforce portfolio-level risk limits (VaR, sector concentration, regime override)
- [G8] Support custom ticker lookup with full analysis
- [G9] Use Schwab Market Data API (read-only) + yfinance + FRED + SEC EDGAR
- [G10] Place zero trades through any API

### Non-Goals
- Trade execution, order routing, or broker integration beyond read-only market data
- Real-time streaming (delayed/snapshot data is sufficient)
- Portfolio P&L tracking or position management
- Backtesting engine (explicitly deferred — would require much larger scope)
- Crypto, futures, or bond options

---

## 4. Universe Definition & Tiering

The universe is divided into six tiers with different liquidity floors, fundamental requirements, and permissible trade structures. A ticker's tier determines which filters it must pass and which structures are available.

### Tier 1: Index & Macro ETFs (~50 tickers)
*Filter: ATM bid-ask < 15% of mid. No fundamental scoring required — ETFs are inherently diversified.*

**Broad Index**: SPY, QQQ, IWM, DIA, MDY, VTI, VOO
**International Developed**: EFA, VEA, EWJ (Japan), EZU (Eurozone), EWG (Germany), EWU (UK), EWC (Canada), EWA (Australia)
**International Emerging**: EEM, VWO, EWZ (Brazil), EWY (S.Korea), FXI, MCHI (China), INDA (India), EWT (Taiwan)
**Fixed Income**: TLT, IEF, SHY, LQD, HYG, JNK, TIP, AGG
**Commodities**: GLD, SLV, USO, UNG, DBC, PDBC, CORN, WEAT, SOYB
**Real Estate & Utilities**: VNQ, XLRE, XLU
**Permitted structures**: All (CSP, Covered Call, Spread, Collar, Strangle, Condor)

### Tier 2: Sector & Thematic ETFs (~40 tickers)
*Filter: ATM bid-ask < 12% of mid. Daily options OI > 500.*

**SPDR Sectors**: XLF, XLE, XLK, XLV, XLI, XLB, XLY, XLP, XLC
**Industry Leaders**: GDX, GDXJ, XBI, IBB, KRE, SMH, SOXX, ARKK, ARKG, ARKQ
**Factor ETFs**: QUAL, MTUM, VLUE, USMV, SPHQ
**Permitted structures**: All

### Tier 3: S&P 500 (~500 tickers)
*Filter: Daily options volume > 1,000 contracts; ATM bid-ask < 12% of mid; Fundamental Score > 40.*
**Permitted structures**: CSP, Covered Call, Spread, Collar, Strangle, Condor

### Tier 4: S&P MidCap 400 (~400 tickers)
*Filter: Daily options volume > 500; ATM bid-ask < 10% of mid; Fundamental Score > 50; Altman Z > 1.81.*
**Permitted structures**: Short Put Spread, Collar, Covered Call
**NOT permitted**: CSP (collar required for downside protection)

### Tier 5: S&P SmallCap 600 + Russell 2000 Select (~300 tickers)
*Filter: Daily options volume > 500; ATM bid-ask < 8% of mid; Market cap > $300M; Fundamental Score > 60; Altman Z > 2.5; Piotroski F-Score ≥ 6.*
**Permitted structures**: Zero-cost Collar only (no naked exposure)

### Tier 6: Micro-Cap Discovery (~100 tickers, IWC universe)
*Filter: Daily options volume > 1,000 (higher threshold required for fills); ATM bid-ask < 6% of mid; Market cap > $150M; Fundamental Score > 70; Altman Z > 2.99 (Safe Zone); Piotroski F-Score ≥ 7; No net losses in any of last 4 quarters.*
**Permitted structures**: Zero-cost Collar only — put MUST be purchased simultaneously with any short call

### Tier 7: Liquid ADRs (~30 tickers)
*Filter: Same as Tier 3. Additional: primary listing on NYSE/NASDAQ; ADR Level II or III only; no pending delisting review.*

**High-Quality ADRs**: TSM (Taiwan Semi), ASML (Netherlands), NVO (Novo Nordisk), SHEL (Shell), TTE (TotalEnergies), AZN (AstraZeneca), SAP (SAP SE), UL (Unilever), DEO (Diageo), HDB (HDFC Bank), BTI (British American Tobacco), SONY, PHG (Philips)
**Permitted structures**: CSP (Tier-3 equivalent treatment if fundamentals > 65), otherwise Spread/Collar

**Total scanned universe**: ~1,420 tickers initially; grows as universe lists are updated

---

## 5. Market Scanner — Two-Stage Architecture

Scanning 1,400+ tickers for full options chain data in a single pass would exceed any API's rate limits. The solution is a two-stage funnel.

### Stage 1: Bulk Pre-Filter (yfinance) — Target: ~30 min, all tickers

**What runs**: For every ticker in the universe:
1. Pull 252 days of OHLCV history → compute Yang-Zhang 21d RV
2. Pull 2 nearest options expirations → compute estimated ATM IV (from yfinance `.impliedVolatility`)
3. Compute estimated VRP = estimated IV − RV
4. Compute IVP from IV history (1 year)
5. Apply coarse liquidity filter: discard if options volume < 500/day

**Output**: Ranked list of top 150–200 tickers by IVP × VRP estimate. These advance to Stage 2.

**Why yfinance here**: No rate-limit constraints at this volume; caching means repeated runs are fast. yfinance IV is approximate (BSM-implied from last trade price) but sufficient for coarse ranking.

### Stage 2: Deep Analysis (Schwab API) — Target: ~20 min, top candidates

**What runs**: For each of the top 150–200 candidates:
1. Fetch full live options chain via Schwab Market Data (all expirations, all strikes, real-time bid/ask, actual Greeks from Schwab's model)
2. Run full BSM IV inversion on each option using live mid-price
3. Construct IV smile per expiration; extract ATM IV30 via variance-time interpolation
4. Run complete VRP signal suite (§6)
5. Fetch fundamentals from SEC EDGAR + yfinance for full forensic scoring (§9)
6. Run trade recommender (§8)

**Schwab API rate management**: 120 requests/minute. Each ticker requires ~3 calls (option chains for 2 expirations + quote). At 150 tickers × 3 calls = 450 calls → 3.75 minutes at full rate. Build in a 50% rate buffer → target 7 minutes for Schwab calls.

**Stage 2 output**: Top 20–30 fully scored candidates with complete trade recommendations.

### Refresh Schedule
| Mode | Frequency | Scope |
|------|-----------|-------|
| Full Scan | Manual or daily auto at 9:45 AM ET | Both stages, full universe |
| Quick Refresh | Manual or every 30 min | Stage 2 only (top candidates re-priced via Schwab) |
| Ticker Lookup | On-demand | Single ticker, full Stage 2 analysis |

### Binary Event Anomaly Filter

Applied in Stage 1 to disqualify structurally misleading VRP signals:

**Trigger**: IV30 > 1.75 × IV60 AND no confirmed earnings within 60 days

**Interpretation**: Near-term IV is massively elevated relative to long-dated IV with no identifiable scheduled event. This pattern indicates an *unknown* binary event (FDA PDUFA, lawsuit ruling, regulatory decision, acquisition rumor). Selling this premium is selling event risk at a price set by informed participants — the VRP is not structural.

**Action**: Disqualify from screener. Flag ticker with "Binary Event Anomaly — IV30/IV60 = X.X×. Potential unscheduled catalyst."

**Exception**: If the user manually indicates they are aware of the event and want the analysis anyway, show it in gray with a prominent red warning banner.

---

## 6. Statistical Edge Engine

### 6.1 Realized Volatility — Multi-Estimator Suite

All estimators are run over 10d, 21d, 30d, and 60d windows. **Yang-Zhang is the primary** for all VRP calculations. Display all four so the trader can see where they diverge (divergence itself is informative about recent structural breaks).

#### 6.1.1 Close-to-Close (CC) — Baseline only
```python
σ²_CC = (252/N) * np.sum(np.log(close/close.shift(1))**2)
```
Highest variance estimator. Used only as reference/sanity check.

#### 6.1.2 Parkinson — ~5× more efficient than CC
```python
σ²_PK = 252 / (4*N*np.log(2)) * np.sum(np.log(high/low)**2)
```
Uses daily range. Assumes zero drift and no overnight gaps. Good for intraday movers.

#### 6.1.3 Garman-Klass — ~8× more efficient
```python
σ²_GK = 252/N * np.sum(0.5*np.log(high/low)**2 - (2*np.log(2)-1)*np.log(close/open_)**2)
```
Adds open/close to Parkinson. Best when overnight gaps are small.

#### 6.1.4 Yang-Zhang — Most Complete (Primary)
```python
def yang_zhang_vol(df, window=21):
    log_oc  = np.log(df['Open'] / df['Close'].shift(1))   # overnight
    log_co  = np.log(df['Close'] / df['Open'])              # intraday
    log_ho  = np.log(df['High'] / df['Open'])
    log_lo  = np.log(df['Low'] / df['Open'])
    rs = log_ho*(log_ho - log_co) + log_lo*(log_lo - log_co)  # Rogers-Satchell
    k = 0.34 / (1.34 + (window+1)/(window-1))
    vol = np.sqrt(252 * (
        (1-k) * log_co.rolling(window).var() +
        k * rs.rolling(window).mean() +
        log_oc.rolling(window).var()
    ))
    return vol
```
Handles overnight gaps and drift. Primary estimator for all VRP calculations.

### 6.2 HAR-RV: Forward Realized Volatility Forecasting

Simply using recent historical RV as the forecast of future RV is suboptimal. The Heterogeneous Autoregressive Realized Variance (HAR-RV) model has superior out-of-sample performance because it captures volatility's multi-scale persistence structure.

```
RV_forecast_{t+21d} = α + β_d·RV_d_t + β_w·RV_w_t + β_m·RV_m_t + ε
```

Where:
- `RV_d` = Daily Yang-Zhang RV (1-day window)
- `RV_w` = Weekly average RV (5-day average of daily RV)
- `RV_m` = Monthly average RV (21-day average of daily RV)
- Coefficients estimated via OLS on rolling 252-day window: typically β_d ≈ 0.25, β_w ≈ 0.40, β_m ≈ 0.35

**VRP using HAR-RV forecast** is more accurate than VRP using a single historical window:
```
VRP_HAR = IV30_atm − RV_HAR_forecast
```
This is the *primary* VRP signal displayed to the user. The historical window VRP is shown as supporting context.

```python
def har_rv_forecast(rv_daily: pd.Series) -> float:
    """Forecast next-period RV using HAR model."""
    rv_d = rv_daily.iloc[-1]
    rv_w = rv_daily.iloc[-5:].mean()
    rv_m = rv_daily.iloc[-21:].mean()

    # Fit HAR on rolling 252-day window
    from sklearn.linear_model import LinearRegression
    y = rv_daily.iloc[21:]
    X = pd.DataFrame({
        'rv_d': rv_daily.shift(1).iloc[21:],
        'rv_w': rv_daily.rolling(5).mean().shift(1).iloc[21:],
        'rv_m': rv_daily.rolling(21).mean().shift(1).iloc[21:],
    })
    X = X.loc[y.index].dropna()
    y = y.loc[X.index]
    model = LinearRegression().fit(X, y)

    forecast = model.predict([[rv_d, rv_w, rv_m]])[0]
    return max(forecast, 0.01)  # floor at 1% annualized
```

### 6.3 Bipower Variation — Separating Diffusive from Jump VRP

Standard RV mixes two types of variance: **continuous (diffusive)** variance from Brownian motion, and **jump** variance from discrete price shocks. The VRP from diffusive risk is structurally persistent and predictable (reliably collected by option sellers). The jump risk premium is episodic, unpredictable, and reflects events that can cause outsized losses.

**Bipower Variation (BPV)** estimates the continuous component:
```python
def bipower_variation(returns: pd.Series, window: int = 21) -> float:
    """
    Andersen et al. (2004) Bipower Variation.
    Estimates continuous variance; insensitive to jumps.
    """
    abs_returns = returns.abs()
    # π/2 * mean(|r_t| * |r_{t-1}|) * 252
    bpv = (np.pi/2) * (abs_returns * abs_returns.shift(1)).rolling(window).mean() * 252
    return bpv.iloc[-1]

# Jump component
def jump_variation(rv: float, bpv: float) -> float:
    return max(rv**2 - bpv, 0)  # floored at zero

# Decomposed VRP
VRP_diffusive = IV30_td_annualized**2 - bpv  # variance space; convert to vol space
VRP_diffusive_vol = np.sign(VRP_diffusive) * np.sqrt(abs(VRP_diffusive))
VRP_jump = IV30_td_annualized**2 * (jump_ratio) - jump_variation
```

**Why this matters for capital preservation**:
- High jump variation on a ticker means recent large jumps inflated IV. Selling this is selling jump insurance — your stop loss may not save you if the jump recurs.
- High diffusive VRP with low recent jump variation is the cleanest, lowest-risk premium.
- The screener displays both components and flags tickers where > 30% of implied variance is jump-attributed.

### 6.4 IV Extraction from Schwab Options Chains

Using Schwab's live data (Stage 2):
1. Extract all options for the 2 expirations bracketing 30 calendar days
2. Filter: bid > 0; open interest > 100; bid-ask spread < 15% of mid
3. Compute mid-price for each option
4. BSM-invert each mid-price to extract per-strike IV: `scipy.optimize.brentq(bsm_price - market_mid, 0.001, 5.0)`
5. Fit a no-arbitrage IV smile: monotone cubic spline through put IVs for strikes below spot, call IVs above spot
6. Extract ATM IV by evaluating the fitted smile at current spot
7. Interpolate IV30: use variance-time weighted interpolation between the two bracketing expirations:

```python
def interpolate_iv30(exp1_iv, exp1_dte, exp2_iv, exp2_dte, target_dte=30):
    """Interpolate in variance-time (total variance) space — arbitrage-free."""
    tv1 = exp1_iv**2 * exp1_dte  # total variance at exp1
    tv2 = exp2_iv**2 * exp2_dte  # total variance at exp2
    tv30 = tv1 + (tv2 - tv1) * (target_dte - exp1_dte) / (exp2_dte - exp1_dte)
    return np.sqrt(tv30 / target_dte)
```

8. Apply calendar-day → trading-day conversion (§2.3) to get `IV30_td_annualized`

### 6.5 Full VRP Signal Suite

All signals computed after Stage 2 Schwab data fetch:

```python
class VRPSignals:
    vrp_har          = IV30_td - RV_HAR_forecast          # Primary
    vrp_historical   = IV30_td - RV_YZ_21d                # Legacy comparison

    vrp_pctile       = percentileofscore(vrp_1yr_history, vrp_har)
    vrp_persist_30d  = (vrp_1yr_history[-30:] > 0).mean()  # Reliability
    vrp_zscore       = (vrp_har - vrp_1yr_mean) / vrp_1yr_std
    vrp_sharpe       = vrp_1yr_mean / vrp_1yr_std * sqrt(252/21)
    vrp_significance = binomtest(n_positive, n_total, 0.5, 'greater').pvalue

    excess_vrp       = vrp_har - (beta * spy_vrp_har)     # Idiosyncratic
    vrp_diffusive    = IV30_td**2 - bpv                   # Jump-cleaned

    ivr              = (iv30 - iv52w_low) / (iv52w_high - iv52w_low)
    ivp              = percentileofscore(iv_252d, iv30)

    skew_25d         = iv_put_25d - iv_call_25d
    skew_zscore      = (skew_25d - skew_1yr_mean) / skew_1yr_std
    term_slope       = iv60 - iv30
    term_slope_pctile= percentileofscore(term_slope_1yr, term_slope)

    jump_pct         = jump_variation / (iv30**2)          # % of variance from jumps
```

### 6.6 Composite VRP Score (0–100)

```
VRP_Score = (
    0.20 × normalize(vrp_pctile, 0, 1)           +  # Magnitude vs. history
    0.15 × normalize(vrp_persist_30d, 0, 1)       +  # Reliability
    0.15 × normalize(clip(vrp_zscore, -3, 3))     +  # Statistical significance
    0.12 × normalize(ivp, 0, 1)                   +  # IV elevation
    0.12 × normalize(excess_vrp, -5, 10)          +  # Structural/idiosyncratic
    0.08 × normalize(skew_25d, -2, 8)             +  # Driver attribution
    0.08 × normalize(term_slope_pctile, 0, 1)     +  # Macro support
    0.05 × normalize(1 - jump_pct, 0, 1)          +  # Jump-clean premium
    0.05 × normalize(liquidity_score, 0, 1)           # Execution quality
) × 100
  × (1 − event_penalty)                              # Earnings window discount
  × (1 − jump_warning_penalty)                        # Jump risk discount
```

Event penalty: 0.30 if earnings within DTE window; 0.15 if earnings 1–2 cycles out.
Jump warning penalty: 0.20 if jump_pct > 30% (recent large jumps inflated IV).

### 6.7 Slippage-Adjusted EV — Multi-Leg Model

The real EV for each trade structure accounts for slippage on every leg:

```python
SLIPPAGE_FACTOR = 0.75  # User-configurable (0 = get mid; 1.0 = cross full spread)

def slippage_cost(bid, ask):
    spread = ask - bid
    return spread * SLIPPAGE_FACTOR

def ev_real(structure: str, legs: dict, pop: float, max_loss: float,
            profit_target_pct: float = 0.50) -> dict:
    """
    Compute theoretical and slippage-adjusted EV.
    legs: dict of {leg_name: (bid, ask, direction)} where direction ∈ {+1 sell, -1 buy}
    """
    # Net credit at mid
    net_credit_mid = sum(
        (bid+ask)/2 * direction
        for (bid, ask, direction) in legs.values()
    )
    # Total slippage across all legs (always paid as a cost)
    total_slippage = sum(
        slippage_cost(bid, ask)
        for (bid, ask, _) in legs.values()
    )
    net_credit_real = net_credit_mid - total_slippage

    avg_win  = net_credit_real * profit_target_pct
    avg_loss = max_loss - net_credit_real  # net of credit received
    ev_theoretical = net_credit_mid * pop - avg_loss * (1-pop)
    ev_real        = net_credit_real * pop - avg_loss * (1-pop)

    return {
        'net_credit_mid':  net_credit_mid,
        'net_credit_real': net_credit_real,
        'slippage_total':  total_slippage,
        'ev_theoretical':  ev_theoretical,
        'ev_real':         ev_real,
        'ev_per_day':      ev_real / DTE,
        'ev_pct_capital':  ev_real / capital_required * 100,
        'go':              ev_real > 0 and ev_pct_capital > 0.3,
    }
```

**Market impact model**: If position size exceeds 5% of the ticker's average daily options volume in the relevant strike/expiration, apply an additional market impact penalty of 0.5× the spread per 5% of ADV:
```python
market_impact_extra = max(0, (position_contracts / avg_daily_volume - 0.05) / 0.05) * 0.5 * spread
```

### 6.8 Macro Regime Detection

```python
REGIME_TABLE = {
    (0,  15): ("Low Vol",      0.50, "Thin premium — reduce all sizes by 50%"),
    (15, 20): ("Normal",       1.00, "Ideal: standard sizing"),
    (20, 28): ("Elevated",     1.25, "Rich premium — increase size by 25%"),
    (28, 35): ("High",         0.75, "Very rich but gamma risk elevated — reduce by 25%"),
    (35, 99): ("Crisis",       0.00, "DO NOT open new short-vol. Alert: consider closing."),
}

# VVIX override: spike in vol-of-vol signals regime instability
vvix_zscore = (vvix - vvix_252d_mean) / vvix_252d_std
if vvix_zscore > 2.0:
    regime_override = "Regime Uncertain — VVIX spiking. Reduce new positions by 50%."

# VIX term structure (proxy: ^VIX3M − ^VIX from yfinance)
vix_term_slope = vix3m - vix
# Negative (backwardation): near-term panic. Excellent premium but heightened risk.
# Positive (contango): normal. Supports short vol.
```

### 6.9 Kelly Criterion Position Sizing

```python
def kelly_size(win_rate, avg_win_per_share, avg_loss_per_share,
               portfolio_value, kelly_fraction=0.25, regime_multiplier=1.0,
               max_position_pct=0.05):
    """
    Fractional Kelly position sizing with portfolio and regime caps.
    win_rate: VRP persistence (fraction of periods with positive VRP)
    avg_win: net credit × profit_target_pct (per share)
    avg_loss: max_loss − net_credit (per share)
    """
    p = win_rate
    b = avg_win_per_share / avg_loss_per_share  # payoff ratio

    full_kelly = (p*b - (1-p)) / b
    fractional_kelly = max(0, full_kelly * kelly_fraction)

    # Apply regime multiplier (§6.8)
    adjusted_kelly = fractional_kelly * regime_multiplier

    # Hard caps
    position_fraction = min(adjusted_kelly, max_position_pct)
    position_dollars  = portfolio_value * position_fraction
    return position_fraction, position_dollars
```

---

## 7. Data Sources & API Stack

### 7.1 Source Usage by Stage

| Source | Stage | Data | Rate Limit |
|--------|-------|------|-----------|
| **yfinance** | 1 (bulk) | OHLCV, estimated IV, options volume, basic fundamentals | ~2000/hr practical |
| **Schwab Market Data API** | 2 (deep) | Live options chains, real-time Greeks, quotes | 120 req/min |
| **FRED API** | Both | Risk-free rates, VIX history, macro indicators | 120 req/min |
| **SEC EDGAR** | 2 (fundamentals) | 10-K/10-Q: revenue, FCF, debt, receivables, inventory | 10 req/sec |
| **yfinance** | 2 (fallback) | Supplement SEC EDGAR for ratios not filed quarterly | Same as above |

### 7.2 Schwab Developer API Setup

The Schwab Developer API requires:
1. A Charles Schwab brokerage account
2. Registration of a "Market Data" app at developer.schwab.com
3. OAuth2 Authorization Code flow for token generation
4. Automatic refresh token rotation (tokens expire every 30 min; refresh tokens every 7 days)

**Key endpoints used**:
- `GET /marketdata/v1/chains` — options chain with bid, ask, delta, gamma, theta, vega, OI, volume, IV
- `GET /marketdata/v1/quotes` — real-time quote for underlying
- `GET /marketdata/v1/pricehistory` — OHLCV history (redundant with yfinance; use as fallback)

**Critical constraint**: Schwab Market Data API cannot place, cancel, or modify orders. The app registers as a Market Data app only. This is enforced at the API permission level — the application literally cannot place trades even if it tried.

### 7.3 FRED API (Free — Risk-Free Rates & Macro)
- **Register**: fred.stlouisfed.org (free API key)
- **Library**: `fredapi`
- **Key series**: `DGS3MO` (3m T-Bill, risk-free rate input for BSM), `VIXCLS` (VIX history), `T10Y2Y` (yield curve), `DGS10` (10Y for earnings yield comparison)

### 7.4 SEC EDGAR (Free — Forensic Accounting Data)
- **No auth required**: `User-Agent: YourName email@domain.com` header
- **Company Facts API**: `https://data.sec.gov/api/xbrl/companyfacts/{CIK}.json`
- **Key facts pulled**: `us-gaap/NetIncomeLoss`, `us-gaap/NetCashProvidedByUsedInOperatingActivities` (CFO), `us-gaap/Revenues`, `us-gaap/InventoryNet`, `us-gaap/AccountsReceivableNetCurrent`, `us-gaap/LongTermDebt`, `us-gaap/InterestExpense`, `us-gaap/OperatingIncomeLoss` (EBIT)
- **Rate limit**: 10 req/sec. For 150 tickers → 15 seconds. Cache 24 hours.

### 7.5 Local SQLite Cache
```
Cache TTLs:
  OHLCV history          → 1 hour
  Options chain (Stage 2)→ 15 minutes
  Fundamentals (SEC/yfin)→ 24 hours
  FRED rates             → 6 hours
  VIX / VVIX / SKEW      → 15 minutes
  Earnings dates         → 12 hours
  Schwab OAuth tokens    → stored in encrypted local keystore
```

---

## 8. Trade Recommendation Engine

### 8.1 Go/No-Go Decision Matrix (14 Points)

| Factor | Points | Type |
|--------|--------|------|
| VRP Percentile > 60th | 2 | **Required** |
| HAR-VRP > 0 (premium is positive after forecast) | 1 | **Required** |
| No earnings within expiration DTE window | 2 | **Required** |
| EV_real > 0 (slippage-adjusted) | 2 | **Required** |
| Fundamental Score passes tier minimum | 2 | **Required for CSP/Stock legs** |
| VRP Persistence > 60% | 2 | Strong |
| Excess VRP > 0 (idiosyncratic) | 1 | Strong |
| IVP > 50th percentile | 1 | Moderate |
| VVIX Z-score < 2.0 (regime stable) | 1 | Moderate |
| Jump % < 30% (diffusive premium dominates) | 1 | Moderate |
| ATM bid-ask < 10% of mid | 1 | Moderate |
| Term structure: contango (IV60 > IV30) | 1 | Moderate |
| **Total possible** | **17** | |

**Decision thresholds**:
- ≥ 12 pts AND all Required conditions met → **GO (High Confidence)**
- 9–11 pts AND all Required → **GO (Moderate Confidence)**
- 6–8 pts → **MARGINAL — present with 50% reduced size and explicit caveats**
- < 6 pts OR any Required condition fails → **NO-GO (show exact reason)**

### 8.2 Trade Structure Selection

```python
def select_structure(tier, fundamental_score, vrp_score, iv30, skew_25d,
                     stock_price, portfolio_value, max_position_pct):

    max_position_dollars = portfolio_value * max_position_pct
    contract_capital_csp = stock_price * 100  # capital to secure 1 CSP

    # Tier 5 and 6: Collar ONLY — capital protection is non-negotiable
    if tier >= 5:
        return "Zero-Cost Collar", "Tier 5/6 mandate: collar-only to protect against assignment on distressed balance sheets"

    # Tier 7 ADR: treat as Tier 3 if score > 65, else spread
    if tier == 7 and fundamental_score < 65:
        return "Short Put Spread", "ADR with borderline fundamentals: defined risk only"

    # Mega/Large-cap with excellent fundamentals → CSP is preferred
    if tier <= 3 and fundamental_score >= 75 and contract_capital_csp <= max_position_dollars:
        return "Cash-Secured Put", "Strong fundamentals + large-cap: assignment is acceptable at margin of safety"

    # Mid-cap or borderline fundamentals: defined risk
    if tier == 4 or (40 <= fundamental_score < 75):
        if abs(skew_25d) < 2.0 and iv30 > 28:  # symmetric elevated IV
            return "Short Strangle", "Symmetric premium: collect on both sides with defined risk via iron condor variation"
        return "Short Put Spread", "Defined risk: spread width caps loss regardless of assignment"

    # High-priced stock where CSP is capital-inefficient
    if contract_capital_csp > max_position_dollars and fundamental_score >= 65:
        return "Short Put Spread", "Capital efficiency: stock price too high for CSP within position limits"

    # Existing holding with elevated call IV
    if existing_holding and skew_25d < 0:  # call premium elevated
        return "Covered Call", "Existing position + elevated call premium: sell covered call"

    # High IV, low-beta, range-bound: condor
    if iv30 > 35 and beta < 1.2:
        return "Iron Condor", "High IV + low beta + low skew: four-legged defined risk"

    return "Short Put Spread", "Default: defined risk structure"
```

### 8.3 Zero-Cost Collar — Full Specification

A collar = long stock + long OTM put + short OTM call. For new positions, the stock purchase and both options are entered simultaneously.

**Strike Selection Logic**:
```python
def collar_strikes(options_chain, stock_price, target_net_debit_max=0.10):
    """
    Select put and call strikes to achieve near-zero net cost.
    Net debit = put_ask - call_bid (paying a small debit is acceptable)
    target_net_debit_max: max acceptable debit per share (default $0.10)
    """
    puts  = options_chain.puts[options_chain.puts['delta'].abs() < 0.40]
    calls = options_chain.calls[options_chain.calls['delta'].abs() < 0.40]

    # Sort puts by OTM-ness (lower strike = more OTM)
    # Sort calls by OTM-ness (higher strike = more OTM)
    # Find the (put, call) pair with minimum abs(net_cost) and net_cost <= target

    best_pair = None
    best_net = float('inf')
    for _, put_row in puts.iterrows():
        for _, call_row in calls.iterrows():
            if call_row['strike'] <= stock_price:  # call must be OTM
                continue
            net = put_row['ask'] - call_row['bid']  # positive = debit, negative = credit
            if net <= target_net_debit_max and abs(net) < best_net:
                best_net = abs(net)
                best_pair = (put_row, call_row, net)

    return best_pair
```

**Put strike interpretation**: The put defines the maximum loss. Put at 90% of stock price = 10% maximum drawdown before protection kicks in.

**Call strike interpretation**: The call caps upside. Call at 105% = you participate up to 5% gain before giving up upside.

**DTE for Collars**: Same as other structures: 30–45 DTE. Avoid expirations with earnings.

**Exit Rules for Collar**:
- **Profit**: Close the short call at 50% of credit received; keep the put as free protection
- **Loss**: If stock drops to put strike, can exercise put (exit stock position) or roll the put down and out for additional protection
- **Time**: At 21 DTE: close or roll the call; evaluate whether to keep the put

**Order output** (what the UI displays to the trader):
```
COLLAR TRADE PLAN — [TICKER]

Step 1: Buy 100 shares of [TICKER] at $[PRICE] limit
Step 2: Buy 1 $[PUT_STRIKE] Put (35Δ) expiring [DATE] at $[PUT_ASK] limit
Step 3: Sell 1 $[CALL_STRIKE] Call (28Δ) expiring [DATE] at $[CALL_BID] limit

Net cost per share: $[STOCK_PRICE] + $[PUT_ASK] − $[CALL_BID]
Maximum loss per share: $[STOCK_PRICE] − $[PUT_STRIKE] + Net_option_cost
Maximum gain per share: $[CALL_STRIKE] − $[STOCK_PRICE] − Net_option_cost
EV_real: $[EV_REAL] per share (slippage-adjusted, 3-leg)
```

### 8.4 Strike Selection for Other Structures

**CSP**:
```python
# Kelly-optimal delta: higher delta when VRP_pctile > 80th (premium rich)
target_delta = 0.25 + 0.05 * (vrp_pctile - 0.60) / 0.40  # scales 0.25→0.30 from 60th to 100th pctile
target_delta = np.clip(target_delta, 0.15, 0.35)

# Find nearest strike; verify: OI > 100, spread < 12% of mid
```

**Put Spread**:
- Short leg: same delta-targeting as CSP (20–30Δ)
- Long leg: 5–10 Δ lower (e.g., short 25Δ, long 15Δ) for a ~10-point spread on a $100 stock
- Width: calibrate so max_loss ≤ 3× net credit (risk/reward floor)

**Iron Condor**:
- Puts: 20Δ short / 10Δ long
- Calls: 20Δ short / 10Δ long
- Verify symmetric IV on both sides; if skew > 3 vol pts, widen put strikes relative to calls

### 8.5 DTE Selection

```python
def select_dte(expirations, earnings_date, target_dte_min=28, target_dte_max=48):
    valid_exps = []
    for exp in expirations:
        dte = (exp - today).days
        if dte < target_dte_min or dte > target_dte_max:
            continue
        # Exclude if earnings fall within this window
        if earnings_date and today < earnings_date < exp:
            continue
        valid_exps.append((abs(dte - 38), exp, dte))  # prefer closest to 38 DTE
    valid_exps.sort()
    return valid_exps[0][1:] if valid_exps else (None, None)  # (expiration, dte)
```

### 8.6 Entry Criteria

Presented to the trader as conditions to look for when manually entering the order:
- Enter during the first 2 hours of the session (9:30–11:30 AM ET) — avoid the open 15-min volatility spike
- Prefer entry when the underlying has a minor intraday dip (selling put on weakness) or VIX has a minor intraday spike
- For the limit: place limit order at mid-price; if unfilled after 15 minutes, adjust to mid + 25% of spread
- Never chase: if the underlying gaps down > 2% before entry, re-evaluate the trade before entering

### 8.7 Exit Rules

**Profit target**: 50% of max credit received (default; user-configurable: 25%, 50%, 75%)

**Stop loss (hard)**: Close if current option value = 200% of original credit (i.e., you've lost an amount equal to the credit received). For spreads, close if the spread reaches 75% of max width.

**Delta stop (naked puts only)**: Close if the short put reaches 50Δ (has gone near ATM).

**Time stop**: At 21 DTE, close if between 0%–50% of profit target reached. Hold if already past profit target.

**Roll rules** (when stop triggered and > 21 DTE remain):
- Roll down-and-out for credit: lower strike by 1–2 standard deviations; extend to next expiration
- Only roll if the additional credit received covers at least 25% of the current loss
- Maximum 1 roll per position — do not compound losing positions repeatedly

---

## 9. Fundamentals Scoring: Forensic Accounting & Margin of Safety

### 9.1 Disqualification Filters (Instant NO-GO for CSP or any stock-leg structure)

These filters block assignment on any stock where fundamental deterioration risk is non-negligible. They are applied before scoring.

| Filter | Threshold | Data Source |
|--------|-----------|-------------|
| **Accrual Anomaly** | Net Income > 0 but CFO < −20% of revenue for 4+ consecutive quarters | SEC EDGAR |
| **Quality of Earnings** | CFO/Net Income < 0.5 for TTM (earnings heavily accrual-based) | SEC EDGAR |
| **Inventory/Receivables Divergence** | AR or Inventory growing > 3× revenue YoY | SEC EDGAR |
| **Altman Z / Z' Distress** | Z-score in Distress Zone (see §9.2) | Calculated |
| **Piotroski F-Score** | F-Score < 4 (fundamentally weak) | Calculated |
| **Interest Coverage** | EBIT / Interest Expense < 1.5 (cannot cover debt service) | SEC EDGAR |
| **Going Concern** | Any going concern qualification in last 10-K | SEC EDGAR text |
| **Revenue Decline** | Revenue declining > 25% YoY AND negative FCF | SEC EDGAR |
| **Market Cap** | < $150M (micro-cap without Tier 6 special clearance) | yfinance |
| **Leveraged / Inverse ETF** | 2×/3× multiplier products | ETF metadata |

### 9.2 Altman Z-Score — Correct Model by Company Type

The original Altman Z (1968) was calibrated on manufacturing companies. Three variants must be used:

```python
def altman_z(data, company_type='nonfinancial'):
    """
    Z  (Altman 1968): original, for manufacturers with publicly traded equity
    Z' (Altman 1983): for non-manufacturers (service, tech, etc.)
    Z'' (Altman 1995): for non-public or non-US companies
    """
    wc_ta   = data['working_capital'] / data['total_assets']
    re_ta   = data['retained_earnings'] / data['total_assets']
    ebit_ta = data['ebit'] / data['total_assets']
    mve_tl  = data['market_value_equity'] / data['total_liabilities']
    s_ta    = data['revenue'] / data['total_assets']

    if company_type == 'manufacturer':
        z = 1.2*wc_ta + 1.4*re_ta + 3.3*ebit_ta + 0.6*mve_tl + 1.0*s_ta
        # Distress: < 1.81 | Gray: 1.81–2.99 | Safe: > 2.99
        zones = [(1.81, "Distress"), (2.99, "Gray"), (99, "Safe")]

    elif company_type == 'nonmanufacturer':  # Z' — most common case
        z = 6.56*wc_ta + 3.26*re_ta + 6.72*ebit_ta + 1.05*mve_tl
        # Distress: < 1.23 | Gray: 1.23–2.90 | Safe: > 2.90
        zones = [(1.23, "Distress"), (2.90, "Gray"), (99, "Safe")]

    elif company_type == 'emerging_private':  # Z''
        z = 6.56*wc_ta + 3.26*re_ta + 6.72*ebit_ta + 1.05*(data['book_equity']/data['total_liabilities'])
        zones = [(1.10, "Distress"), (2.60, "Gray"), (99, "Safe")]

    # Note: Financial companies (banks, REITs) — Altman Z does not apply.
    # Use Tier 1 ETF treatment or a financial-specific model (Merton distance-to-default).

    zone = next(label for threshold, label in zones if z < threshold)
    return z, zone
```

**For ETFs**: Altman Z does not apply. ETFs always pass the Z filter.
**For financial companies** (banks, REITs, insurance): Use Interest Coverage alone as the primary solvency filter.

### 9.3 Piotroski F-Score (9 Binary Factors)

Each factor scores 1 (pass) or 0 (fail). Total F-Score = sum (0–9). Score ≥ 7 is strong; ≤ 3 is weak.

```
PROFITABILITY (max 4 points):
  F1: ROA > 0 (positive return on assets)
  F2: CFO > 0 (positive operating cash flow)
  F3: ΔROA > 0 (ROA improving YoY)
  F4: Accrual: CFO/Total Assets > ROA (earnings backed by cash)

LEVERAGE / LIQUIDITY (max 3 points):
  F5: ΔLeverage < 0 (long-term debt ratio decreasing)
  F6: ΔCurrent Ratio > 0 (liquidity improving)
  F7: No new shares issued in the past year (no dilution)

OPERATING EFFICIENCY (max 2 points):
  F8: ΔGross Margin > 0 (margin expanding)
  F9: ΔAsset Turnover > 0 (assets becoming more productive)
```

### 9.4 Margin of Safety Valuation Score (0–100)

This score is the second half of the fundamental score (F-Score is the quality signal; this is the *price* signal). A company can be fundamentally great but overpriced — buying above intrinsic value defeats the margin of safety.

| Factor | Weight | Scoring | Source |
|--------|--------|---------|--------|
| **Earnings Yield Premium** | 25% | E/P − risk_free_rate_3m. Must exceed 400bps to score maximum. Scales linearly from 0 to 400bps. | yfinance + FRED |
| **Price-to-Tangible Book** | 20% | P/TBV < 1.0 → 100pts; > 4.0 → 0pts. Inverse linear. | SEC EDGAR (goodwill, intangibles subtracted) |
| **Interest Coverage** | 20% | EBIT/InterestExp. < 1.5 → disqualified. 4.0+ → 100pts. Linear 1.5→4.0. | SEC EDGAR |
| **FCF Yield** | 15% | FCF/Price. > 8% → 100pts; < 0% → 0pts. Linear. | SEC EDGAR |
| **Debt/Tangible Equity** | 10% | < 0.5 → 100pts; > 3.0 → 0pts. Inverse linear. | SEC EDGAR |
| **Revenue Growth (1yr)** | 10% | > 10% → 100pts; < −10% → 0pts. Linear between. | SEC EDGAR |

### 9.5 Combined Fundamental Score

```
Fundamental_Score = 0.45 × (Piotroski_F / 9 × 100) + 0.55 × Margin_of_Safety_Score
```

This weighting emphasizes valuation (margin of safety) slightly more than quality, consistent with deep-value assignment philosophy: it's better to be assigned on a cheap company than on an expensive quality company.

### 9.6 Per-Tier Minimum Fundamental Scores

| Tier | Min Fundamental Score | Additional Hard Requirements |
|------|----------------------|------------------------------|
| 1–2 (ETFs) | N/A | Not applied to ETFs |
| 3 (S&P 500) | 40 | Altman Z > 1.23 (not Distress) |
| 4 (MidCap) | 55 | Altman Z > 1.81; Piotroski ≥ 5 |
| 5 (SmallCap) | 65 | Altman Z > 2.5; Piotroski ≥ 6 |
| 6 (Micro-Cap) | 75 | Altman Z > 2.99; Piotroski ≥ 7; 4Q positive net income |
| 7 (ADR) | 55 | Same as Tier 3; ADR Level II+ |

---

## 10. Risk Management Framework

### 10.1 Position-Level Rules

| Rule | Default | Notes |
|------|---------|-------|
| Profit target | 50% of max credit | User-configurable: 25%/50%/75% |
| Hard stop | 200% of credit received | For naked; or 75% of spread width for defined-risk |
| Delta stop (naked only) | Exit at 50Δ | Short put breaches ATM |
| Time stop | Close at 21 DTE | If < profit target; rescues gamma risk |
| Max roll | 1× per position | No compounding losing positions |

### 10.2 Portfolio-Level Rules

| Rule | Default | Rationale |
|------|---------|-----------|
| Max short vol exposure | 30% of portfolio | Systemic spike protection |
| Max single position | 5% of portfolio | Concentration |
| Max single sector | 10% of portfolio | Correlated vol clustering |
| Max correlated positions | β-weighted: treat β>0.7 pairs as 1 position | Hidden correlation |
| Max simultaneous positions | 12 | Manageability |
| Tier 5/6 max allocation | 10% total | Micro/small-cap tail risk cap |
| No new positions if VIX > 40 | Hard rule | Tail risk shutoff |

### 10.3 Portfolio VaR Overlay

Before recommending any new position, the engine computes the incremental 1-day 99% VaR contribution:

```python
# Simplified parametric VaR for a short put position
def position_var_1d_99(strike, stock_price, delta, portfolio_beta,
                       portfolio_vol, position_size_dollars):
    # 1-day 2.33-sigma move on the underlying
    stock_1d_99_move = stock_price * portfolio_vol / sqrt(252) * 2.33
    # Delta approximation of option P&L on that move
    position_var = position_size_dollars * abs(delta) * (stock_1d_99_move / stock_price)
    return position_var

# Check: does adding this position push total portfolio VaR > 5% of portfolio value?
PORTFOLIO_VAR_LIMIT = 0.05  # 5% of portfolio as 1-day 99% VaR
```

If the new position would breach the portfolio VaR limit, the recommendation displays a warning and suggests a reduced position size that keeps VaR within limits.

### 10.4 Regime-Based Sizing Multipliers

| VIX | Regime | Size Multiplier |
|-----|--------|----------------|
| < 15 | Low Vol | 0.5× (thin premium) |
| 15–20 | Normal | 1.0× |
| 20–28 | Elevated | 1.25× |
| 28–35 | High | 0.75× |
| > 35 | Crisis | 0× (no new positions) |
| VVIX Z > 2.0 | Uncertain | 0.5× override (all regimes) |

### 10.5 Structural Tail Hedge Recommendation (Permanent Portfolio Layer)

The system recommends maintaining a permanent 1–2% of portfolio in tail protection:
- **Low-cost approach**: Long SPY 1% OTM puts, 90-day DTE, rolling every 60 days; estimated cost ~0.5% of portfolio annually
- **Alternative**: Long VIX calls (15 delta, 30-day) — cheaper in normal regimes, massive payoff in crisis

The screener accounts for this tail hedge cost when presenting EV of any new trade (net cost of hedge amortized across portfolio).

### 10.6 Black Swan Alert Banner

Displayed prominently at top of UI when:
- VIX > 25 AND VVIX Z-score > 1.5
- VX futures (^VIX3M − ^VIX) in backwardation by > 2 pts
- SPY declining > 2% on 2+ consecutive days
- 10Y−2Y yield spread < −0.75% (deep inversion)

Actions: All new position sizes reduced by 50%; existing positions flagged for early closure review.

---

## 11. UI/UX Specification

### 11.1 Page Layout

**Page 1: Screener Dashboard**
```
╔══════════════════════════════════════════════════════════════════════╗
║  VRP Options Screener v3         [Last Updated: 10:12 ET]  [LIVE]  ║
║  [Run Full Scan] [Quick Refresh (Top 30)] [Custom Ticker Lookup]    ║
╠══════════════════════════════════════════════════════════════════════╣
║  MACRO OVERLAY                                                       ║
║  VIX: 19.2 [Normal]  VVIX: 89.1  VIX3M-VIX: +1.8 (Contango)       ║
║  3m T-Bill: 5.25%   10Y-2Y: +0.12%   Regime Multiplier: 1.0×       ║
╠══════════════════════════════════════════════════════════════════════╣
║  SCREENER TABLE  [Filter: VRP%>60 | IVP>50 | No Earn. 14d | GO only]║
║                                                                      ║
║  Ticker|Tier| Price |IV30|RV_YZ|VRP_HAR|VRP%|IVP|Skew|Score|Struct  ║
║  ──────────────────────────────────────────────────────────────────  ║
║  XLE   | T2 | 89.2  |28.4| 15.8| +9.6  | 89 | 82| 3.4|  88 | CSP  ║ ← GO
║  IWM   | T1 | 196.5 |24.1| 14.2| +7.8  | 76 | 71| 1.8|  74 |Sprd  ║ ← GO
║  NVDA  | T3 | 820.0 |52.1| 38.4| +8.2  | 64 | 59| 6.2|  68 |Sprd  ║ ← MARGINAL
║  CROX  | T4 | 128.3 |38.7| 24.1| +9.1  | 77 | 74| 2.9|  71 |Cllr  ║ ← GO
║  [40 more rows]                                                      ║
║  [Click row to open full analysis]  [Export CSV]                     ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Page 2: Full Ticker Analysis**
```
╔══════════════════════════════════════════════════════════════════════╗
║  XLE — Energy Select SPDR ETF            Tier 2 | Price: $89.20    ║
╠════════════════════╦═════════════════════════════════════════════════╣
║ VRP DASHBOARD      ║  IV TERM STRUCTURE                              ║
║                    ║  [Plotly: IV vs DTE, all expirations]          ║
║ IV30:    28.4%     ║                                                 ║
║ RV_YZ:   15.8%     ╠═════════════════════════════════════════════════╣
║ VRP_HAR: +9.6 pts  ║  VRP HISTORY (1 year)                          ║
║ VRP %:   89th      ║  [Plotly: IV30 vs RV, VRP shaded]              ║
║ VRP Persist: 83%   ║                                                 ║
║ VRP Z-score: 2.41  ╠═════════════════════════════════════════════════╣
║ VRP Sharpe:  1.89  ║  SKEW  [25Δ skew vs historical]                ║
║ Excess VRP: +4.1   ║                                                 ║
║                    ╠═════════════════════════════════════════════════╣
║ Jump % of Var: 12% ║  VRP DECOMPOSITION                             ║
║ Diffusive VRP: +8.1║  Diffusive: 8.1 pts (84%) ▓▓▓▓▓▓▓▓▓░          ║
║ Jump VRP:  +1.5    ║  Jump:      1.5 pts (16%) ▓░░░░░░░░░           ║
╠════════════════════╩═════════════════════════════════════════════════╣
║  VRP ATTRIBUTION                                                     ║
║  ✅ IV at 89th IVP — structurally elevated                           ║
║  ✅ 83% VRP persistence — extremely reliable premium collection       ║
║  ✅ Excess VRP +4.1 pts above beta-adj SPY — idiosyncratic premium   ║
║  ✅ Put skew 3.4 pts (72nd pct): institutional hedging demand        ║
║  ✅ Jump % only 12%: diffusive premium dominates — cleanest signal   ║
║  ✅ Term structure contango: macro vol expectations stable            ║
║  ⚠  ETF: commodity sector vol — watch crude oil catalysts            ║
╠══════════════════════════════════════════════════════════════════════╣
║  FUNDAMENTAL SCORE: 87/100 [ETF — STRONG]                           ║
║  ETF: $37B AUM | Expense: 0.09% | YTD: +4.2%                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  TRADE RECOMMENDATION                       ████████ GO (High: 14/17)║
║                                                                      ║
║  Structure:      Cash-Secured Put                                    ║
║  Strike:         $84 Put (26Δ) — 5.8% OTM                          ║
║  Expiration:     Apr 17 (42 DTE)                                     ║
║  Mid Credit:     $1.92/share ($192/contract)                         ║
║                                                                      ║
║  Slippage Analysis:                                                  ║
║  Bid: $1.85 | Ask: $2.05 | Spread: $0.20 | Slippage (75%): $0.15   ║
║  Net Credit Real: $1.77/share                                        ║
║                                                                      ║
║  EV Theoretical: +$89 | EV Real: +$74 | EV/day: +$1.76 | EV%: 0.87%║
║  PoP: 74% (from delta) | HAR-RV forecast: 16.1%                     ║
║                                                                      ║
║  ENTRY: Sell $84 Put at $1.77+ (real net) between 10:00–11:30 AM    ║
║         Wait for minor VIX intraday spike or XLE intraday dip       ║
║                                                                      ║
║  EXITS:                                                              ║
║  Profit: Close at $0.89 debit (50% of $1.77 real credit)            ║
║  Stop:   Close if option value reaches $3.54 (200% of credit)       ║
║  Delta:  Close if $84 Put reaches 50Δ                               ║
║  Time:   Close at 21 DTE if < 50% profit reached                    ║
║                                                                      ║
║  POSITION SIZE                                                       ║
║  Kelly full: 7.2% → 25% fractional: 1.8% → $9,000 of $500k ✅      ║
║  Regime multiplier: 1.0× (Normal) → Final: $9,000                   ║
║  Contracts: 1 ($8,400 capital secured) | Portfolio VaR contrib: 0.4%║
║                                                                      ║
║  MANUAL ORDER:                                                       ║
║  SELL 1 XLE Apr17'26 $84 PUT — Limit $1.77 (net credit floor)       ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 11.2 Configuration Sidebar

```
PORTFOLIO SETTINGS
├─ Portfolio value: $500,000
├─ Max short vol allocation: 30%
├─ Max per-position: 5%
├─ Max positions: 12
└─ Profit target: 50%

SCREENING THRESHOLDS
├─ Min VRP Percentile: 60th
├─ Min VRP Persistence: 60%
├─ Min EV Real (per contract): $25
├─ Earnings exclusion window: 14 days
├─ Max ATM bid-ask: 12% of mid
└─ Min options volume: 500/day

SLIPPAGE MODEL
├─ Slippage factor: 0.75
└─ Market impact threshold: 5% of ADV

KELLY PARAMETERS
├─ Kelly fraction: 25%
└─ Regime multiplier: Auto (from VIX)

UNIVERSE
├─ Tiers enabled: [1✓][2✓][3✓][4✓][5✓][6✓][7✓]
├─ + Add custom tickers
└─ Edit tier universe lists

SCHWAB API
└─ Status: [Connected ✅] | Token refresh: 28 min

AUTO-REFRESH
└─ Quick refresh: [Off / 15min / 30min / 1hr]
```

---

## 12. Technical Architecture

### 12.1 Stack

| Layer | Technology |
|-------|-----------|
| UI | Streamlit |
| Backend | Python 3.11+ |
| Data fetch | yfinance, schwab-py (official Schwab SDK), fredapi, requests |
| Analytics | NumPy, SciPy, pandas, scikit-learn (HAR-RV OLS) |
| Persistence | SQLite (caching + settings) |
| OAuth | schwab-py handles token lifecycle |
| Charts | Plotly via st.plotly_chart |
| Scheduling | APScheduler |
| Concurrency | concurrent.futures.ThreadPoolExecutor (Stage 1 bulk) |

### 12.2 Project Structure

```
vrp_screener/
├── app.py
├── config.py
├── requirements.txt
│
├── data/
│   ├── cache.py                # SQLite TTL-aware cache
│   ├── fetcher_yfinance.py     # Stage 1 bulk fetch
│   ├── fetcher_schwab.py       # Stage 2 Schwab API (OAuth, options chains)
│   ├── fetcher_fred.py         # FRED risk-free rates, VIX history
│   ├── fetcher_edgar.py        # SEC EDGAR forensic accounting data
│   └── options_parser.py       # BSM inversion, IV smile, IV30 extraction
│
├── analytics/
│   ├── realized_vol.py         # CC, Parkinson, GK, Yang-Zhang estimators
│   ├── har_rv.py               # HAR-RV forward forecasting model
│   ├── bipower_variation.py    # BPV for jump separation
│   ├── implied_vol.py          # IV surface, ATM IV, IV30 interpolation
│   ├── vrp.py                  # VRP signals: pctile, persist, zscore, sharpe, excess
│   ├── skew.py                 # 25Δ skew, Z-score
│   ├── term_structure.py       # IV term structure, contango/backwardation
│   ├── regime.py               # VIX regime, VVIX overlay
│   ├── correlation.py          # Beta-adjusted excess VRP
│   ├── scoring.py              # Composite VRP score
│   └── slippage.py             # Per-leg slippage model, market impact
│
├── recommender/
│   ├── go_nogo.py              # 17-point go/no-go matrix
│   ├── structure_selector.py   # Trade structure logic with tier awareness
│   ├── collar.py               # Zero-cost collar strike selection
│   ├── strike_dte.py           # Strike targeting, DTE selection
│   ├── entry_exit.py           # Entry, profit, stop, time, roll rules
│   ├── kelly.py                # Kelly + fractional Kelly + regime multiplier
│   ├── var_overlay.py          # Portfolio VaR incremental check
│   └── ev_calculator.py        # Slippage-adjusted multi-leg EV
│
├── fundamentals/
│   ├── disqualifiers.py        # Hard NO-GO filters (accrual, Altman, QoE)
│   ├── altman_z.py             # Z, Z', Z'' by company type
│   ├── piotroski.py            # 9-factor F-Score
│   ├── margin_of_safety.py     # Earnings yield, TBV, FCF yield, coverage
│   └── scorer.py               # Combined fundamental score
│
└── ui/
    ├── scanner_table.py
    ├── ticker_panel.py
    ├── recommendation_card.py
    ├── charts.py
    └── sidebar.py
```

### 12.3 Stage 1 → Stage 2 Pipeline

```python
# Stage 1: yfinance bulk (parallel, 30 min target)
with ThreadPoolExecutor(max_workers=20) as ex:
    stage1_results = {
        ticker: ex.submit(stage1_fetch, ticker)
        for ticker in full_universe
    }
# Rank by IVP × estimated_VRP, take top 175

# Stage 2: Schwab deep analysis (rate-limited, sequential within bucket)
schwab_client = SchwabClient(tokens)
for ticker in top_175:
    chain = schwab_client.get_option_chain(ticker, ...)  # live Greeks
    run_full_signal_suite(chain, ticker)
    time.sleep(60/100)  # 100 req/min = 50% of 120 rate limit cap
```

---

## 13. Implementation Phases

### Phase 1: Data Infrastructure (~2 weeks)
- [ ] yfinance Stage 1 bulk fetcher with SQLite caching
- [ ] Schwab OAuth2 token management (`schwab-py` library)
- [ ] Schwab options chain fetcher with rate limiting
- [ ] FRED fetcher (risk-free rate, VIX history)
- [ ] SEC EDGAR fetcher (company facts → forensic ratios)
- [ ] Yang-Zhang RV calculator
- [ ] IV30 extraction (BSM inversion, variance-time interpolation)
- [ ] Basic Streamlit app skeleton

**Deliverable**: Raw data flowing for any ticker; IV30 and RV displayed.

### Phase 2: Statistical Engine (~2 weeks)
- [ ] HAR-RV model
- [ ] Bipower Variation + jump separation
- [ ] Full VRP signal suite (pctile, persistence, Z-score, Sharpe, excess VRP)
- [ ] Skew metrics (25Δ skew and Z-score)
- [ ] Term structure slope
- [ ] Composite VRP score
- [ ] Macro regime detection
- [ ] Binary Event Anomaly filter (IV30/IV60 ratio)
- [ ] Stage 1 bulk pre-filter pipeline
- [ ] Stage 2 deep analysis pipeline

**Deliverable**: Screener table with all VRP metrics for a 50-ticker subset.

### Phase 3: Fundamentals & Forensics (~2 weeks)
- [ ] All disqualification filters (accrual anomaly, QoE ratio, Altman Z, inventory/receivables, interest coverage)
- [ ] Altman Z / Z' / Z'' by company type
- [ ] Piotroski F-Score (9 factors from SEC EDGAR)
- [ ] Margin of Safety score (5 components)
- [ ] Combined fundamental score
- [ ] Per-tier minimum score enforcement

**Deliverable**: Fundamental scoring for all S&P 500 tickers.

### Phase 4: Recommendations & Risk (~2 weeks)
- [ ] 17-point Go/No-Go matrix
- [ ] Trade structure selector (tier-aware)
- [ ] Collar strike selection algorithm
- [ ] Strike/DTE selection (all structures)
- [ ] Slippage-adjusted EV (multi-leg)
- [ ] Market impact model
- [ ] Kelly position sizing + regime multiplier
- [ ] Portfolio VaR overlay
- [ ] Entry/exit/roll rules per structure
- [ ] Manual order output text

**Deliverable**: Full trade recommendation card for any qualifying ticker.

### Phase 5: Full Universe & Polish (~1 week)
- [ ] Complete tier 1–7 universe lists loaded
- [ ] Auto-refresh scheduling (Stage 2 quick refresh)
- [ ] Universe editor in sidebar
- [ ] Black Swan alert banner
- [ ] Configuration sidebar (all parameters)
- [ ] CSV export
- [ ] Performance tuning (Stage 1 target: < 30 min; Stage 2: < 20 min)
- [ ] Graceful error handling for tickers with sparse options

**Deliverable**: Production-ready local tool on full ~1,700 ticker universe.

---

## 14. Success Metrics

| Metric | Target |
|--------|--------|
| Stage 1 full scan (1,700 tickers) | < 35 minutes |
| Stage 2 deep analysis (150 candidates) | < 20 minutes |
| Quick refresh (Stage 2 only, top 30) | < 5 minutes |
| Individual ticker lookup | < 15 seconds |
| VRP metrics match manual calc | Within 0.1 vol points |
| HAR-RV forecast RMSE vs YZ-21d | Lower RMSE on held-out 252d window |
| Go signals with VRP Persist > 60% | ≥ 90% of time |
| Fundamental disqualifiers blocking distressed stocks | 100% of Altman Distress Zone stocks blocked for CSP |

---

## 15. Appendix: Statistical Model Reference Code

### A. HAR-RV Rolling Fit
```python
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

def fit_har_rv(rv_daily: pd.Series, fit_window: int = 252) -> dict:
    """Fit HAR-RV model and return coefficients + 21d forecast."""
    rv = rv_daily.dropna()
    rv_d = rv
    rv_w = rv.rolling(5).mean()
    rv_m = rv.rolling(21).mean()

    X = pd.DataFrame({'rv_d': rv_d, 'rv_w': rv_w, 'rv_m': rv_m})
    # Target: RV 21 days ahead
    y = rv.shift(-21)

    idx = X.dropna().index.intersection(y.dropna().index)[-fit_window:]
    model = LinearRegression(fit_intercept=True)
    model.fit(X.loc[idx], y.loc[idx])

    forecast = model.predict([[rv_d.iloc[-1], rv_w.iloc[-1], rv_m.iloc[-1]]])[0]
    return {
        'forecast': max(forecast, 0.01),
        'alpha': model.intercept_,
        'beta_d': model.coef_[0],
        'beta_w': model.coef_[1],
        'beta_m': model.coef_[2],
        'r_squared': model.score(X.loc[idx], y.loc[idx]),
    }
```

### B. VRP Binomial Significance Test
```python
from scipy.stats import binomtest

def vrp_significance(vrp_series: pd.Series) -> dict:
    """Test whether VRP persistence is statistically above 50%."""
    n_pos = int((vrp_series > 0).sum())
    n_total = int(vrp_series.dropna().__len__())
    result = binomtest(n_pos, n_total, p=0.5, alternative='greater')
    return {
        'n_positive': n_pos,
        'n_total': n_total,
        'win_rate': n_pos / n_total,
        'p_value': result.pvalue,
        'significant': result.pvalue < 0.05,
        'label': f"p={result.pvalue:.3f} {'✅ Sig.' if result.pvalue < 0.05 else '⚠ Not sig.'}"
    }
```

### C. Bipower Variation
```python
def bipower_variation(close: pd.Series, window: int = 21) -> float:
    """
    Andersen et al. (2004). Continuous variance estimator — insensitive to jumps.
    Returns annualized continuous variance.
    """
    log_ret = np.log(close / close.shift(1)).dropna()
    abs_ret = log_ret.abs()
    bpv_daily = (np.pi/2) * (abs_ret * abs_ret.shift(1)).rolling(window).mean()
    return (bpv_daily.iloc[-1] * 252)  # annualized variance (not vol)
```

### D. IV Smile Smoothing (Monotone Cubic Spline)
```python
from scipy.interpolate import PchipInterpolator

def smooth_iv_smile(strikes: np.ndarray, ivs: np.ndarray, spot: float) -> callable:
    """
    Fit a PCHIP (monotone cubic) spline to observed IV smile.
    PCHIP preserves monotonicity and avoids butterfly arbitrage.
    """
    valid = ~np.isnan(ivs) & (ivs > 0.01)
    k_valid, iv_valid = strikes[valid], ivs[valid]
    if len(k_valid) < 3:
        return lambda k: np.interp(k, k_valid, iv_valid)
    return PchipInterpolator(k_valid, iv_valid)
```

### E. Quality of Earnings (Accrual Check)
```python
def quality_of_earnings(net_income_ttm: float, cfo_ttm: float, revenue_ttm: float) -> dict:
    """
    Quality of Earnings ratio: CFO / Net Income.
    < 0.5: suspect earnings (accrual-heavy)
    < 0: cash flow negative while profit positive: RED FLAG
    """
    if net_income_ttm <= 0:
        return {'ratio': None, 'flag': 'Net loss — QoE not applicable'}
    ratio = cfo_ttm / net_income_ttm
    accrual_ratio = (net_income_ttm - cfo_ttm) / revenue_ttm  # Sloan (1996)
    return {
        'qoe_ratio': ratio,
        'accrual_ratio': accrual_ratio,
        'flag': 'DISQUALIFY' if ratio < 0 else ('WARNING' if ratio < 0.5 else 'PASS'),
        'label': f"QoE: {ratio:.2f} — {'🚨 Accrual earnings' if ratio < 0.5 else '✅ Cash-backed'}"
    }
```

---

*End of PRD v3.0 — VRP Options Screener*

*This document supersedes both v1.0 (free-API-only) and v2.0 (critiqued version). All execution is manual. No trades are placed through any API.*
