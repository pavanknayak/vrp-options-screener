# Product Requirements Document
# Variance Risk Premium (VRP) Options Screener & Trade Planner
**Local Desktop Application — Individual Use Only**
**Schwab API: Market Data Pull Only — Absolutely No Trade Execution**

Version: 4.1
Date: 2026-03-06
Status: Final

---

## Preface: Critique of v3.0 and What Changes in v4.0

### What v3.0 Got Right (Carried Forward)
- Two-stage scan architecture (yfinance bulk → Schwab deep) — correct approach to rate limit problem
- Universe tiering with per-tier filters and permissible structure constraints
- HAR-RV ensemble forecasting, Yang-Zhang primary estimator, Bipower Variation jump separation
- Full VRP signal suite: persistence, Z-score, Sharpe, excess VRP, skew, term structure
- Forensic accounting disqualifiers: Piotroski F-Score, Quality of Earnings, Altman Z', interest coverage
- Margin of Safety: earnings yield spread, TBV, FCF yield
- Multi-leg slippage model with market impact
- Collar full specification with exit strategy
- Kelly Criterion (25% fractional) with regime multipliers

### Critical Gaps in v3.0 (Addressed in v4.0)

**1. No market microstructure signals.** v3.0 knows *how much* premium exists but not *who is paying it or why right now*. Dealer Gamma Exposure (GEX) and Put-Call Ratio (PCR), computable directly from the Schwab options chain data already being fetched, provide real-time microstructure context that dramatically sharpens timing.

**2. No VRP momentum signal.** A VRP at the 80th percentile that is *rising* (wait) is a fundamentally different trade from one that is *falling* (enter now before it collapses). v3.0 has no concept of VRP direction.

**3. Vol of Vol not computed.** Rolling volatility of the IV30 series itself is a critical quality filter. A VRP signal during a period when IV is itself swinging violently (high VoV) is unreliable — the premium can evaporate in hours. v3.0 ignores this.

**4. No scenario P&L analysis.** v3.0 outputs a single EV number. For capital preservation, the trader needs to see what happens in the bull case, base case, bear case, and crash case — with probability-weighted outcomes. This is the difference between a recommendation and a decision.

**5. No trade reasoning narrative.** v3.0 shows signal scores. The user asked for *reasoning* — a written explanation of why this premium exists, why to enter now vs. wait, and what specific factors could cause the trade to lose. This is the primary user-facing value and was not specified.

**6. RV forecasting only uses HAR-RV.** Adding a GARCH(1,1) and exponentially weighted model and taking an ensemble average produces measurably better RV forecasts. Better forecast → more accurate VRP → sharper edge identification.

**7. Implied move vs. historical move ratio is absent.** The ATM straddle price is the market's implied expected move. Dividing by the realized expected move over equivalent historical periods is a direct, intuitive measure of premium richness that complements IV-based VRP.

**8. FOMC calendar not integrated.** IV spikes before Fed decisions and collapses after. Entering short-vol in the 2 days before FOMC hands the market maker additional edge. Post-FOMC vol crush is one of the most reliable vol-selling entry points. This calendar dependency is absent in v3.0.

**9. Portfolio correlation concentration missing.** v3.0 limits sector exposure by percentage but doesn't compute rolling pairwise correlations between existing positions. When correlations spike (market stress), the portfolio acts like a single position. CVaR (Conditional VaR) is more appropriate than parametric VaR here.

**10. Roll decision framework is incomplete.** v3.0 specifies "maximum 1 roll per position" and a credit threshold, but doesn't specify the full decision tree that governs whether to roll, close, or hold — the most critical active management decision.

### On Data Sources: Is Schwab the Best Free Option?

Schwab Market Data API remains the primary. The only credible free alternative is the **Interactive Brokers TWS API** — which provides equivalent or superior options data quality (IBKR's options analytics are industry-standard), is completely free with an IBKR account, has no official rate limit, and directly exposes real Greeks. However, it requires the TWS desktop application to be running, making it less suitable for headless/scheduled operation. For someone using Schwab as their primary broker, the Schwab API is the correct choice. For IBKR users, the architecture is identical — only the fetcher module differs.

**No free options data source provides real-time options chains without a brokerage account.** Tradier's free sandbox is 15-minute delayed and insufficient for accurate VRP calculation on rapidly-moving underlyings. The Schwab + yfinance hybrid remains the optimal architecture for this use case.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Statistical Foundation & Core Concepts](#2-statistical-foundation--core-concepts)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Universe & Tiering](#4-universe--tiering)
5. [Two-Stage Scanner Architecture](#5-two-stage-scanner-architecture)
6. [Statistical Edge Engine](#6-statistical-edge-engine)
7. [Data Sources & API Stack](#7-data-sources--api-stack)
8. [Trade Recommendation Engine](#8-trade-recommendation-engine)
9. [Trade Reasoning Module](#9-trade-reasoning-module)
10. [Fundamentals: Forensic Accounting & Margin of Safety](#10-fundamentals-forensic-accounting--margin-of-safety)
11. [Risk Management Framework](#11-risk-management-framework)
12. [UI/UX Specification](#12-uiux-specification) *(§12.0: Desktop App Delivery)*
13. [Technical Architecture](#13-technical-architecture) *(§13.0: Architecture Diagram)*
14. [Implementation Phases](#14-implementation-phases)
15. [Appendix: Reference Implementations](#15-appendix-reference-implementations)

---

## 1. Executive Summary

### What This Is
A **local desktop application** — installed and run entirely on the user's personal computer. It opens in the system's default web browser but runs no external servers and sends no data anywhere. Everything: the data cache, computation, configuration, and output stays on-device.

### What It Does
Systematically finds, evaluates, and plans Variance Risk Premium (VRP) options trades across a universe of ~1,485 US-listed tickers — spanning US index and sector ETFs, international ETFs (including dedicated India and China coverage), spot Bitcoin and Ethereum ETFs, S&P 1500 equities, Russell 2000 small-caps, micro-caps, and US-listed ADRs for the most liquid Indian and Chinese individual stocks.

The system uses a two-stage scanning architecture (yfinance bulk pre-filter → Schwab Market Data deep analysis), applies a 12-signal statistical edge engine, forensic accounting and margin-of-safety fundamentals scoring, and a 21-point go/no-go decision matrix. For each qualifying candidate it generates a complete, self-explaining trade plan: structure, specific strikes, DTE, entry timing guidance, four-scenario P&L table, Kelly-sized position, and three written reasoning paragraphs (why the premium exists; why to enter now vs. wait; what specifically could go wrong).

### Critical Constraint — Schwab API Usage
**The Schwab Developer API is used exclusively to pull market data (options chains, quotes, and price history). It is configured as a Market Data application only. It cannot place, modify, or cancel orders. The application contains no order-routing logic whatsoever. All trade execution is performed manually by the user in their broker's interface.**

This constraint is architectural, not just policy: the application registers under Schwab's "Market Data" OAuth scope, which the Schwab API enforces at the permission level. Even if such code were written (it won't be), the API would reject it.

---

## 2. Statistical Foundation & Core Concepts

### 2.1 Variance Risk Premium

```
VRP(t, τ) = IV_td(t, τ) − E_hat[RV_td(t, t+τ)]
```

- `IV_td` = Implied volatility converted to trading-day basis (see §2.2)
- `E_hat[RV_td]` = Ensemble RV forecast over matching horizon (see §6.3)
- The VRP is the option seller's compensation for bearing variance risk

**Why it persists**: Options buyers — primarily institutional hedgers — are systematically willing to overpay for protection. Their demand is price-inelastic (they must hedge regardless of cost). This structural imbalance creates a reliable, persistent premium. VRP on SPY has averaged +3.8 annualized vol points since 1990, positive in ~72% of monthly observations.

### 2.2 Calendar-Day vs. Trading-Day Conversion

Options accumulate calendar-day variance (weekends and holidays count). OHLCV-based realized vol measures trading-day variance. Direct comparison overstates the VRP, especially for short DTEs with many weekend days.

```python
# Convert options IV (calendar-day basis) to trading-day annualized vol
# Both sides then share the same 252-trading-day annualization basis

def iv_to_trading_day(iv_calendar: float) -> float:
    """Scale IV from calendar-day to trading-day annualization."""
    return iv_calendar * np.sqrt(365 / 252)

# Weekend effect for very short DTEs (< 7 days):
def weekend_adjusted_iv(iv: float, dte_calendar: int) -> float:
    """Discount IV for weekend time in short-DTE windows."""
    trading_days_in_window = dte_calendar * (252 / 365)
    effective_vol = iv * np.sqrt(trading_days_in_window / dte_calendar)
    return effective_vol
```

### 2.3 VRP Signal Taxonomy

Not all VRP is equal. The system categorizes each signal along two dimensions:

**By Driver** (determines persistence):

| Driver | Persistence | Signal Proxy |
|--------|------------|-------------|
| Structural hedging demand | High — institutions always need protection | 25Δ skew vs. historical average |
| Dealer inventory risk | Medium — market maker positioning cycles | Dealer GEX (sign and magnitude) |
| Regime uncertainty | Low-Medium — mean-reverting with vol regimes | VIX level, VVIX Z-score |
| Event anticipation | Low — disappears post-event | IV30/IV60 ratio >1.75 |
| Jump risk aversion | Episodic — spikes after large moves | Jump % of implied variance (BPV) |

**By Cleanness** (determines reliability):

| Type | Reliability | Identification |
|------|------------|---------------|
| Diffusive VRP | Highest — Brownian motion is predictable | IV² − BPV (jump-cleaned variance) |
| Skew VRP | High — structural put demand | 25Δ skew above historical baseline |
| Level VRP | Medium — general IV elevation | IV vs. HAR-RV forecast spread |
| Tail VRP | Low — fat-tail fear premium | Butterfly IV, OTM skew convexity |

### 2.4 The Implied Move vs. Realized Move Framework

The simplest, most intuitive VRP measure bypasses IV inversion entirely:

```
EM = ATM Straddle Price / Underlying Price   (implied expected move as % of spot)
RM = realized_std(returns[-21d]) × sqrt(DTE)  (historical expected move over DTE)
EM_Ratio = EM / RM
```

`EM_Ratio > 1.20` means the market is paying 20% more than historical moves justify.
`EM_Ratio > 1.40` is highly elevated — strong premium signal.
This metric complements the IV-based VRP: both should agree for highest confidence.

---

## 3. Goals & Non-Goals

### Goals
- [G1] Run as a **local desktop application** on the user's personal computer — browser-based UI served locally, no cloud, no external servers, all data and computation stays on-device
- [G2] Scan ~1,485 US-listed tickers across 16 sub-tiers (8 ETF sub-tiers including dedicated India, China, and Crypto spot ETF coverage; S&P 500; MidCap 400; SmallCap + Russell 2000; Micro-Cap; India ADRs; China ADRs; Rest-of-World ADRs) using a two-stage, rate-limit-aware architecture
- [G3] Apply a 12-signal statistical edge engine with full VRP decomposition (diffusive, skew, jump, and microstructure components)
- [G4] Compute Dealer Gamma Exposure (GEX) and Put-Call Ratio (PCR) directly from Schwab options chain data as real-time microstructure signals
- [G5] Forecast forward realized volatility using an ensemble model (HAR-RV + GARCH(1,1) + EWMA) for accurate VRP quantification
- [G6] Generate a VRP momentum signal (5d and 10d rate of change of VRP) for entry timing — distinguish rising premium (wait) from falling premium (enter now)
- [G7] Apply forensic accounting disqualifiers (Piotroski F-Score, Altman Z/Z'/Z'', Quality of Earnings) and margin-of-safety valuation for all trades involving potential stock assignment
- [G8] Produce complete, specific trade plans: structure, exact strikes, DTE target, entry conditions, profit target, stop-loss, roll trigger, and full exit decision tree
- [G9] Generate three written reasoning paragraphs per trade: (1) why the premium exists, (2) why to enter now vs. wait, (3) what specifically could cause the trade to lose
- [G10] Show four-scenario P&L analysis (Bull/Base/Bear/Crash) with probability-weighted expected value for every recommended trade
- [G11] Size positions via 25% fractional Kelly with stacked multipliers for volatility regime, Vol-of-Vol, and GEX sign
- [G12] Maintain a rolling 60-day portfolio correlation matrix and Conditional VaR (CVaR) portfolio-level risk overlay
- [G13] Integrate FOMC and earnings calendars into entry timing guidance (ban entry 2 days pre-FOMC; flag as priority entry 1 day post-FOMC vol crush)
- [G14] Apply asset-class-specific structural restrictions: Crypto ETFs — Spread/Collar only, 2% max position size, no Thursday/Friday entry, wider crash shocks (±50%); China ADRs — Spread/Collar only, no CSP (VIE structure and delisting risk make assignment unacceptable); Leveraged ETFs — Spread/Collar only, no CSP
- [G15] **Use Schwab Developer API exclusively and solely for Market Data reads (options chains, quotes, price history) registered under the Market Data OAuth scope. The application contains zero order-routing logic. Zero write operations of any kind through any API, ever.**

### Non-Goals
- Trade execution, order routing, or any write operation through any broker API — ever, under any circumstances
- Real-time streaming data (TTL-cached snapshots: options chains 15 min, price history 1 hr, fundamentals 24 hr)
- Portfolio P&L tracking, position management, or brokerage account balance reads
- Backtesting engine (historical signal validation is explicitly deferred to a future phase)
- Options on futures (VIX futures options, commodity futures options, index futures options)
- Delta-hedged variance swap replication (theoretical exercise — retail execution costs make this economically impractical)
- Automated alerts, push notifications, or scheduled actions that execute without user-initiated screen refresh

---

## 4. Universe & Tiering

Eight tiers with different liquidity requirements, fundamental thresholds, and permissible trade structures. A ticker's tier is assigned at universe load time and governs all downstream analysis. All universe lists are user-editable from the configuration sidebar.

---

### Tier 1A: US Broad Index ETFs (~20 tickers)
*Options filter: ATM bid-ask < 15% of mid. No fundamental score required. Structures: All.*

SPY, QQQ, IWM, DIA, MDY, VTI, VOO, RSP (equal-weight S&P 500), ONEQ (Nasdaq Composite), OEF (S&P 100), IJH (S&P MidCap 400), IJR (S&P SmallCap 600), IWB (Russell 1000), IWC (Micro-Cap), VTWO (Russell 2000), VXF (Total Market ex-S&P 500), SCHB, ITOT

---

### Tier 1B: US Sector & Thematic ETFs (~55 tickers)
*Options filter: ATM bid-ask < 12% of mid; daily options OI at ATM strike > 500. Structures: All.*

**SPDR Sectors (all 11)**: XLF, XLE, XLK, XLV, XLI, XLB, XLY, XLP, XLU, XLC, XLRE

**Industry ETFs**: GDX, GDXJ (gold miners), XBI, IBB (biotech), KRE (regional banks), SMH, SOXX (semis), HACK (cybersecurity), XRT (retail), XHB (homebuilders), ITB, JETS (airlines), XOP (oil & gas E&P), OIH (oil services), COPX (copper miners), LIT (lithium & EV battery), ICLN (clean energy), TAN (solar)

**Factor ETFs**: QUAL, MTUM, VLUE, USMV, SPHQ, SIZE, PRF (fundamental weight)

**High-Vol Thematic** *(flagged: high VRP but borderline assignment quality — Collar/Spread only)*: ARKK, ARKG, ARKQ, ARKW, ARKF

---

### Tier 1C: International ETFs — Developed Markets (~20 tickers)
*Options filter: ATM bid-ask < 15% of mid; daily OI > 300. Structures: All.*

**Broad Developed**: EFA, VEA, IEFA, SCHF, EFV (value)
**Europe**: EZU (Eurozone), EWG (Germany), EWU (UK), EWL (Switzerland), EWI (Italy), EWP (Spain), EWQ (France)
**Asia-Pacific**: EWJ (Japan), DXJ (Japan hedged), EWA (Australia), EWC (Canada), EWS (Singapore)

---

### Tier 1D: International ETFs — India 🇮🇳 (~8 tickers)
*Options filter: ATM bid-ask < 15% of mid; daily OI > 200. Structures: All.*

India has become one of the fastest-growing allocations in global portfolios. Structural vol premium exists due to political risk perception and currency uncertainty that consistently overstates realized market moves.

| Ticker | Fund | Notes |
|--------|------|-------|
| **INDA** | iShares MSCI India ETF | Primary India ETF, ~$10B AUM, most liquid options |
| **INDY** | iShares India 50 ETF | Tracks Nifty 50 large-caps |
| **EPI** | WisdomTree India Earnings Fund | Earnings-weighted; active options |
| **SMIN** | iShares MSCI India Small-Cap ETF | Higher VRP due to small-cap risk premium |
| **PIN** | Invesco India ETF | Broader index |
| **NFTY** | First Trust India NIFTY 50 Equal Weight | Equal-weight Nifty 50 |
| **INCO** | Columbia India Consumer ETF | Consumer-focused |
| **INDL** | Direxion MSCI India Bull 2× | ⚠ LEVERAGED — Spread/Collar only; no CSP |

*Note: INDL is a leveraged ETF. It is included for its elevated VRP but is automatically restricted to defined-risk structures (spread or collar). Assignment is never acceptable on leveraged ETFs.*

---

### Tier 1E: International ETFs — China 🇨🇳 (~10 tickers)
*Options filter: ATM bid-ask < 15% of mid; daily OI > 300. Structures: All except CSP (Spread/Collar only — regulatory and delisting risk in China ADR structures warrants defined-risk mandate).*

China ETFs command among the highest VRP in the ETF universe due to: geopolitical uncertainty (Taiwan, regulatory crackdowns, ADR delisting risk), extreme earnings volatility in Chinese companies, and sustained institutional fear premium for downside protection.

| Ticker | Fund | Notes |
|--------|------|-------|
| **FXI** | iShares China Large-Cap ETF | Primary China ETF; most liquid options by far |
| **MCHI** | iShares MSCI China ETF | Broader exposure; second most liquid |
| **KWEB** | KraneShares CSI China Internet ETF | Tech-heavy; extremely active options market due to high retail interest |
| **CQQQ** | Invesco China Technology ETF | Tech sector; active options |
| **ASHR** | Xtrackers Harvest CSI 300 A-Shares | A-share market access; growing options activity |
| **GXC** | SPDR S&P China ETF | S&P-methodology China index |
| **CHIQ** | Global X MSCI China Consumer Disc. | Consumer sector focus |
| **CXSE** | WisdomTree China ex-State-Owned Enterprises | Excludes SOEs; more market-oriented companies |
| **PGJ** | Invesco Golden Dragon China | US-listed Chinese companies only |
| **YINN** | Direxion Daily FTSE China Bull 3× | ⚠ LEVERAGED 3× — Spread/Collar only; no CSP |

*Note: YINN is a 3× leveraged ETF. VRP is very high. Restricted to spreads and collars only.*

---

### Tier 1F: International ETFs — Emerging Markets (ex-India/China) (~15 tickers)
*Options filter: ATM bid-ask < 15% of mid. Structures: All.*

EEM, VWO (Emerging Markets broad), EWZ (Brazil), EWY (South Korea), EWT (Taiwan), EWW (Mexico), EPOL (Poland), TUR (Turkey), EZA (South Africa), EWM (Malaysia), EIDO (Indonesia), THD (Thailand), ECH (Chile), ARGT (Argentina), VNM (Vietnam)

---

### Tier 1G: Fixed Income ETFs (~12 tickers)
*Options filter: ATM bid-ask < 15% of mid. Structures: All (note: interest rate vol is different in character from equity vol — VRP analysis applies but regime signals calibrated differently).*

TLT (20Y+ Treasuries), IEF (7–10Y), SHY (1–3Y), LQD (IG Corporate), HYG (High Yield), JNK (High Yield), TIP (TIPS/Inflation), AGG (Aggregate Bond), BND, HYD (Muni High Yield), MBB (Mortgage-Backed), BKLN (Senior Loans/Floating Rate)

---

### Tier 1H: Commodity ETFs (~12 tickers)
*Options filter: ATM bid-ask < 15% of mid. Structures: All.*

GLD, IAU (Gold — both), SLV (Silver), GDX (Gold Miners — also Tier 1B), USO (Oil — futures-based; note roll cost), UNG (Natural Gas — futures-based; high VRP), DBC (Diversified Commodity), PDBC (Tax-efficient commodity), CORN, WEAT, SOYB (Grain), CPER (Copper), PALL (Palladium), PPLT (Platinum)

---

### Tier 1I: Crypto ETFs — Spot Bitcoin & Ethereum 🪙 (~10 tickers)
*Options filter: ATM bid-ask < 20% of mid (wider acceptable given crypto volatility); daily OI > 500. Structures: Short Put Spread and Collar ONLY — no CSP, no strangle, no condor. Crypto ETFs have exceptional VRP due to extreme retail fear premium and continuous 24/7 underlying price movement vs. options that only trade market hours.*

**⚠ Special handling**: Crypto ETFs exhibit fundamentally different vol dynamics:
- IV is extreme (often 60–120% annualized) — VRP can be enormous but also volatile
- Realized vol is high but structurally below implied vol for the same reason equity VRP exists: fear premium
- Weekend gap risk: the underlying (BTC/ETH) trades 24/7 but ETF options only price in market-hours moves → Monday open gaps are systematically underpriced in Friday option values → **never sell naked on Thursday/Friday**
- Position sizes must be materially smaller: cap at 2% of portfolio per crypto ETF position (vs. 5% for equity)
- The 4-scenario P&L model uses wider vol shocks: ±20% for bear/bull, ±50% for crash/moon

| Ticker | Fund | Underlying | Notes |
|--------|------|-----------|-------|
| **IBIT** | iShares Bitcoin Trust | Bitcoin (spot) | Largest spot Bitcoin ETF; by far the most liquid options market |
| **FBTC** | Fidelity Wise Origin Bitcoin Fund | Bitcoin (spot) | Second largest; growing options liquidity |
| **GBTC** | Grayscale Bitcoin Trust | Bitcoin (spot) | Oldest; active options; premium/discount dynamics add extra VRP |
| **BITO** | ProShares Bitcoin Strategy ETF | Bitcoin (futures) | First mover; futures roll cost is a persistent premium drag — VRP analysis accounts for this |
| **BITB** | Bitwise Bitcoin ETF | Bitcoin (spot) | Smaller; growing options activity |
| **ARKB** | ARK 21Shares Bitcoin ETF | Bitcoin (spot) | Options available |
| **HODL** | VanEck Bitcoin Trust | Bitcoin (spot) | Options available |
| **ETHA** | iShares Ethereum Trust ETF | Ethereum (spot) | Primary ETH options market |
| **FETH** | Fidelity Ethereum Fund | Ethereum (spot) | Second most liquid ETH ETF options |
| **ETHW** | Bitwise Ethereum ETF | Ethereum (spot) | Growing options market |

*Permitted structures for Tier 1I: Short Put Spread only (defined maximum loss), Zero-cost Collar (if trader holds ETF shares). No cash-secured puts, no strangles, no iron condors. Weekend entry restriction: no new positions opened Thursday afternoon or Friday.*

---

### Tier 2: S&P 500 US Large-Caps (~500 tickers)
*Filter: Daily options volume > 1,000; ATM bid-ask < 12% of mid; Fundamental Score > 40; Altman Z' not in Distress Zone.*
*Structures permitted: CSP (if Fundamental Score > 75), Short Put Spread, Short Strangle, Iron Condor, Collar, Covered Call*

---

### Tier 3: S&P MidCap 400 (~400 tickers)
*Filter: Daily options volume > 500; ATM bid-ask < 10% of mid; Fundamental Score > 55; Altman Z' > 1.23; Piotroski F ≥ 5.*
*Structures permitted: Short Put Spread, Collar, Covered Call — no naked puts*

---

### Tier 4: S&P SmallCap 600 + Russell 2000 Select (~300 tickers)
*Filter: Daily options volume > 500; ATM OI > 200; ATM bid-ask < 8% of mid; Market cap > $300M; Fundamental Score > 65; Altman Z' > 2.5; Piotroski F ≥ 6.*
*Structures permitted: Zero-cost Collar only*

---

### Tier 5: Micro-Cap Discovery (~80 tickers from IWC)
*Filter: Daily options volume > 1,000; ATM bid-ask < 6% of mid; Market cap $150M–$2B; Fundamental Score > 75; Altman Z' > 2.99 (Safe Zone); Piotroski F ≥ 7; 4 consecutive quarters positive net income AND FCF.*
*Structures permitted: Zero-cost Collar ONLY*

---

### Tier 6A: India ADRs — US-Listed Indian Stocks 🇮🇳 (~8 tickers)
*Filter: Same as Tier 2; primary listing NYSE/NASDAQ; ADR Level II or III; daily options volume > 500.*
*Structures: CSP if Fundamental Score > 65 AND Piotroski F ≥ 6; else Short Put Spread or Collar.*

India's largest companies are accessible through US-listed ADRs. Most have reasonably liquid options markets. Currency risk (INR/USD) is embedded in ADR pricing and contributes a persistent premium component.

| Ticker | Company | Sector | Options Liquidity |
|--------|---------|--------|-----------------|
| **INFY** | Infosys | IT Services | High — most liquid Indian ADR options |
| **HDB** | HDFC Bank | Private Banking | High — largest Indian bank by market cap |
| **IBN** | ICICI Bank | Private Banking | High — second largest private bank ADR |
| **WIT** | Wipro | IT Services | Moderate — decent options activity |
| **TTM** | Tata Motors | Automotive/EV | Moderate — JLR exposure adds vol premium |
| **RDY** | Dr. Reddy's Laboratories | Pharmaceuticals | Moderate — USFDA risk creates persistent IV premium |
| **VEDL** | Vedanta | Mining & Resources | Lower — include only if OI > 300 on scan day |
| **AZRE** | Azure Power Global | Renewable Energy | Lower — include only if OI > 300 |

*VRP context for India ADRs*: Indian IT companies (INFY, WIT) have historically high VRP due to US client concentration risk, USDÂ earnings currency risk, and H-1B visa policy uncertainty — all of which inflate IV beyond what realized moves justify. Banking ADRs (HDB, IBN) carry NPA (non-performing asset) risk premium that is structurally priced in.

---

### Tier 6B: China ADRs — US-Listed Chinese Stocks 🇨🇳 (~15 tickers)
*Filter: Same as Tier 2; primary listing NYSE/NASDAQ; daily options volume > 500.*
*Structures: Short Put Spread or Zero-cost Collar ONLY — no CSP. Rationale: ADR delisting risk, VIE structure legal uncertainty, and Chinese regulatory intervention risk make outright assignment unacceptable regardless of fundamental score.*

**⚠ China ADR Risk Disclosure in PRD**: Chinese ADRs carry unique risks absent in domestic equities: (1) VIE structures mean shareholders do not own the underlying Chinese operating entity; (2) the SEC has previously threatened delisting of non-compliant Chinese ADRs; (3) Chinese government regulatory interventions have caused >50% single-day drops (Didi, TAL, New Oriental). These risks are **not** adequately captured by standard fundamental scoring. Accordingly, no naked exposure (CSP, strangle) is ever permitted on China ADRs. All positions must have a defined maximum loss.

Despite these risks, China ADRs offer some of the highest and most persistent VRP available in any asset class — the extreme regulatory and geopolitical fear premium consistently overshoots realized volatility. The edge is real; it must simply be captured with defined-risk structures.

| Ticker | Company | Sector | Options Quality |
|--------|---------|--------|----------------|
| **BABA** | Alibaba Group | E-Commerce / Cloud | Very High — massive options market |
| **JD** | JD.com | E-Commerce / Logistics | High |
| **PDD** | PDD Holdings (Temu/Pinduoduo) | E-Commerce | Very High |
| **BIDU** | Baidu | Search / AI | High |
| **NIO** | NIO Inc. | Electric Vehicles | Very High — extreme retail options activity |
| **XPEV** | Xpeng | Electric Vehicles | High |
| **LI** | Li Auto | Electric Vehicles | High |
| **NTES** | NetEase | Gaming / Media | Moderate-High |
| **TCOM** | Trip.com | Online Travel | Moderate |
| **BILI** | Bilibili | Video / Gaming | Moderate |
| **YUMC** | Yum China Holdings | Restaurants (KFC/Pizza Hut China) | Moderate |
| **EDU** | New Oriental Education | Education | Moderate — regulatory crackdown history creates persistent VRP |
| **IQ** | iQIYI | Streaming Video | Lower |
| **TME** | Tencent Music Entertainment | Music Streaming | Lower |
| **VIPS** | Vipshop Holdings | Discount E-Commerce | Lower — include only if OI > 300 |

*VRP context for China ADRs*: The premium is primarily driven by regulatory intervention fear (Didi, Ant Group, EDU precedents), geopolitical tension (Taiwan risk, US sanctions risk), VIE structure uncertainty, and consistent institutional hedging demand. The EV names (NIO, XPEV, LI) carry additional EV-sector vol premium from competitive dynamics and subsidy uncertainty. In aggregate, this universe has historically exhibited among the highest VRP of any equity segment — but only spreads and collars are appropriate.

---

### Tier 7: Rest-of-World Liquid ADRs (~20 tickers)
*Filter: Same as Tier 2; primary listing NYSE/NASDAQ; ADR Level II/III.*
*Structures: CSP if Fundamental Score > 65; else Spread/Collar.*

TSM (Taiwan Semiconductor), ASML (Netherlands), NVO (Novo Nordisk/Denmark), SHEL (Shell/UK-Netherlands), TTE (TotalEnergies/France), AZN (AstraZeneca/UK-Sweden), UL (Unilever/UK), SAP (SAP SE/Germany), DEO (Diageo/UK), SONY (Japan), BTI (British American Tobacco), TD (Toronto-Dominion Bank), ENB (Enbridge/Canada), VALE (Brazil), RIO (Rio Tinto/Australia-UK), SE (Sea Limited/Singapore), MELI (MercadoLibre/Argentina-Uruguay), NU (Nubank/Brazil)

---

### Universe Summary

| Tier | Description | Approx. Tickers | Structures Available |
|------|------------|----------------|---------------------|
| 1A | US Broad Index ETFs | ~20 | All |
| 1B | US Sector & Thematic ETFs | ~55 | All |
| 1C | International Developed ETFs | ~20 | All |
| 1D | India ETFs | ~8 | All (INDL: Spread/Collar only) |
| 1E | China ETFs | ~10 | Spread/Collar only (YINN: same) |
| 1F | Emerging Market ETFs (ex-India/China) | ~15 | All |
| 1G | Fixed Income ETFs | ~12 | All |
| 1H | Commodity ETFs | ~12 | All |
| 1I | Crypto ETFs (BTC + ETH) | ~10 | Spread/Collar only; 2% max size |
| 2 | S&P 500 US Large-Caps | ~500 | CSP (if Fund>75), Spread, Strangle, Condor, Collar |
| 3 | S&P MidCap 400 | ~400 | Spread, Collar, Covered Call |
| 4 | S&P SmallCap 600 + Russell 2000 Select | ~300 | Collar only |
| 5 | Micro-Cap (IWC) | ~80 | Collar only |
| 6A | India ADRs | ~8 | CSP (if Fund>65+Piotroski≥6), else Spread/Collar |
| 6B | China ADRs | ~15 | Spread/Collar ONLY |
| 7 | Rest-of-World ADRs | ~20 | CSP (if Fund>65), else Spread/Collar |
| **Total** | | **~1,485** | |

*All universe lists are user-editable from the Configuration sidebar. Add or remove tickers without touching code.*

---

## 5. Two-Stage Scanner Architecture

### The Rate Limit Problem and Solution

At 120 Schwab API requests/minute, scanning all ~1,485 tickers for full options chains would require ~1,250+ calls (multiple expirations per ticker) → over 10 minutes of pure API time with zero buffer. More importantly, yfinance is fast, parallelizable, and has no strict rate limit — it is ideal for bulk pre-filtering. Schwab's precision is reserved for the candidates that actually matter.

### Stage 1: Bulk Pre-Filter (yfinance) — All tickers, ~20–35 min

For every ticker in the universe, in parallel (20 threads):
1. Pull 252 days of OHLCV → compute Yang-Zhang 21d RV
2. Pull most recent options chain for the nearest expiration → extract estimated ATM IV from yfinance `.impliedVolatility` field (approximate; sufficient for ranking)
3. Compute estimated VRP = IV_td_estimated − RV_YZ_21d
4. Compute IVP from 252-day IV history
5. Check daily options volume from yfinance options chain (OI-weighted proxy)
6. Flag earnings dates: if earnings within 14 days → skip
7. Apply Binary Event Anomaly check: IV30_est > 1.75× IV60_est with no earnings → flag

**Output**: Sorted list of top 175 candidates by `IVP × max(VRP_estimate, 0)`. These proceed to Stage 2.

**Cache behavior**: yfinance OHLCV cached 1 hour; options volume cached 15 min; Stage 1 results cached 30 min. On a warm cache, Stage 1 runs in < 5 minutes.

### Stage 2: Deep Analysis (Schwab API) — Top 175 candidates, ~15–25 min

For each candidate, sequentially with rate-limiting:
1. Fetch live Schwab options chain for 2–3 expirations bracketing 30–60 DTE
2. Filter options: bid > 0, OI > 100, bid-ask < 15% of mid
3. BSM-invert each valid option's mid-price to extract per-strike IV
4. Fit IV smile (PCHIP monotone cubic spline) per expiration
5. Extract ATM IV per expiration; interpolate to IV30 and IV60 in variance-time space
6. Compute full IV history (IV30 back-calculated from cached prior chains for VRP history)
7. Run complete VRP signal suite (all 12 signals — §6)
8. Run Ensemble RV forecast (§6.3)
9. Run GEX and PCR from the same options chain (§6.6, §6.7)
10. Run fundamentals (from cached SEC EDGAR + yfinance, TTL 24h)
11. Run trade recommender (§8)
12. Generate reasoning narrative (§9)

**Schwab rate management**: 100 requests/minute (83% of 120 limit for safety buffer). Each ticker: ~4 calls (3 expirations + underlying quote). 175 tickers × 4 = 700 calls → 7 minutes. Full Stage 2 including computation: ~20 minutes.

### Stage 3: Refresh Modes

| Mode | Trigger | Scope | Duration |
|------|---------|-------|---------|
| Full Scan | Daily at 9:45 AM ET (auto) or manual | Both stages | ~45 min |
| Quick Refresh | Every 30 min (auto) or manual | Stage 2 only (top 30) | ~4 min |
| Ticker Lookup | On-demand | Single ticker full Stage 2 | < 30 sec |
| Event Refresh | Triggered if VIX moves > 5% intraday | Stage 2 top 30 | ~4 min |

---

## 6. Statistical Edge Engine

### 6.1 Realized Volatility — Four-Estimator Suite

All estimators run over 10d, 21d, 30d, and 60d windows. Yang-Zhang is primary for all VRP calculations. Others are displayed for context and used in divergence detection.

| Estimator | Relative Efficiency vs. CC | Best For |
|-----------|--------------------------|---------|
| Close-to-Close (CC) | 1× (baseline) | Reference/sanity check |
| Parkinson | ~5× | Intraday movers, no gaps |
| Garman-Klass | ~8× | Normal trading, small overnight gaps |
| Yang-Zhang | ~14× | All conditions — handles gaps + drift |

**Estimator divergence signal**: When Parkinson or GK are significantly lower than YZ (> 3 vol pts), large overnight gaps are dominating the RV. This means selling ATM options is not capturing the true vol risk — flag for review.

### 6.2 Yang-Zhang Estimator (Primary)

```python
def yang_zhang_vol(ohlc: pd.DataFrame, window: int = 21) -> pd.Series:
    log_oc = np.log(ohlc['Open'] / ohlc['Close'].shift(1))   # overnight
    log_co = np.log(ohlc['Close'] / ohlc['Open'])              # intraday
    log_ho = np.log(ohlc['High'] / ohlc['Open'])
    log_lo = np.log(ohlc['Low'] / ohlc['Open'])
    rs = log_ho*(log_ho - log_co) + log_lo*(log_lo - log_co)  # Rogers-Satchell
    k = 0.34 / (1.34 + (window+1)/(window-1))
    return np.sqrt(252 * (
        (1-k) * log_co.rolling(window).var() +
        k * rs.rolling(window).mean() +
        log_oc.rolling(window).var()
    ))
```

### 6.3 Ensemble RV Forecast (3-Model Average)

Using a single RV estimator as the VRP forecast is suboptimal. An ensemble of three independent models consistently outperforms any individual model in out-of-sample RV prediction, reducing forecast RMSE by 15–25%.

#### 6.3.1 HAR-RV (Heterogeneous Autoregressive)
Captures multi-scale persistence: daily, weekly, and monthly vol components.
```python
def har_rv_forecast(rv_daily: pd.Series, fit_window: int = 252) -> float:
    rv_d = rv_daily; rv_w = rv_daily.rolling(5).mean(); rv_m = rv_daily.rolling(21).mean()
    # OLS: RV_t+21 = α + β_d*RV_d_t + β_w*RV_w_t + β_m*RV_m_t
    X = pd.DataFrame({'d': rv_d, 'w': rv_w, 'm': rv_m})
    y = rv_daily.shift(-21)  # target: RV 21 days forward
    idx = X.dropna().index.intersection(y.dropna().index)[-fit_window:]
    from sklearn.linear_model import LinearRegression
    model = LinearRegression().fit(X.loc[idx], y.loc[idx])
    return max(model.predict([[rv_d.iloc[-1], rv_w.iloc[-1], rv_m.iloc[-1]]])[0], 0.01)
```

#### 6.3.2 GARCH(1,1)
Captures volatility clustering: high-vol periods tend to persist, then revert.
```python
from arch import arch_model
def garch_rv_forecast(returns: pd.Series) -> float:
    """GARCH(1,1) with GJR asymmetry (accounts for leverage effect — neg returns → higher vol)."""
    model = arch_model(returns * 100, vol='Garch', p=1, o=1, q=1, dist='t')
    res = model.fit(disp='off', last_obs=-1)
    # 21-day ahead forecast, annualized
    forecast = res.forecast(horizon=21)
    var_forecast = forecast.variance.values[-1].mean() / 10000  # daily variance
    return np.sqrt(var_forecast * 252)
```

#### 6.3.3 EWMA (Exponentially Weighted Moving Average)
Fast-adapting; captures recent vol regime shifts. Lambda = 0.94 (RiskMetrics standard).
```python
def ewma_rv_forecast(returns: pd.Series, lam: float = 0.94) -> float:
    """RiskMetrics EWMA volatility."""
    r2 = returns**2
    weights = np.array([(1-lam) * lam**i for i in range(len(r2)-1, -1, -1)])
    weights /= weights.sum()
    ewma_var = (weights * r2).sum()
    return np.sqrt(ewma_var * 252)
```

#### 6.3.4 Ensemble Average
```python
def ensemble_rv_forecast(ohlc, returns):
    har = har_rv_forecast(yang_zhang_vol(ohlc))
    garch = garch_rv_forecast(returns)
    ewma = ewma_rv_forecast(returns)
    # Equal-weighted ensemble (can be optimized via rolling out-of-sample R²)
    return np.mean([har, garch, ewma])
```

**VRP primary signal**:
```python
VRP = IV30_td_annualized - ensemble_rv_forecast
```

### 6.4 Bipower Variation — Jump Separation

Continuous (diffusive) variance is reliably collectible. Jump variance is episodic and can produce large losses. The diffusive VRP is the cleanest, most persistent signal.

```python
def bipower_variation(close: pd.Series, window: int = 21) -> float:
    """Annualized continuous variance — insensitive to price jumps."""
    log_ret = np.log(close/close.shift(1)).dropna()
    abs_ret = log_ret.abs()
    bpv = (np.pi/2) * (abs_ret * abs_ret.shift(1)).rolling(window).mean() * 252
    return bpv.iloc[-1]

# Jump component (in variance space):
jump_var = max(rv_yz_21d**2 - bpv, 0)
jump_pct = jump_var / iv30_td**2  # fraction of implied variance attributable to jumps

# Diffusive VRP (most reliable component):
vrp_diffusive_vol = np.sign(iv30_td**2 - bpv) * np.sqrt(abs(iv30_td**2 - bpv))
```

**Interpretation**:
- `jump_pct < 20%`: Premium is predominantly diffusive — excellent quality signal
- `jump_pct 20–35%`: Mixed — reduce position size by 25%
- `jump_pct > 35%`: Recent jumps dominate — IV is compensating for jump fear more than diffusive uncertainty. High-risk premium to sell. Apply NO-GO unless diffusive VRP alone still qualifies.

### 6.5 Core VRP Signal Suite

```python
class VRPSignals:
    # Primary
    vrp              = iv30_td - rv_ensemble         # Main signal (ensemble forecast)
    vrp_diffusive    = vrp_diffusive_vol             # Jump-cleaned signal
    em_ratio         = atm_straddle / (rv_yz_21d * stock_price * np.sqrt(DTE/252))

    # Historical context
    vrp_1yr          = pd.Series([...])  # rolling 252-day VRP history
    vrp_pctile       = percentileofscore(vrp_1yr, vrp)    # vs. past year
    vrp_persist_30d  = (vrp_1yr[-30:] > 0).mean()         # recent reliability
    vrp_zscore       = (vrp - vrp_1yr.mean()) / vrp_1yr.std()
    vrp_sharpe       = vrp_1yr.mean() / vrp_1yr.std() * np.sqrt(252/21)
    vrp_significance = binomtest(n_pos, n_total, 0.5, 'greater').pvalue

    # VRP Momentum (NEW in v4.0)
    vrp_5d_change    = vrp - vrp_1yr[-5]    # rising or falling?
    vrp_10d_change   = vrp - vrp_1yr[-10]
    vrp_momentum     = np.sign(vrp_5d_change)  # +1 rising, -1 falling

    # Idiosyncratic signal
    excess_vrp       = vrp - (beta * spy_vrp)   # premium above beta-adj index

    # IV positioning
    ivr              = (iv30 - iv_52w_low) / (iv_52w_high - iv_52w_low)
    ivp              = percentileofscore(iv_252d, iv30)
    vov_30d          = iv_252d[-30:].std()    # Vol of Vol: IV30 rolling std
    vov_zscore       = (vov_30d - iv_252d.rolling(30).std().mean()) / (...)

    # Skew
    skew_25d         = iv_put_25d - iv_call_25d
    skew_zscore      = (skew_25d - skew_1yr.mean()) / skew_1yr.std()
    skew_persist_30d = (skew_1yr[-30:] > skew_1yr.mean()).mean()

    # Term structure
    term_slope       = iv60 - iv30
    term_slope_pctile= percentileofscore(term_slope_1yr, term_slope)

    # Jump
    jump_pct         = jump_var / iv30_td**2
```

### 6.6 Dealer Gamma Exposure (GEX) — Computed from Schwab Chain

GEX is the aggregate gamma position of market makers (dealers). It is computed directly from the options chain we already fetch — no external data source needed.

**Why it matters for VRP trading**: When dealers are net long gamma (positive GEX), they *dampen* price moves by selling rallies and buying dips (delta-hedging). Dampened moves → realized vol comes in below implied vol → VRP more reliably collected. When dealers are net short gamma (negative GEX), they *amplify* moves. This is when realized vol can spike and exceed implied vol.

```python
def compute_gex(options_chain, spot: float) -> dict:
    """
    Compute net dealer gamma exposure in dollar terms.
    Assumes dealers are short puts and long calls (standard approximation).
    GEX > 0 (dealers long gamma): dampens moves → supports VRP collection
    GEX < 0 (dealers short gamma): amplifies moves → VRP collection riskier
    """
    gex = 0
    for _, row in options_chain.calls.iterrows():
        # Dealers sold calls to retail → dealers are SHORT calls → LONG puts (net delta hedge)
        # Call OI × gamma × 100 (shares/contract) × spot² = dollar GEX contribution
        gex += row['openInterest'] * row['gamma'] * 100 * spot**2 * (-1)  # dealer short call

    for _, row in options_chain.puts.iterrows():
        # Dealers sold puts to retail → dealers are SHORT puts → LONG stock (net delta hedge)
        gex += row['openInterest'] * row['gamma'] * 100 * spot**2 * (+1)  # dealer short put

    # Normalize by spot² for interpretability
    gex_bn = gex / 1e9  # GEX in billions

    return {
        'gex_raw': gex,
        'gex_billions': gex_bn,
        'sign': 'positive' if gex > 0 else 'negative',
        'interpretation': 'Moves dampened (supports premium collection)' if gex > 0
                          else 'Moves amplified (VRP collection riskier)',
        'magnitude': abs(gex_bn)
    }
```

**GEX thresholds**:
- GEX > +$0.5B: Strongly supportive — dealer hedging suppresses vol
- GEX +$0–0.5B: Mildly supportive
- GEX −$0–0.5B: Mildly adverse — neutral on position size
- GEX < −$0.5B: Adverse — reduce position size by 25%

### 6.7 Put-Call Ratio (PCR)

Directly computable from the Schwab options chain. PCR measures the relative demand for puts vs. calls — a proxy for institutional hedging demand and market sentiment.

```python
def compute_pcr(options_chain, dte_min=7, dte_max=60) -> dict:
    """Compute PCR by volume and OI for the relevant expiration window."""
    puts  = options_chain.puts
    calls = options_chain.calls

    pcr_volume = puts['volume'].sum() / max(calls['volume'].sum(), 1)
    pcr_oi     = puts['openInterest'].sum() / max(calls['openInterest'].sum(), 1)

    return {
        'pcr_volume': pcr_volume,
        'pcr_oi':     pcr_oi,
        'interpretation': (
            'Elevated put buying: hedging demand premium present' if pcr_oi > 1.5
            else 'Balanced: structural premium only' if 0.8 <= pcr_oi <= 1.5
            else 'Call heavy: unusual (M&A/event rumors?), reduce put-selling conviction'
        )
    }
```

**PCR interpretation**:
- PCR OI > 1.8: Heavy institutional put buying → strong hedging demand premium → premium quality high
- PCR OI 1.2–1.8: Elevated but normal → moderate hedging demand
- PCR OI 0.8–1.2: Balanced → structural premium present but less hedging-demand driven
- PCR OI < 0.8: Call-heavy → unusual condition; investigate for event rumors or M&A

### 6.8 Vol of Vol (VoV)

Rolling standard deviation of the IV30 series itself. When IV is itself highly volatile, the VRP signal is unreliable — the premium can collapse or spike without warning.

```python
# VoV: 30-day rolling std of daily IV30 changes
vov_30d = iv30_daily_series[-30:].std() * np.sqrt(252)  # annualized

# VoV Z-score vs. 252-day history
vov_zscore = (vov_30d - vov_1yr_mean) / vov_1yr_std

# Interpretation:
# VoV Z > 1.5: IV itself is unstable → VRP unreliable → reduce position size by 30%
# VoV Z > 2.5: IV extremely unstable → NO-GO for new short-vol positions
```

### 6.9 VRP Momentum — Entry Timing Signal

VRP at the 80th percentile that is *rising* is a different trade from VRP at the 80th percentile that is *falling*. If the VRP is rising (IV expanding faster than RV), it may continue to expand — waiting costs little but gets more premium. If VRP is falling (IV compressing toward RV), premium is evaporating — enter immediately if the signal is GO.

```python
def vrp_timing_signal(vrp_5d_change, vrp_10d_change, vrp_pctile):
    """Returns timing recommendation for entry."""
    is_rising  = vrp_5d_change > 0.5  # VRP rising by >0.5 vol pts over 5d
    is_falling = vrp_5d_change < -0.5  # VRP falling

    if is_falling and vrp_pctile > 65:
        return "ENTER NOW", "VRP is contracting — premium collapsing toward mean. Enter immediately."
    elif is_rising and vrp_pctile > 80:
        return "ENTER NOW or WAIT 1-3 DAYS", "VRP is expanding at 80th+ pctile. Can enter now or wait for peak."
    elif is_rising and vrp_pctile < 70:
        return "WAIT 1-3 DAYS", "VRP expanding but below threshold. Let premium build before entering."
    else:
        return "ENTER AT OPPORTUNITY", "VRP stable at elevated level. Enter on minor IV spike or underlying dip."
```

### 6.10 FOMC & Event Calendar Integration

IV reliably spikes into FOMC meetings and collapses after. This creates a specific pattern:
- **2–3 days before FOMC**: IV elevated, but selling here means being short vol through the announcement. High event risk. **Avoid opening new positions.**
- **1 day after FOMC resolution**: Vol crush often occurs. **Excellent short-vol entry** — sell into the post-resolution elevation that hasn't fully collapsed.
- **7+ days before FOMC** with > 21 DTE expiration: FOMC falls within DTE window → flag as event risk in expiration selection.

```python
FOMC_DATES_2026 = ['2026-01-29', '2026-03-19', '2026-05-07', '2026-06-18',
                   '2026-07-30', '2026-09-17', '2026-11-05', '2026-12-17']

def fomc_context(today, expiration_date):
    for fomc_date in FOMC_DATES_2026:
        fdate = pd.Timestamp(fomc_date)
        days_to_fomc = (fdate - today).days
        fomc_in_window = today < fdate < expiration_date

        if 0 < days_to_fomc <= 2:
            return "AVOID", f"FOMC in {days_to_fomc} days. High event risk. Wait for post-FOMC entry."
        elif days_to_fomc == -1:
            return "PRIORITY ENTRY", "FOMC concluded yesterday. Vol crush likely in progress. Prime entry window."
        elif fomc_in_window:
            return "FOMC IN WINDOW", f"FOMC on {fomc_date} falls within this expiration. Moderate event risk."
    return "CLEAR", "No FOMC in expiration window."
```

### 6.11 Composite VRP Score (0–100)

Twelve signals, four quality adjustments:

```
VRP_Score = (
    0.18 × normalize(vrp_pctile, 0, 1)              +  # Magnitude vs. history (primary)
    0.12 × normalize(vrp_persist_30d, 0.4, 1)        +  # Reliability
    0.12 × normalize(clip(vrp_zscore, -3, 3))         +  # Statistical significance
    0.10 × normalize(em_ratio, 0.8, 2.0)              +  # Implied vs. realized move
    0.10 × normalize(excess_vrp, -5, 10)              +  # Idiosyncratic premium
    0.08 × normalize(ivp, 0, 1)                       +  # IV elevation
    0.08 × normalize(skew_25d, -2, 8)                 +  # Hedging demand driver
    0.07 × normalize(term_slope_pctile, 0, 1)         +  # Term structure support
    0.05 × normalize(1 - jump_pct, 0.5, 1)            +  # Jump-cleanliness
    0.04 × normalize(pcr_oi, 0.8, 2.5)               +  # Put buying demand
    0.03 × gex_support_score                          +  # Dealer positioning
    0.03 × normalize(1 - vov_zscore/3, 0, 1)             # IV stability (inverted VoV)
) × 100
  × (1 − event_penalty)          # Earnings in window: 0.30; near-term earnings: 0.15
  × (1 − jump_penalty)           # jump_pct > 35%: 0.20; > 25%: 0.10
  × (1 − vov_penalty)            # VoV Z > 2.5: DISQUALIFY; > 1.5: 0.25
```

### 6.12 Macro Regime

```python
def regime(vix, vvix, vix3m, vvix_252d_mean, vvix_252d_std):
    vvix_z = (vvix - vvix_252d_mean) / vvix_252d_std
    vix_term_slope = vix3m - vix

    if vix > 40:   return "CRISIS",   0.00, "Close all. Do not open new short-vol."
    if vvix_z > 2.5: return "VOL_UNSTABLE", 0.25, "VVIX spike: VRP unreliable. 25% size max."
    if vix > 28:   return "HIGH",     0.75, "Rich premium; tail risk elevated."
    if vix > 20:   return "ELEVATED", 1.25, "Premium-rich: increase size modestly."
    if vix > 15:   return "NORMAL",   1.00, "Standard environment."
    return         "LOW_VOL",  0.50, "Thin premium; reduce size, be selective."
```

---

## 7. Data Sources & API Stack

### 7.1 Architecture Summary

| Source | Stage | Data Type | Auth | Rate Limit | Cost |
|--------|-------|-----------|------|-----------|------|
| **yfinance** | Stage 1 | OHLCV, approx IV, volume, basic fundamentals | None | ~2000/hr practical | Free |
| **Schwab Market Data API** | Stage 2 | Live options chains, real-time Greeks, quotes | OAuth2 (Schwab account) | 120 req/min | Free with account |
| **FRED API** | Both | Risk-free rates (DGS3MO), VIX history, macro | Free API key | 120 req/min | Free |
| **SEC EDGAR** | Stage 2 | 10-K/10-Q financials: FCF, revenue, debt, etc. | User-Agent header | 10 req/sec | Free |
| **yfinance (fallback)** | Stage 2 | Fundamental ratios not in EDGAR quarterly | None | Same as above | Free |

**Total cost**: Free. Only requires a Schwab brokerage account (which an options trader already has).

### 7.2 Schwab API Integration

> **ABSOLUTE CONSTRAINT**: The Schwab API is used *exclusively* for **Market Data reads**. This application:
> - Registers with Schwab under the **"Market Data"** OAuth scope only — not "Trading"
> - Contains **zero order-routing logic** of any kind (no `place_order`, `cancel_order`, or any write endpoint)
> - The `schwab-py` client object is initialized with `read_only=True` semantics — the Market Data scope token physically cannot execute trades even if such code were accidentally written
> - All execution is **100% manual** by the user in their broker's own interface

The `schwab-py` library (official Schwab SDK) handles OAuth2 lifecycle:
- Authorization Code flow on first run (browser redirect to Schwab login)
- Access tokens: 30-minute expiry, auto-refreshed
- Refresh tokens: 7-day expiry, stored in encrypted local keystore

```python
import schwab

# One-time setup (browser-based OAuth)
client = schwab.auth.easy_client(
    api_key=SCHWAB_APP_KEY,
    app_secret=SCHWAB_APP_SECRET,
    callback_url='https://127.0.0.1',
    token_path='schwab_token.json'
)

# Options chain fetch
def fetch_option_chain(ticker: str, exp1_date: str, exp2_date: str):
    resp = client.get_option_chain(
        ticker,
        contract_type=client.Options.ContractType.ALL,
        strike_count=40,
        include_underlying_quote=True,
        strategy=client.Options.Strategy.SINGLE,
        from_date=exp1_date,
        to_date=exp2_date
    )
    return resp.json()
```

**Key data fields from Schwab chain**: `bid`, `ask`, `last`, `mark` (mid), `delta`, `gamma`, `theta`, `vega`, `rho`, `impliedVolatility`, `openInterest`, `totalVolume`, `inTheMoney`, `daysToExpiration`

### 7.3 FOMC Calendar Source

FOMC dates are maintained as a static list in the application (updated annually). The Federal Reserve publishes the full calendar at the start of each year at federalreserve.gov — no API needed.

### 7.4 Earnings Calendar

Sourced from `yfinance.Ticker().calendar` which returns the next earnings date. For precise earnings time (pre/post market), cross-check with `yfinance.Ticker().earnings_dates`. Cache for 12 hours.

### 7.5 Caching Strategy (SQLite)

```
Table: cache
  key TEXT PRIMARY KEY        -- "{ticker}_{data_type}_{date}"
  value BLOB                  -- JSON or pickle
  fetched_at TIMESTAMP
  ttl_seconds INTEGER

TTLs:
  ohlcv_history      → 3600   (1 hour)
  options_chain_live → 900    (15 minutes, Schwab)
  options_chain_yf   → 1800   (30 minutes, yfinance)
  fundamentals       → 86400  (24 hours, SEC EDGAR)
  fred_rates         → 21600  (6 hours)
  earnings_dates     → 43200  (12 hours)
  fomc_calendar      → static (annual update)
  schwab_oauth_token → stored in keystore, not SQLite
```

---

## 8. Trade Recommendation Engine

### 8.1 Go/No-Go Decision Matrix (20 Points)

**Hard disqualifiers — any one triggers NO-GO regardless of score:**
- VRP not statistically significant: p-value > 0.10 (binomial test)
- Earnings within expiration DTE window
- EV_real ≤ 0 (slippage-adjusted)
- VoV Z-score > 2.5 (IV too unstable)
- Regime = CRISIS (VIX > 40)
- Altman Z in Distress Zone for CSP/collar stock leg
- jump_pct > 50% (jump risk dominates)
- **CSP selected for China ADR (Tier 6B) or China ETF (Tier 1E)** — defined-risk structures only (VIE structure / delisting risk makes stock assignment unacceptable)
- **CSP or Strangle selected for Crypto ETF (Tier 1I)** — Spread/Collar only
- **Crypto ETF (Tier 1I) entry attempted on Thursday afternoon (after 2 PM ET) or Friday** — weekend gap risk; no new positions into weekend close
- **Leveraged ETF (INDL, YINN, or any 2×/3× fund) selected for CSP** — Spread/Collar only; assignment is never acceptable on leveraged ETFs

**Scored factors (all must pass Hard Disqualifiers first):**

| Factor | Points | Type |
|--------|--------|------|
| VRP Percentile > 65th | 3 | Strong |
| VRP Persistence > 65% | 2 | Strong |
| VRP momentum ≤ 0 (falling or stable) | 1 | Entry timing |
| HAR-RV forecast < IV (VRP positive on forecast basis) | 2 | Strong |
| EM_Ratio > 1.20 | 2 | Strong |
| No earnings in DTE window | 2 | Required |
| Excess VRP > 0 (idiosyncratic) | 2 | Strong |
| Skew Z-score > 0.5 (elevated put demand) | 1 | Moderate |
| Term slope: contango (IV60 > IV30) | 1 | Moderate |
| GEX positive | 1 | Moderate |
| PCR OI > 1.2 | 1 | Moderate |
| VoV Z-score < 1.0 (IV stable) | 1 | Moderate |
| Fundamental Score ≥ tier minimum | 2 | Required for stock-leg structures |
| **Total possible** | **21** | |

**Thresholds:**
- ≥ 16 pts + all Required: **GO — High Confidence**
- 12–15 pts + all Required: **GO — Moderate Confidence**
- 8–11 pts: **MARGINAL — 50% size, explicit caveats**
- < 8 pts or any Hard Disqualifier: **NO-GO** (specific reason shown)

### 8.2 Trade Structure Selection

```python
def select_structure(tier, fundamental_score, vrp_score, iv30, skew_25d,
                     beta, stock_price, portfolio_value, max_pos_pct,
                     existing_holding=False, asset_class=None, is_leveraged=False):

    max_pos = portfolio_value * max_pos_pct
    csp_capital = stock_price * 100

    # Asset-class hard mandates — checked before all tier logic
    if asset_class == "crypto_etf":
        return "Short Put Spread", "Crypto ETF: Spread/Collar only (2% max; no Thursday/Friday entry)"
    if asset_class == "china_adr" or asset_class == "china_etf":
        return "Short Put Spread", "China exposure: defined-risk mandate (VIE structure/delisting risk — no assignment)"
    if is_leveraged:
        return "Short Put Spread", "Leveraged ETF: Spread/Collar only — assignment on leveraged products is prohibited"

    # Tier 4/5/micro-cap: Collar only — non-negotiable
    if tier >= 4:
        return "Zero-Cost Collar", "Tier mandate: collar required for small/micro-cap assignment risk"

    # Existing holding + elevated call premium
    if existing_holding and skew_25d < 0:  # call skew elevated
        return "Covered Call", "Existing position + elevated call IV: sell covered call against shares"

    # CSP: ideal when fundamentals strong + capital allows + stock is one we'd want to own
    if tier <= 3 and fundamental_score >= 75 and csp_capital <= max_pos:
        return "Cash-Secured Put", "Strong fundamentals + affordable contract: accept assignment risk"

    # Spread: CSP too capital-heavy or fundamentals borderline
    if tier <= 4 and fundamental_score >= 45:
        if iv30 > 35 and abs(skew_25d) < 2.5 and beta < 1.3:
            return "Short Strangle / Iron Condor", "High symmetric IV + low beta: capture both-sided premium with defined risk"
        return "Short Put Spread", "Defined risk: spread caps loss, maintains premium collection"

    # Collar: fundamentals borderline (40–60) but VRP is worth the trade
    if 40 <= fundamental_score < 65:
        return "Zero-Cost Collar", "Borderline fundamentals: collar provides assignment protection at no cost"

    return "Short Put Spread", "Default: defined risk"
```

### 8.3 Strike Selection

```python
def select_short_put_strike(chain_puts, vrp_pctile, vov_zscore, em_ratio):
    """
    Kelly-optimal delta selection:
    Higher VRP → more edge → take more delta (higher premium)
    High VoV → IV unstable → stay further OTM (lower delta)
    """
    base_delta = 0.25

    # VRP adjustment: ±5 delta points based on percentile
    vrp_adj = 0.05 * (vrp_pctile - 0.65) / 0.35  # scales −0.05 to +0.05 from 65th to 100th

    # VoV penalty: elevated VoV → move OTM
    vov_adj = -0.05 * max(vov_zscore - 1.0, 0)  # reduce delta if VoV > 1σ above mean

    target_delta = np.clip(base_delta + vrp_adj + vov_adj, 0.10, 0.35)

    # Find the 3 closest puts
    chain_puts['delta_diff'] = (chain_puts['delta'].abs() - target_delta).abs()
    candidates = chain_puts.nsmallest(5, 'delta_diff')

    # Filter: OI > 200, spread < 12% of mid
    valid = candidates[
        (candidates['openInterest'] > 200) &
        ((candidates['ask'] - candidates['bid']) / ((candidates['ask'] + candidates['bid'])/2) < 0.12)
    ]
    return valid.iloc[0] if len(valid) > 0 else candidates.iloc[0]
```

### 8.4 Zero-Cost Collar Strike Selection

```python
def collar_strikes(chain, stock_price, max_net_debit_pct=0.003):
    """
    Find (put, call) pair achieving near-zero cost.
    max_net_debit_pct: max acceptable debit as % of stock price (default 0.3%)
    """
    max_debit = stock_price * max_net_debit_pct
    puts  = chain.puts[(chain.puts['delta'].abs() > 0.15) & (chain.puts['delta'].abs() < 0.45)]
    calls = chain.calls[(chain.calls['delta'].abs() > 0.15) & (chain.calls['delta'].abs() < 0.40)]
    calls = calls[calls['strike'] > stock_price]  # calls must be OTM

    best = None; best_cost = float('inf')
    for _, put in puts.iterrows():
        for _, call in calls.iterrows():
            net = put['ask'] - call['bid']  # positive = debit
            if net <= max_debit and abs(net) < best_cost:
                best_cost = abs(net)
                best = (put, call, net)
    return best
```

### 8.5 DTE Selection

```python
def select_expiration(available_exps, today, earnings_date, fomc_dates,
                      min_dte=25, max_dte=50, ideal_dte=38):
    candidates = []
    for exp in available_exps:
        dte = (exp - today).days
        if not (min_dte <= dte <= max_dte):
            continue
        # Disqualify if earnings in window
        if earnings_date and today < pd.Timestamp(earnings_date) < exp:
            continue
        # Flag (but don't disqualify) if FOMC in window
        fomc_flag = any(today < pd.Timestamp(f) < exp for f in fomc_dates)
        candidates.append((abs(dte - ideal_dte), exp, dte, fomc_flag))

    candidates.sort()
    return candidates[0][1:] if candidates else (None, None, False)  # (exp, dte, fomc_flag)
```

### 8.6 Slippage-Adjusted EV — Per-Leg Model

```python
SLIPPAGE_FACTOR = 0.75  # configurable; 0.75 = give up 75% of spread

def multi_leg_ev(legs: list, pop: float, max_loss_per_share: float,
                 profit_target_pct: float, dte: int,
                 capital_required: float, avg_daily_vol: int,
                 position_contracts: int) -> dict:
    """
    legs: [(bid, ask, direction, contracts)] where direction: +1=sell, -1=buy
    """
    net_credit_mid = sum((b+a)/2 * d * c for b,a,d,c in legs)
    slippage_total = sum((a-b) * SLIPPAGE_FACTOR * abs(c) for b,a,d,c in legs)

    # Market impact: if position > 5% of ADV, add extra friction
    position_as_pct_adv = position_contracts / max(avg_daily_vol, 1)
    market_impact = max(0, (position_as_pct_adv - 0.05) / 0.05) * 0.5 * (
        sum((a-b) for b,a,d,c in legs) / len(legs)  # avg spread
    )

    net_credit_real = net_credit_mid - slippage_total - market_impact
    avg_win  = net_credit_real * profit_target_pct
    avg_loss = max_loss_per_share - net_credit_real

    ev_exp = net_credit_real * pop - avg_loss * (1-pop)
    return {
        'net_credit_mid':  round(net_credit_mid, 3),
        'net_credit_real': round(net_credit_real, 3),
        'slippage':        round(slippage_total, 3),
        'market_impact':   round(market_impact, 3),
        'ev_theoretical':  round(net_credit_mid * pop - avg_loss*(1-pop), 2),
        'ev_real':         round(ev_exp, 2),
        'ev_per_day':      round(ev_exp / dte, 3),
        'ev_pct_capital':  round(ev_exp / capital_required * 100, 3),
        'go':              ev_exp > 0 and ev_exp / capital_required > 0.002,  # > 0.2% of capital
    }
```

### 8.7 Position Sizing — Fractional Kelly + Adjustments

```python
def position_size(win_rate, avg_win, avg_loss, portfolio_value,
                  kelly_fraction=0.25, regime_mult=1.0,
                  vov_mult=1.0, gex_mult=1.0, max_pos_pct=0.05):
    """
    Stacked multipliers: regime × VoV-adjusted × GEX-adjusted × hard cap
    win_rate: VRP persistence (30d); avg_win/avg_loss per share
    """
    p = win_rate
    b = avg_win / max(avg_loss, 0.01)
    full_kelly = (p*b - (1-p)) / b
    adjusted = max(0, full_kelly * kelly_fraction * regime_mult * vov_mult * gex_mult)
    position_frac = min(adjusted, max_pos_pct)

    return {
        'full_kelly_pct':      round(full_kelly * 100, 2),
        'fractional_kelly_pct':round(adjusted * 100, 2),
        'final_pct':           round(position_frac * 100, 2),
        'dollars':             round(portfolio_value * position_frac, 0),
    }

# VoV multiplier: reduce size when IV is unstable
vov_mult = 1.0 - max(0, min(0.50, (vov_zscore - 1.0) * 0.25))

# GEX multiplier: reduce size when dealers are short gamma (amplifying moves)
gex_mult = 1.0 if gex_billions >= 0 else max(0.6, 1.0 + gex_billions * 0.1)
```

### 8.8 Four-Scenario P&L Analysis

This is the centerpiece of capital preservation. Every recommendation displays what happens across four possible outcomes, with estimated probability and dollar P&L at expiration.

```python
def scenario_analysis(short_strike, expiration_dte, net_credit_real,
                      max_loss, stock_price, rv_ensemble,
                      regime_mult, structure: str, asset_class: str = None) -> list:
    """
    Four scenarios based on vol trajectory over the trade duration.
    Probabilities estimated from log-normal return distribution.
    Crypto ETFs use wider shocks (±20% bear/bull, ±50% crash/moon).
    """
    from scipy.stats import norm

    is_crypto = (asset_class == "crypto_etf")

    # Scenario definitions (annualized IV assumptions for each)
    # Crypto ETF: wider shocks due to 24/7 underlying and extreme vol regime
    scenarios = [
        {
            'name': 'Bull — Vol Collapses',
            'iv_delta': -10.0 if is_crypto else -5.0,
            'description': ('BTC/ETH surges; IV collapses sharply' if is_crypto
                           else 'IV falls sharply; underlying stable or rising'),
            'prob_raw': 0.30,
        },
        {
            'name': 'Base — Vol Flat',
            'iv_delta': 0.0,
            'description': ('Crypto consolidates; IV unchanged' if is_crypto
                           else 'IV unchanged; underlying moves within expected range'),
            'prob_raw': 0.42,
        },
        {
            'name': 'Bear — Vol Spikes',
            'iv_delta': +20.0 if is_crypto else +8.0,
            'description': ('Crypto selloff -20% to -35%; IV spikes hard' if is_crypto
                           else 'Market selloff; underlying -8% to -15%'),
            'prob_raw': 0.20,
        },
        {
            'name': 'Crash — Vol Spikes Hard',
            'iv_delta': +50.0 if is_crypto else +20.0,
            'description': ('Crypto crash -50%+; exchange/regulatory shock' if is_crypto
                           else 'Market crash or idiosyncratic event; underlying -20%+'),
            'prob_raw': 0.08,
        },
    ]

    # Normalize probabilities
    total = sum(s['prob_raw'] for s in scenarios)
    for s in scenarios:
        s['probability'] = s['prob_raw'] / total

    # Compute P&L for each scenario
    days = expiration_dte
    for s in scenarios:
        implied_move = (rv_ensemble + s['iv_delta']/100) * np.sqrt(days/252)
        spot_at_expiry = stock_price * np.exp(-0.5 * implied_move)  # bear tilt

        if structure == "Cash-Secured Put":
            if spot_at_expiry >= short_strike:
                # Expires worthless: collect full premium
                pnl = net_credit_real * 100
                pnl_pct = net_credit_real / short_strike
                outcome = "Full premium collected"
            else:
                # Assigned: own stock at effective price = strike - credit
                intrinsic = short_strike - spot_at_expiry
                pnl = (net_credit_real - intrinsic) * 100
                pnl_pct = pnl / (short_strike * 100)
                outcome = f"Assigned at ${short_strike:.0f}; stock at ${spot_at_expiry:.2f}"
        # (similar logic for spread, strangle, condor)

        s['pnl_per_contract'] = round(pnl, 0)
        s['pnl_pct'] = round(pnl_pct * 100, 2)
        s['outcome_description'] = outcome

    ev_weighted = sum(s['probability'] * s['pnl_per_contract'] for s in scenarios)

    return scenarios, round(ev_weighted, 0)
```

### 8.9 Exit Decision Tree

A complete flowchart displayed to the trader covering all possible mid-trade states:

```
TRADE OPENED
├── At 50% of net credit received:
│   └── CLOSE POSITION — Profit target hit. Best risk-adjusted outcome. Do not get greedy.
│
├── At 200% of net credit received (option value = 3× original credit):
│   └── CLOSE POSITION — Hard stop. Take the loss. Do not average down.
│
├── Short put reaches 50Δ (CSP only):
│   ├── If DTE > 21 and VRP_signal still GO → EVALUATE ROLL:
│   │   └── Roll down-and-out IF net credit from roll > 25% of current loss
│   │       AND new position still passes Go/No-Go
│   │       AND no earnings in new window
│   │   └── Else → CLOSE (maximum 1 roll per position — do not compound)
│   └── If DTE ≤ 21 → CLOSE (gamma explosion risk)
│
├── At 21 DTE:
│   ├── If PnL ≥ profit target: CLOSE (time stop — protect gains)
│   ├── If PnL between 0% and target: CLOSE (theta decay slowing, gamma rising)
│   └── If PnL < 0 (at or near stop): CLOSE OR ROLL per above rules
│
├── Fundamental deterioration during trade:
│   └── If Fundamental Score drops below tier minimum: CLOSE IMMEDIATELY
│       (The reason for entering the trade has changed)
│
├── Earnings announced within DTE window after entry:
│   └── CLOSE before earnings — the event risk disqualifier applies retroactively
│
├── VIX crosses 40 (Crisis regime) after entry:
│   └── CLOSE or hedge all positions — the risk environment has fundamentally changed
│
└── At expiration (if not exited earlier):
    ├── Out of the money: Expires worthless. Full premium collected.
    └── In the money (CSP): Take assignment IF fundamental score still ≥ tier min.
        Else: close or roll before expiration.
```

---

## 9. Trade Reasoning Module

The most important user-facing output. Every recommendation includes three written paragraphs generated from quantitative data using template-based natural language. This makes the recommendation self-explanatory without requiring the user to interpret raw numbers.

### 9.1 VRP Attribution Narrative (Why Does This Premium Exist?)

Template system that combines the 3–4 highest-scoring signal factors into a coherent paragraph:

**Structural driver identification**:
- If `skew_zscore > 1.0 AND pcr_oi > 1.4`: → "Market participants are actively purchasing protection on [TICKER]. The 25Δ put skew of X.X vol points (Yth percentile) reflects institutional hedging demand that structurally elevates put premiums above fair value. The put-call OI ratio of [PCR] confirms elevated defensive positioning."
- If `excess_vrp > 2.0`: → "The VRP for [TICKER] is X.X vol points above what its beta of [BETA] to SPY would predict (excess VRP: +[EXCESS] pts). This idiosyncratic premium is not explained by general market vol — it represents a structural, ticker-specific source of edge."
- If `term_slope > 0 AND term_slope_pctile > 70`: → "The IV term structure is in [Nth percentile] contango (IV60 − IV30 = +[SLOPE] pts), confirming that near-term vol is structurally elevated relative to long-dated expectations. This is characteristic of steady premium availability, not a vol spike to fade."
- If `gex_billions > 0.5`: → "Dealer gamma exposure of +$[GEX]B indicates market makers are net long gamma on this underlying. Their delta-hedging activity systematically dampens daily price moves, compressing realized vol below implied vol — the mechanical engine of VRP collection."
- If `jump_pct < 20`: → "The premium is [JUMP_PCT]% attributable to continuous (diffusive) variance, with the remainder from jump risk. This is the cleanest signal type — the most reliably collected component of VRP."

**Reliability assessment**:
- "This premium has been positive in [PERSIST_30D×100]% of the past 30 sessions (VRP persistence). Over the past year, it has been positive [PERSIST_252D×100]% of the time — [SIGNIFICANCE: statistically significant at p=[P_VALUE]] / [not statistically significant at p=[P_VALUE] — reduced confidence]."
- "The current VRP of +[VRP] vol pts is at its [VRP_PCTILE]th percentile of the past year (Z-score: [Z]). The VRP Sharpe of [SHARPE] indicates [HIGH/MODERATE/LOW] risk-adjusted quality of the premium stream."

### 9.2 Entry Timing Narrative (Why Enter Now vs. Wait?)

```python
def generate_timing_narrative(timing_signal, vrp_momentum, fomc_context,
                               vix_regime, vov_zscore, vix_intraday_pattern) -> str:
    lines = []

    # Timing recommendation
    action, reason = timing_signal
    lines.append(f"**Entry timing: {action}.** {reason}")

    # VRP direction
    if vrp_momentum == 1:  # rising
        lines.append(f"VRP has risen {abs(vrp_5d_change):.1f} vol pts over the past 5 sessions. "
                     f"This is typically a sign of expanding premium opportunity — "
                     f"waiting 1–3 days may yield a slightly better entry, "
                     f"but at {vrp_pctile}th percentile, the current premium is already well above average.")
    else:
        lines.append(f"VRP has contracted {abs(vrp_5d_change):.1f} vol pts over the past 5 sessions. "
                     f"Premium is declining toward its mean — entering now captures "
                     f"premium before further compression.")

    # FOMC context
    if fomc_context[0] == 'PRIORITY ENTRY':
        lines.append("FOMC concluded recently. Post-meeting vol crush is in progress — "
                     "this is one of the highest-probability short-vol entry windows.")
    elif fomc_context[0] == 'AVOID':
        lines.append(f"⚠ FOMC in {fomc_days} days. Entering today means being short vol "
                     f"through the announcement. Consider waiting for post-FOMC entry.")
    elif fomc_context[0] == 'FOMC IN WINDOW':
        lines.append(f"Note: FOMC on {fomc_date} falls within this expiration window. "
                     f"The meeting contributes approximately 0.5–1.5 vol pts of event premium "
                     f"— collect if the meeting resolves without surprise; assess at 21 DTE.")

    # Intraday entry
    lines.append("For intraday entry: prefer the 10:30 AM – 11:30 AM ET window "
                 "(after open volatility settles) or a minor intraday spike in VIX or "
                 "dip in the underlying. Place limit orders at real net credit; "
                 "do not chase by crossing more than 15% of the spread.")

    return "\n".join(lines)
```

### 9.3 Risk Narrative (What Could Go Wrong?)

```python
def generate_risk_narrative(ticker, structure, short_strike, stock_price,
                             fundamental_score, jump_pct, vov_zscore,
                             gex_billions, vrp_driver, fomc_in_window,
                             earnings_days_away) -> str:
    risks = []

    # Jump risk
    if jump_pct > 20:
        risks.append(f"**Idiosyncratic jump risk**: {jump_pct:.0f}% of the implied variance "
                     f"reflects jump compensation, not diffusive vol. A discrete price event "
                     f"(surprise announcement, sector news) could cause the underlying to gap "
                     f"through the short strike immediately, bypassing the stop loss.")

    # Fundamental risk (for stock-leg structures)
    if structure in ('Cash-Secured Put', 'Zero-Cost Collar') and fundamental_score < 70:
        risks.append(f"**Assignment quality**: Fundamental score of {fundamental_score}/100 "
                     f"is above the minimum threshold but not exceptional. Assignment at "
                     f"${short_strike:.0f} yields an effective cost basis of "
                     f"${short_strike - 0:.2f} (strike minus credit). "
                     f"Ensure you are comfortable holding this underlying for 3–6 months "
                     f"if assigned.")

    # GEX risk
    if gex_billions < -0.3:
        risks.append(f"**Dealer gamma risk**: Dealer GEX of ${gex_billions:.1f}B is negative — "
                     f"market makers are net short gamma and will amplify moves in this "
                     f"underlying. Daily moves may be larger than historical averages, "
                     f"compressing VRP faster than normal or triggering the stop loss "
                     f"sooner than expected.")

    # VoV risk
    if vov_zscore > 1.0:
        risks.append(f"**Regime instability**: Vol-of-Vol Z-score of {vov_zscore:.1f} indicates "
                     f"implied vol itself has been unusually volatile over the past 30 sessions. "
                     f"The VRP signal may be less reliable than the historical statistics suggest.")

    # FOMC risk
    if fomc_in_window:
        risks.append("**FOMC event risk**: The Federal Reserve meeting falls within this "
                     "expiration window. An unexpected policy shift or hawkish/dovish "
                     "surprise can produce an intraday vol spike of 3–8 vol pts, "
                     "which may breach the stop loss or dramatically alter the P&L profile. "
                     "Monitor closely around the FOMC date.")

    # VRP driver risk
    if vrp_driver == 'event_uncertainty':
        risks.append("**Event-driven premium**: A portion of this VRP appears to compensate "
                     "for near-term uncertainty rather than structural hedging demand. "
                     "When the uncertainty resolves, the premium may collapse faster than "
                     "theta decay suggests.")

    # Earnings risk (outside window but approaching)
    if 45 < earnings_days_away < 90:
        risks.append(f"**Upcoming earnings**: Earnings expected in ~{earnings_days_away} days — "
                     f"outside this expiration window but approaching. If this trade is "
                     f"rolled or entered again, ensure the next cycle clears the earnings date.")

    risk_text = "\n".join(f"• {r}" for r in risks) if risks else "• No elevated risks identified beyond standard short-vol exposure."
    return risk_text
```

### 9.4 Complete Recommendation Card Format

```
╔══════════════════════════════════════════════════════════════════════════╗
║  TRADE RECOMMENDATION                        Generated: [TIMESTAMP]     ║
║  [TICKER] — [Company Name]          Tier [N] | [SCORE]/100 VRP Score    ║
╠══════════════════════════════════════════════════════════════════════════╣
║  ████████████████░░░ GO — [High/Moderate] Confidence ([N]/21 points)    ║
╠══════════════════════════════════════════════════════════════════════════╣
║  TRADE DETAILS                                                          ║
║  ┌──────────────────────────────────────────────────────────────────┐   ║
║  │ [MANUAL ORDER TEXT]                                              │   ║
║  │ Example: SELL 2 XLE Apr17'26 $84 PUT @ $1.77 LIMIT              │   ║
║  └──────────────────────────────────────────────────────────────────┘   ║
║  Structure: [NAME] | Strike: $[X] ([DELTA]Δ) | Exp: [DATE] ([DTE] DTE)║
║  Mid Credit: $[CREDIT]/share | Net Real Credit: $[REAL]/share (after slip)║
║  PoP: [POP]% | Contracts: [N] | Capital: $[CAP] ([PCT]% of portfolio)  ║
╠══════════════════════════════════════════════════════════════════════════╣
║  VRP SIGNALS                        MICROSTRUCTURE                      ║
║  VRP (HAR): +[VRP] pts              GEX: +$[N]B [Dampening ✅]         ║
║  VRP %ile:  [N]th                   PCR OI: [N] [Hedging demand ✅]     ║
║  Persist:   [N]% (30d)              VoV Z: [N] [Stable ✅]              ║
║  Z-score:   [N]σ | Sharpe: [N]     EM Ratio: [N]× [Elevated ✅]        ║
║  Excess VRP: +[N] pts               Jump %: [N]% [Clean ✅]             ║
║  Skew 25Δ:  +[N] pts ([N]th %ile)                                       ║
║  IVR: [N]% | IVP: [N]%             TIMING: [ENTER NOW / WAIT]          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  WHY THIS PREMIUM EXISTS                                                ║
║  [Generated attribution narrative — 3–4 sentences]                     ║
╠══════════════════════════════════════════════════════════════════════════╣
║  WHY ENTER NOW                                                          ║
║  [Generated timing narrative — 2–3 sentences + FOMC note if relevant]  ║
╠══════════════════════════════════════════════════════════════════════════╣
║  SCENARIO ANALYSIS                                                      ║
║  ┌─────────────────────┬───────────┬──────────────────────────────────┐ ║
║  │ Scenario            │ Prob.     │ P&L / contract (at target/expiry)│ ║
║  ├─────────────────────┼───────────┼──────────────────────────────────┤ ║
║  │ Bull: Vol −5 pts    │ 30%       │ +$[N] (full premium)             │ ║
║  │ Base: Vol flat      │ 42%       │ +$[N] (at 50% target)            │ ║
║  │ Bear: Vol +8 pts    │ 20%       │ −$[N] (near stop)                │ ║
║  │ Crash: Vol +20 pts  │ 8%        │ −$[N] (max loss)                 │ ║
║  ├─────────────────────┼───────────┼──────────────────────────────────┤ ║
║  │ EV (weighted)       │           │ +$[N] per contract               │ ║
║  └─────────────────────┴───────────┴──────────────────────────────────┘ ║
╠══════════════════════════════════════════════════════════════════════════╣
║  EXITS                                                                  ║
║  Profit: Close at $[TARGET] debit (50% of $[CREDIT] real credit)        ║
║  Stop:   Close if option value reaches $[STOP] (200% of credit)         ║
║  Delta:  Close if short put reaches 50Δ                                 ║
║  Time:   Close at 21 DTE if < 50% profit reached                        ║
║  Roll:   If at stop AND > 21 DTE: roll down-and-out for credit          ║
║          (only if additional credit > 25% of loss AND VRP still GO)     ║
╠══════════════════════════════════════════════════════════════════════════╣
║  POSITION SIZE                                                          ║
║  Kelly full: [N]% → Fractional (25%): [N]% → Regime (×[N]): [N]%      ║
║  VoV adj (×[N]) → GEX adj (×[N]) → Final: [N]% = $[N] ([N] contracts)  ║
║  Portfolio VaR contribution (1d 99%): [N]% of portfolio                ║
╠══════════════════════════════════════════════════════════════════════════╣
║  WHAT COULD GO WRONG                                                    ║
║  [Generated risk narrative — bullet points from risk module]            ║
╠══════════════════════════════════════════════════════════════════════════╣
║  FUNDAMENTALS (Assignment Quality)   Score: [N]/100 [TIER N MINIMUM: N] ║
║  Piotroski F: [N]/9 | Altman Z': [N] ([Zone]) | QoE: [N] [✅/⚠/🚨]    ║
║  [Key fundamental ratios: P/E, P/TBV, FCF yield, debt/equity, etc.]    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 10. Fundamentals: Forensic Accounting & Margin of Safety

*(Full specification carried from v3.0 — restated concisely here)*

### 10.1 Hard Disqualifiers for Any Stock-Leg Trade

| Test | Threshold | Data |
|------|-----------|------|
| Accrual anomaly | CFO/Net Income < 0 for TTM (cash flow negative while reporting profit) | SEC EDGAR |
| QoE ratio | CFO/Net Income < 0.5 for 4+ quarters | SEC EDGAR |
| Inventory/receivables divergence | AR or inventory growing > 3× revenue YoY | SEC EDGAR |
| Altman Z'/Z'' | Distress zone (Z' < 1.23; Z'' < 1.10) | Computed |
| Piotroski F-Score | F < 4 | Computed |
| Interest coverage | EBIT/InterestExpense < 1.5 | SEC EDGAR |
| Market cap | < $150M (below Tier 6 minimum) | yfinance |
| Consecutive net losses | 2+ consecutive annual net losses | SEC EDGAR |
| FCF negative | 4+ consecutive quarters with negative FCF | SEC EDGAR |

### 10.2 Altman Z by Company Type

```python
# Z (1968): publicly traded manufacturers
# Z' (1983): non-manufacturers (tech, services, most public companies) — use this by default
# Z'' (1995): emerging markets or private companies

def altman_zp(wc_ta, re_ta, ebit_ta, mve_tl):
    """Z' model for non-manufacturer public companies."""
    z = 6.56*wc_ta + 3.26*re_ta + 6.72*ebit_ta + 1.05*mve_tl
    if z < 1.23:   return z, "Distress"
    elif z < 2.90: return z, "Gray Zone"
    else:          return z, "Safe"
```

Financial companies (banks, REITs, insurers) are scored using Interest Coverage Ratio and Tier 1 capital ratio only — Altman Z does not apply.

### 10.3 Piotroski F-Score (9 Binary Factors, 0–9)

```
Profitability (4 points):
  F1: ROA > 0 (positive return on assets)
  F2: Operating CFO > 0
  F3: ROA improving YoY
  F4: Accrual quality: CFO/Total Assets > ROA (earnings are cash-backed)

Leverage/Liquidity (3 points):
  F5: Long-term debt ratio decreased YoY
  F6: Current ratio improved YoY
  F7: No new shares issued in past year (no dilution)

Operating Efficiency (2 points):
  F8: Gross margin expanded YoY
  F9: Asset turnover increased YoY
```

### 10.4 Margin of Safety Composite Score (0–100)

| Factor | Weight | Scoring |
|--------|--------|---------|
| Earnings yield premium (E/P − T-bill yield) | 25% | Requires > 400bps; scales 0→400bps linearly |
| Price-to-Tangible Book Value | 20% | P/TBV < 1.5 → max; > 5.0 → 0 (inverse) |
| Interest coverage (EBIT/Interest) | 20% | < 1.5 → 0; > 5.0 → max |
| FCF yield (FCF/Price) | 15% | < 0% → 0; > 8% → max |
| Debt/Tangible Equity | 10% | < 0.5 → max; > 3.0 → 0 (inverse) |
| Revenue growth (1yr) | 10% | < −10% → 0; > 10% → max |

```
Fundamental_Score = 0.45 × (F_score/9 × 100) + 0.55 × MOS_score
```

The weighting favors MOS (valuation) over quality — it is better to be assigned on a cheap adequate company than an expensive excellent one.

---

## 11. Risk Management Framework

### 11.1 Position-Level Rules

| Rule | Default | Configurable |
|------|---------|-------------|
| Profit target | 50% of max credit | 25% / 50% / 75% |
| Hard stop | 200% of credit received | Yes |
| Spread stop | 75% of max spread width | Yes |
| Delta stop (naked) | 50Δ breach | Yes |
| Time stop | 21 DTE | Yes |
| Max rolls | 1 | No — hard limit |
| Roll credit minimum | > 25% of current loss | No |

### 11.2 Portfolio-Level Rules

| Rule | Default |
|------|---------|
| Max short vol exposure | 30% of portfolio |
| Max single position | 5% of portfolio |
| Max single sector (beta-weighted) | 10% of portfolio |
| Max Tier 5/6 combined | 10% of portfolio |
| Max correlated positions (β>0.7 pairs count as 1) | Enforced per sector limit |
| Max simultaneous positions | 12 |
| New position ban (VIX > 40) | Hard rule |
| New position ban (VoV Z > 2.5) | Hard rule |

### 11.3 Rolling Portfolio Correlation Matrix

Updated with each Quick Refresh. Flags pairs with ρ > 0.70:

```python
def portfolio_correlation_matrix(holdings: list, returns_window: int = 60) -> pd.DataFrame:
    """
    Compute pairwise return correlations for all open positions.
    Uses 60-day rolling return series from OHLCV cache.
    """
    returns = {h['ticker']: get_returns(h['ticker'], window=returns_window)
               for h in holdings}
    corr_matrix = pd.DataFrame(returns).corr()
    flagged_pairs = [(i, j, corr_matrix.loc[i, j])
                     for i in corr_matrix.index for j in corr_matrix.columns
                     if i < j and corr_matrix.loc[i, j] > 0.70]
    return corr_matrix, flagged_pairs
```

When a pair is flagged (ρ > 0.70), the system warns: "Your [TICKER_A] and [TICKER_B] positions are highly correlated (ρ=[N]). Under market stress, these positions will move together — your effective portfolio risk is higher than it appears."

### 11.4 Conditional VaR (CVaR / Expected Shortfall)

More conservative than parametric VaR. Answers: "Given that this trade loses money, what is the average loss?"

```python
def portfolio_cvar(positions: list, confidence: float = 0.99,
                   n_simulations: int = 10000) -> dict:
    """
    Monte Carlo CVaR for the options portfolio.
    For each position: simulate underlying return → compute option P&L via delta approximation
    """
    portfolio_pnl = np.zeros(n_simulations)
    for pos in positions:
        spot_returns = np.random.normal(
            pos['drift'],
            pos['rv_yz_21d'] / np.sqrt(252),
            n_simulations
        )
        # Delta approximation + gamma correction
        option_pnl = (pos['delta'] * spot_returns * pos['spot'] +
                      0.5 * pos['gamma'] * (spot_returns * pos['spot'])**2) * pos['contracts'] * 100
        portfolio_pnl += option_pnl

    var = np.percentile(portfolio_pnl, (1 - confidence) * 100)
    cvar = portfolio_pnl[portfolio_pnl <= var].mean()
    return {'var_1d_99pct': round(var, 0), 'cvar_1d_99pct': round(cvar, 0)}
```

### 11.5 Regime-Based Sizing Multipliers

| VIX | VVIX Z | Regime | Size Multiplier |
|-----|--------|--------|----------------|
| < 15 | Any | Low Vol | 0.50× |
| 15–20 | < 1.5 | Normal | 1.00× |
| 20–28 | < 1.5 | Elevated | 1.25× |
| 28–35 | Any | High | 0.75× |
| > 35 | Any | Crisis | 0.00× |
| Any | > 2.5 | Unstable | 0.25× (caps all other multipliers) |

### 11.6 Permanent Tail Hedge Recommendation

Display in portfolio overview (not per-trade):

"Recommended portfolio tail hedge: Buy 1–2% of portfolio notional in 90-DTE SPY puts, 5–7% OTM (≈10Δ), rolled every 60 days. Estimated annual cost: 0.3–0.7% of portfolio. This hedge will approximately double in value on a 15%+ SPY correction (VIX > 30), offsetting ~30% of short-vol losses from the portfolio. If portfolio short-vol exposure > 20%, this hedge is recommended."

---

## 12. UI/UX Specification

### 12.0 Desktop Application Delivery

This is a **local desktop application**. There is no hosted server, no cloud account, and no data leaves the user's machine.

**Installation**:
```bash
# 1. Clone or download the project
# 2. Install dependencies (Python 3.11+)
pip install -r requirements.txt

# 3. Run the app (opens in default browser automatically)
streamlit run app.py
```

**What "desktop app" means here**:
- Streamlit starts a local HTTP server on `localhost:8501` (or next available port)
- The system's default browser opens automatically to `http://localhost:8501`
- The server process runs on the user's machine — it has no internet-facing endpoint
- All SQLite cache files, OAuth tokens, configuration, and computed output are stored in the project's `data/` subdirectory on the local disk
- Closing the terminal/process shuts down the application completely
- No background sync, no telemetry, no external API calls except to Schwab (reads), yfinance, FRED, and SEC EDGAR when the user triggers a scan

**System requirements**: Windows 10+, macOS 12+, or Linux; Python 3.11+; 4 GB RAM minimum (8 GB recommended for full universe scan); Schwab brokerage account with Developer API access enabled.

**First-run Schwab OAuth setup**: On the very first launch, the app opens a browser tab to the Schwab login page. After the user logs in and grants "Market Data" scope access, the OAuth token is saved locally to `data/schwab_token.json` (encrypted). All subsequent runs auto-refresh the token silently.

---

### 12.1 Page Structure

**Page 1: Scanner Dashboard**
```
╔═════════════════════════════════════════════════════════════════════╗
║  VRP Screener v4          [Last Full Scan: 09:52 ET]  [● Live]     ║
║  [▶ Run Full Scan]  [↻ Quick Refresh]  [⊕ Custom Ticker]           ║
╠═════════════════════════════════════════════════════════════════════╣
║  REGIME BANNER (contextual — color-coded):                          ║
║  ● NORMAL  VIX: 19.2 (+0.3)  VVIX: 89.1  VIX3M-VIX: +1.8 Contango║
║  GEX (SPY): +$8.2B (Dampening)  3m T-Bill: 5.25%  Regime×: 1.0×  ║
╠═════════════════════════════════════════════════════════════════════╣
║  [Filters] VRP%>65 | Persist>60% | No Earn.14d | EV_real>0 | GO   ║
║                                                                     ║
║  Ticker│T│Score│IV30│VRP│VRP%│IVP│Persist│Excess│Skew│EM×│Earn│GO ║
║  ──────────────────────────────────────────────────────────────────║
║  XLE   │2│  88 │28.4│9.6│ 89 │ 82│  83%  │ +4.1 │3.4 │1.4│51d│GO ║
║  IWM   │1│  76 │24.1│7.8│ 76 │ 71│  73%  │ +2.2 │1.8 │1.3│N/A│GO ║
║  NVDA  │3│  64 │52.1│8.2│ 64 │ 59│  61%  │ +1.9 │6.2 │1.6│ 8d│⚠  ║ ← earnings
║  CROX  │4│  72 │38.7│9.1│ 77 │ 74│  71%  │ +3.1 │2.9 │1.5│62d│GO ║
║  [30+ rows; click row for full analysis]        [⬇ Export CSV]     ║
╚═════════════════════════════════════════════════════════════════════╝
```

**Page 2: Ticker Analysis (Full Recommendation Card)**
Renders the complete recommendation card from §9.4.

Supplementary charts below the card:
- IV Term Structure (line chart: IV vs. DTE for all expirations)
- VRP History + HAR-RV Forecast (1-year shaded area chart: IV30 vs. RV ensemble vs. VRP)
- IV Skew Chart (IV vs. delta for chosen expiration, with historical average overlay)
- Scenario P&L Chart (bar chart: four scenarios with color-coding)
- GEX History (line chart: 30-day GEX trend)

**Page 3: Custom Ticker Lookup**
```
Enter any US options ticker: [__________] [▶ Analyze]
→ Renders full Page 2 analysis for any valid ticker with options
```

**Page 4: Portfolio Correlation Monitor**
```
OPEN POSITIONS (manual entry — no auto-fetch of portfolio positions)
[+ Add Position]

CORRELATION MATRIX (60-day rolling)
     XLE  IWM  CROX
XLE  1.0  0.61  0.43
IWM  0.61 1.0   0.38
CROX 0.43 0.38  1.0
✅ No high-correlation pairs (all < 0.70)

PORTFOLIO METRICS
Short vol exposure: 18.3% of portfolio (limit: 30%) ✅
Total positions: 3 (limit: 12) ✅
1d 99% CVaR: −$2,840 (0.57% of portfolio) ✅
Tail hedge status: ⚠ Not confirmed (recommend 1% SPY puts, 90 DTE, 10Δ)
```

### 12.2 Configuration Sidebar

```
PORTFOLIO
├─ Total value: $500,000
├─ Max short vol: 30%
├─ Max per position: 5%
├─ Max positions: 12

TRADE DEFAULTS
├─ Target profit: 50%
├─ Hard stop: 200%
├─ Base delta: 25Δ
├─ Target DTE: 38 days
└─ Kelly fraction: 25%

SCREENING THRESHOLDS
├─ Min VRP percentile: 65th
├─ Min persistence: 60%
├─ Min EV_real: $25/contract
├─ Earnings exclusion: 14 days
└─ Max ATM spread: 12% of mid

SLIPPAGE MODEL
├─ Slippage factor: 0.75
└─ Market impact ADV threshold: 5%

UNIVERSE TIERS
├─ ETFs: [1A✓][1B✓][1C✓][1D✓][1E✓][1F✓][1G✓][1H✓][1I✓]
└─ Equities: [2✓][3✓][4✓][5✓][6A✓][6B✓][7✓]

SCHWAB API
└─ Status: [✅ Connected] Token: 22 min

CALENDARS
├─ FOMC dates: [2026 loaded ✅]
└─ Auto-refresh: [30 min ▼]
```

---

## 13. Technical Architecture

### 13.0 Desktop Application Architecture

This is a **single-user local desktop application** — not a web service.

```
USER'S MACHINE
┌─────────────────────────────────────────────────────────────────┐
│  Terminal / CLI                                                  │
│    └── streamlit run app.py ──→ Streamlit local server          │
│                                  (localhost:8501)               │
│                                         │                       │
│                                    Browser tab                  │
│                                  (auto-opens)                   │
│                                         │                       │
│         ┌───────────────────────────────┘                       │
│         ▼                                                       │
│   [Analytics Engine] ←── [SQLite Cache (data/cache.db)]        │
│         │                                                       │
│   [Schwab Fetcher] ──── HTTPS ──→ api.schwab.com/marketdata    │  ← READ ONLY
│   [yfinance Fetcher] ── HTTPS ──→ finance.yahoo.com            │  ← read only
│   [FRED Fetcher] ────── HTTPS ──→ api.stlouisfed.org           │  ← read only
│   [EDGAR Fetcher] ───── HTTPS ──→ data.sec.gov                 │  ← read only
│                                                                 │
│   [OAuth Token: data/schwab_token.json] ← local file only      │
│   [Config: data/config.json] ← local file only                 │
└─────────────────────────────────────────────────────────────────┘
```

**No external servers owned or operated by this application. No data sent externally. No accounts required beyond Schwab brokerage (already held by user).**

### 13.1 Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| UI | Streamlit | Serves locally on localhost only; opens in browser |
| Options Math | Custom BSM + scipy.optimize | Per-strike IV inversion |
| RV Models | NumPy, pandas, scikit-learn, arch | YZ, HAR-RV, GARCH(1,1), EWMA |
| Persistence | SQLite + SQLAlchemy | TTL-aware cache; settings; all local |
| Schwab Auth | schwab-py (official SDK) | OAuth2 lifecycle; Market Data scope only |
| Charts | Plotly via st.plotly_chart | IV surface, VRP history, scenarios |
| Scheduling | APScheduler | Auto-refresh; event trigger; runs in-process |
| Concurrency | ThreadPoolExecutor | Stage 1 parallel yfinance fetch |
| Smoothing | scipy.interpolate.PchipInterpolator | IV smile (no-arb cubic spline) |
| Secret Storage | keyring | OS keychain for Schwab credentials (not plaintext) |

### 13.2 Project Structure

```
vrp_screener/
├── app.py                        # Streamlit entry point, page routing
├── config.py                     # All user-configurable parameters
├── requirements.txt
│
├── data/
│   ├── cache.py                  # SQLite TTL-aware cache manager
│   ├── fetcher_yfinance.py       # Stage 1: bulk OHLCV + approx IV + fundamentals
│   ├── fetcher_schwab.py         # Stage 2: live options chains via schwab-py
│   ├── fetcher_fred.py           # Risk-free rates (DGS3MO), VIX history
│   ├── fetcher_edgar.py          # SEC EDGAR financial statements
│   └── options_parser.py         # BSM inversion, smile fitting, IV30 interpolation
│
├── analytics/
│   ├── realized_vol.py           # CC, Parkinson, GK, Yang-Zhang
│   ├── har_rv.py                 # HAR-RV OLS model
│   ├── garch_model.py            # GARCH(1,1) + GJR asymmetry
│   ├── ewma_model.py             # EWMA RV (RiskMetrics)
│   ├── ensemble.py               # 3-model ensemble average
│   ├── bipower_variation.py      # Jump separation
│   ├── implied_vol.py            # IV surface, ATM IV, IV30, smile smoothing
│   ├── vrp_signals.py            # All 12 signals + composite score
│   ├── gex.py                    # Dealer Gamma Exposure from options chain
│   ├── pcr.py                    # Put-Call Ratio
│   ├── vov.py                    # Vol of Vol (rolling std of IV30)
│   ├── vrp_momentum.py           # VRP rate of change + timing signal
│   ├── em_ratio.py               # Expected move vs. realized move ratio
│   ├── regime.py                 # VIX regime detection + VVIX overlay
│   └── scoring.py                # Composite VRP score (0–100)
│
├── recommender/
│   ├── go_nogo.py                # 21-point go/no-go matrix
│   ├── structure_selector.py     # Structure selection logic (tier-aware)
│   ├── collar.py                 # Zero-cost collar strike selection
│   ├── strike_dte.py             # Delta targeting, DTE selection, FOMC check
│   ├── slippage.py               # Per-leg slippage + market impact
│   ├── ev_calculator.py          # Multi-leg EV with slippage
│   ├── scenarios.py              # Four-scenario P&L analysis
│   ├── kelly.py                  # Fractional Kelly + regime/VoV/GEX multipliers
│   ├── var_cvar.py               # CVaR Monte Carlo
│   └── exit_tree.py              # Exit decision tree display
│
├── reasoning/
│   ├── attribution.py            # VRP attribution narrative generator
│   ├── timing.py                 # Entry timing narrative + FOMC context
│   ├── risk_narrative.py         # Risk factors narrative
│   └── order_text.py             # Manual order text generator
│
├── fundamentals/
│   ├── disqualifiers.py          # Hard NO-GO filters
│   ├── altman_z.py               # Z / Z' / Z'' by company type
│   ├── piotroski.py              # 9-factor F-Score from EDGAR
│   ├── margin_of_safety.py       # 6-factor MOS score
│   └── scorer.py                 # Combined fundamental score
│
└── ui/
    ├── scanner_table.py          # Main screener table
    ├── ticker_panel.py           # Full analysis + charts
    ├── recommendation_card.py    # Structured recommendation display
    ├── portfolio_monitor.py      # Correlation matrix + CVaR
    ├── charts.py                 # Plotly components
    └── sidebar.py                # Configuration panel
```

---

## 14. Implementation Phases

### Phase 1: Data Infrastructure & Core Analytics (~2.5 weeks)
- [ ] yfinance Stage 1 fetcher with parallel ThreadPoolExecutor
- [ ] Schwab OAuth2 integration via `schwab-py`; live options chain fetcher with rate limiter
- [ ] FRED fetcher (DGS3MO risk-free rate; VIX history)
- [ ] SEC EDGAR fetcher (company facts → FCF, revenue, debt)
- [ ] SQLite cache manager with TTL
- [ ] Yang-Zhang + GK + Parkinson RV calculators
- [ ] BSM per-strike IV inversion
- [ ] IV smile (PCHIP spline) + IV30 variance-time interpolation
- [ ] FOMC calendar loader; earnings date fetcher

**Milestone**: For any single ticker, correctly compute IV30, RV_YZ, and raw VRP. Display in Streamlit.

### Phase 2: Full Signal Suite (~2 weeks)
- [ ] HAR-RV (rolling OLS fit)
- [ ] GARCH(1,1) with GJR asymmetry (arch library)
- [ ] EWMA RV model
- [ ] Ensemble forecast average
- [ ] Bipower Variation + jump separation
- [ ] VRP history (252-day rolling), percentile, persistence, Z-score, Sharpe, significance
- [ ] Excess VRP (beta-adjusted vs. SPY VRP)
- [ ] 25Δ skew + Z-score + persistence
- [ ] Term structure slope
- [ ] GEX computation from Schwab chain
- [ ] PCR (OI and volume) from Schwab chain
- [ ] Vol of Vol (30-day rolling std of IV30)
- [ ] VRP momentum (5d and 10d change)
- [ ] EM ratio (straddle / historical expected move)
- [ ] Composite VRP score (0–100)
- [ ] Macro regime (VIX + VVIX)
- [ ] Binary Event Anomaly filter (IV30/IV60 ratio)

**Milestone**: Full screener table with all 12 signals for a 50-ticker test universe.

### Phase 3: Two-Stage Universe Scan (~1.5 weeks)
- [ ] Full Tier 1A–7 universe lists populated (all 16 sub-tiers, ~1,485 tickers total)
- [ ] Asset-class-specific constraint enforcement: Crypto ETF (Tier 1I) — Spread/Collar only, 2% max, no Thu/Fri entry, wider crash shocks; China ADRs (Tier 6B) — Spread/Collar only; Leveraged ETFs — Spread/Collar only
- [ ] Stage 1 bulk scan (yfinance parallel, 20 threads, all tiers)
- [ ] Stage 2 deep analysis pipeline (Schwab Market Data API, top 175 candidates)
- [ ] Cache warm-up strategy (preserve Stage 2 results between quick refreshes)
- [ ] Auto-refresh scheduler (APScheduler, in-process, no external daemon)
- [ ] Event-triggered refresh (VIX moves > 5% intraday)

**Milestone**: Full ~1,485 ticker universe scanned and displayed in < 50 minutes on a warm cache.

### Phase 4: Fundamentals & Forensics (~2 weeks)
- [ ] All hard disqualifiers (accrual, QoE, inventory divergence, interest coverage)
- [ ] Altman Z / Z' / Z'' (correct model by company type)
- [ ] Piotroski F-Score (9 factors from EDGAR)
- [ ] Margin of Safety (6-factor score)
- [ ] Combined fundamental score + per-tier minimum enforcement

**Milestone**: Every Tier 3–6 candidate has a fundamental score; disqualifiers block correctly.

### Phase 5: Recommendations, Scenarios & Reasoning (~2.5 weeks)
- [ ] 21-point Go/No-Go matrix
- [ ] Trade structure selector (all 7 structures)
- [ ] Collar strike selection
- [ ] Strike/DTE selection with FOMC calendar check
- [ ] Multi-leg slippage + market impact EV
- [ ] Four-scenario P&L analysis
- [ ] Kelly sizing + regime/VoV/GEX multipliers
- [ ] CVaR Monte Carlo
- [ ] Exit decision tree display
- [ ] Attribution narrative generator
- [ ] Entry timing narrative + FOMC integration
- [ ] Risk narrative generator
- [ ] Manual order text output
- [ ] Full recommendation card render

**Milestone**: Complete recommendation card with reasoning narratives for any qualifying ticker.

### Phase 6: Portfolio Monitor & Polish (~1 week)
- [ ] Portfolio correlation matrix (manual position entry)
- [ ] CVaR display in portfolio monitor
- [ ] Tail hedge recommendation
- [ ] Configuration sidebar (all parameters)
- [ ] Universe editor
- [ ] Black Swan alert banner
- [ ] CSV export of screener results
- [ ] Performance tuning (Stage 1 < 30 min; Stage 2 < 20 min; Quick Refresh < 5 min)
- [ ] IBKR TWS API adapter (same interface as Schwab fetcher — drop-in replacement for IBKR users)

---

## 15. Appendix: Reference Implementations

### A. GARCH(1,1) with GJR Asymmetry (arch library)
```python
from arch import arch_model
import numpy as np

def garch_forecast(returns: pd.Series, horizon: int = 21) -> float:
    """
    GJR-GARCH(1,1,1) with Student-t innovations.
    Asymmetry (leverage effect): negative returns increase vol more than positive.
    horizon: trading days to forecast (default 21)
    """
    model = arch_model(
        returns * 100,           # scale for numerical stability
        vol='Garch',
        p=1, o=1, q=1,          # GARCH(1,1) + 1 asymmetry term
        dist='t'                 # fat tails
    )
    res = model.fit(disp='off', show_warning=False)
    forecast = res.forecast(horizon=horizon, reindex=False)
    # Mean daily variance over forecast horizon → annualized vol
    mean_daily_var = forecast.variance.values[-1].mean() / 10000  # undo ×100 scaling
    return float(np.sqrt(mean_daily_var * 252))
```

### B. Implied Expected Move vs. Realized Expected Move
```python
def expected_move_ratio(atm_call_price: float, atm_put_price: float,
                        spot: float, rv_yz_21d: float, dte: int) -> float:
    """
    EM_Ratio = (straddle price / spot) / (RV_YZ × sqrt(DTE/252))
    > 1.0: options overpriced relative to recent realized moves
    > 1.3: significantly elevated — strong VRP signal
    """
    implied_move_pct = (atm_call_price + atm_put_price) / spot
    realized_move_pct = rv_yz_21d * np.sqrt(dte / 252)
    return implied_move_pct / realized_move_pct if realized_move_pct > 0 else 1.0
```

### C. IV Smile No-Arbitrage Check
```python
def check_smile_arbitrage(strikes: np.ndarray, ivs: np.ndarray, spot: float, r: float, T: float):
    """
    Butterfly arbitrage check: for any three strikes K1 < K2 < K3,
    the call/put prices must satisfy convexity.
    Flags if > 5% of strike triplets have arbitrage violations.
    """
    from scipy.stats import norm
    def bsm_call(S, K, r, T, sigma):
        d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
        d2 = d1 - sigma*np.sqrt(T)
        return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

    prices = [bsm_call(spot, K, r, T, iv) for K, iv in zip(strikes, ivs)]
    violations = 0
    for i in range(1, len(strikes)-1):
        butterfly = prices[i-1] - 2*prices[i] + prices[i+1]
        if butterfly < 0:
            violations += 1
    pct_violations = violations / max(len(strikes)-2, 1)
    return pct_violations < 0.05, pct_violations  # (is_valid, violation_rate)
```

### D. Roll Decision Algorithm
```python
def evaluate_roll(current_pnl: float, credit_received: float, max_loss: float,
                  dte_remaining: int, vrp_score: float, new_credit_available: float,
                  earnings_in_new_window: bool) -> dict:
    """
    Determines whether to roll, close, or hold a losing position.
    """
    loss_pct = -current_pnl / credit_received  # positive = loss

    # Never roll if:
    if dte_remaining <= 21:
        return {'action': 'CLOSE', 'reason': 'DTE ≤ 21 — gamma risk too high to roll safely'}
    if earnings_in_new_window:
        return {'action': 'CLOSE', 'reason': 'Earnings would fall in new window — cannot roll without event risk'}
    if vrp_score < 50:
        return {'action': 'CLOSE', 'reason': 'VRP signal has deteriorated — no longer qualifies for a new position'}

    # Roll credit check: must recover at least 25% of loss
    required_credit = abs(current_pnl) * 0.25
    if new_credit_available < required_credit:
        return {'action': 'CLOSE', 'reason': f'Roll credit ${new_credit_available:.2f} insufficient (need ${required_credit:.2f} to recover 25% of loss)'}

    return {
        'action': 'ROLL',
        'reason': f'Roll credit ${new_credit_available:.2f} recovers {new_credit_available/abs(current_pnl)*100:.0f}% of loss. VRP signal still valid at {vrp_score}/100.',
        'note': 'This is the ONLY permitted roll on this position.'
    }
```

### E. VRP Attribution Narrative Template Engine
```python
def vrp_attribution_narrative(signals: dict) -> str:
    """Generate a human-readable paragraph explaining why the VRP exists."""
    parts = []

    # Lead with the strongest signal
    if signals['vrp_pctile'] > 0.80:
        parts.append(
            f"{signals['ticker']}'s VRP of +{signals['vrp']:.1f} vol points is at its "
            f"{signals['vrp_pctile']*100:.0f}th percentile of the past year — "
            f"options sellers have been consistently overcompensated for vol risk here."
        )

    # Persistence
    if signals['vrp_persist_30d'] > 0.70:
        sig = 'statistically significant' if signals['vrp_significance'] < 0.05 else 'directionally persistent but not yet significant'
        parts.append(
            f"The premium has been positive in {signals['vrp_persist_30d']*100:.0f}% "
            f"of the past 30 sessions ({sig} at p={signals['vrp_significance']:.3f})."
        )

    # Driver attribution
    if signals['excess_vrp'] > 2.0:
        parts.append(
            f"Importantly, {signals['excess_vrp']:.1f} vol points of this premium are "
            f"idiosyncratic — above what the underlying's beta of {signals['beta']:.2f} "
            f"to SPY would predict. This is not just index vol."
        )
    if signals['skew_zscore'] > 1.0:
        parts.append(
            f"The 25Δ put skew of {signals['skew_25d']:.1f} pts "
            f"({signals['skew_pctile']*100:.0f}th percentile) indicates active institutional "
            f"put-buying for downside protection — a structural demand that persistently inflates put premiums."
        )
    if signals['gex_billions'] > 0.5:
        parts.append(
            f"Dealer gamma exposure of +${signals['gex_billions']:.1f}B means market makers "
            f"are net long gamma — their delta-hedging dampens daily moves, "
            f"mechanically compressing realized vol below implied vol."
        )
    if signals['jump_pct'] < 0.20:
        parts.append(
            f"Only {signals['jump_pct']*100:.0f}% of implied variance is attributable to "
            f"jump risk — the premium is predominantly diffusive and reliably collectible."
        )

    return " ".join(parts)
```

---

*End of PRD v4.0 — VRP Options Screener*

*Supersedes v1.0, v2.0, and v3.0. Zero trades executed through any API. All execution is manual.*
