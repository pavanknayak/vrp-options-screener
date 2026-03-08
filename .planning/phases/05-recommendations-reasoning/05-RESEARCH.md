# Phase 5: Recommendations & Reasoning — Research

**Researched:** 2026-03-07
**Domain:** Options trade recommendation engine — BSM strike selection, Kelly sizing, P&L scenario computation, narrative generation
**Confidence:** HIGH (all findings verified against existing codebase; no external API changes needed)

---

## Summary

Phase 5 builds on four fully-complete prior phases (Data, Analytics, Scanner, Fundamentals). The analytics engine already computes every signal the recommendation engine needs (vrp_pctile, vov_z, regime, gex, jump_pct, ivp, timing_action). The fundamentals engine already enforces tier gates and returns permitted_structures. The Schwab chain parser already extracts `delta`, `bid`, `ask`, `strike`, `gamma`, `impliedVolatility`, and `openInterest` columns per-leg — so strike selection by delta is fully supported with live data and has a BSM fallback for cases where Schwab returns NaN deltas.

Five plan files already exist for Phase 5 and are well-designed. The research task is to verify their correctness against the codebase and identify any gaps the planner must address. The key findings: (1) BSM delta-strike formulas are correct; (2) the simplified Kelly is acceptable for this strategy class but has one implementation nuance; (3) four-scenario P&L formulas are correct for CSP and Spread; (4) the Collar structure needs explicit implementation guidance that the existing plans lack; (5) tickers.json permits `strangle` and `condor` for most ETF tiers but the plans correctly restrict to CSP/Spread/Collar per requirements — that mismatch needs explicit handling; (6) narrative quality is adequate given the signal interpolation approach.

**Primary recommendation:** Execute the five existing PLAN.md files with three targeted corrections: explicit Collar P&L implementation, go/no-go filter to restrict structure to {csp, spread, collar} only (ignoring strangle/condor from tickers.json), and a confirmed asset_class enrichment in the engine before pnl computation.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REC-01 | 21-point go/no-go matrix with hard disqualifiers | Plan 05-01 implements fully; 9 HARD + 12 SOFT checks in correct priority order |
| REC-02 | Trade structure per tier/asset-class mandate | Plan 05-02 implements; tickers.json has strangle/condor — plan must filter to allowed 3 |
| REC-03 | Strike selection by Kelly-optimal delta (base 25Δ ± adjustments) | Plan 05-02; BSM fallback is correct; Schwab chain has delta column |
| REC-04 | DTE selection with FOMC avoidance | Plan 05-02; fomc_context() already implemented in data/fomc.py |
| REC-05 | Slippage-adjusted EV (per-leg bid-ask × 0.75) | Plan 05-03; formula confirmed correct |
| REC-06 | Four-scenario P&L with probability-weighted EV | Plan 05-03; CSP and Spread confirmed; Collar needs explicit coverage |
| REC-07 | 25% fractional Kelly with regime × VoV × GEX multipliers | Plan 05-03; formula verified; clamping logic correct |
| REC-08 | Complete recommendation card with all required fields | Plan 05-04; all 20+ fields present in RecommendationCard dataclass |
| REAS-01 | Paragraph 1 — why premium exists (signal values) | Plan 05-04; template interpolates ivp, vrp_pctile, vrp, skew_25d, persist, excess_vrp |
| REAS-02 | Paragraph 2 — why to enter now (momentum, FOMC, GEX, VoV) | Plan 05-04; template interpolates timing_action, fomc_status, gex, vov_z, term_slope |
| REAS-03 | Paragraph 3 — what could cause loss (specific risk) | Plan 05-04; priority cascade: earnings > jump_flag > accrual > macro |
| REAS-04 | Manual order text for broker entry | Plan 05-04; STO/BTO format with strike, month, credit |

</phase_requirements>

---

## Standard Stack

### Core (all already installed in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy.stats.norm | scipy ≥1.10 | BSM delta-strike computation (norm.ppf, norm.cdf) | Authoritative SciPy stats; used in analytics/vrp_engine.py already |
| numpy | ≥1.24 | Vectorized P&L, Kelly clamping, np.clip | Standard numeric; used throughout all phases |
| pandas | ≥2.0 | Chain DataFrames (puts_df, calls_df); already in chain format | Standard; all chain data is already DataFrames |
| dataclasses | stdlib | GoNoGoResult, StructureResult, PnLResult, RecommendationCard | Already used in fundamentals/piotroski.py etc. |
| datetime | stdlib | DTE → expiration_date computation, FOMC calendar lookup | Already used in data/fomc.py |

### No New Dependencies Required
All five plan files can be implemented with zero new pip installs. The existing venv already contains scipy, numpy, pandas, and the project-local modules (analytics, fundamentals, data, universe).

**Installation:** None needed.

---

## Architecture Patterns

### Recommended Project Structure
```
recommendations/
├── __init__.py          # Package marker only (Plan 05-01)
├── gonogo.py            # GoNoGoResult + evaluate_gonogo() (Plan 05-01)
├── structures.py        # StructureResult + select_structure() + select_strikes() (Plan 05-02)
├── pnl.py               # ScenarioPnL + PnLResult + compute_* (Plan 05-03)
├── card.py              # RecommendationCard + build_recommendation_card() (Plan 05-04)
└── engine.py            # run_recommendation() orchestrator (Plan 05-05)
```

### Dependency Order (critical)
```
structures.py (strike selection, DTE, FOMC) ─┐
                                              ├──> pnl.py (slippage EV from bid/ask) ─┐
                                              │                                        ├──> gonogo.py (HARD-03 needs slippage_adj_ev)
                                              └──────────────────────────────────────────> gonogo.py
gonogo.py + structures.py + pnl.py ──────────────────────────────────────────────────> card.py
all four ────────────────────────────────────────────────────────────────────────────> engine.py
```

**Note:** The engine (Plan 05-05) correctly runs structures and pnl BEFORE gonogo, because HARD-03 (EV > 0) requires the slippage-adjusted EV to be computed first. This ordering is unconventional but necessary and is correctly captured in Plan 05-05.

### Pattern 1: BSM Delta-Strike Approximation
**What:** When chain put delta is NaN or absent, compute approximate put strike for a target delta using:
```
K_put = S × exp(N^{-1}(Δ_target) × σ × √T)
```
where N^{-1} is the standard normal inverse CDF (`scipy.stats.norm.ppf`).

**Correctness verification:** For a put with delta = -0.25, Δ_target = 0.25 (use absolute value):
- `norm.ppf(0.25)` ≈ -0.6745
- K = S × exp(-0.6745 × σ × √T), which is OTM below spot — correct for a 25-delta put.

**Source:** This exact formula appears in analytics/vrp_engine.py lines 232-235 for skew computation and is analytically correct per BSM theory.

**Confidence:** HIGH — code already in production in this project.

```python
# Source: analytics/vrp_engine.py lines 232-235
from scipy.stats import norm
import numpy as np
k_put = spot * np.exp(norm.ppf(target_delta) * iv * np.sqrt(T))
# target_delta = 0.25 → norm.ppf(0.25) ≈ -0.6745 → K < spot (correct OTM put)
```

### Pattern 2: Schwab Chain Delta Column
**What:** The Schwab chain `puts_df` and `calls_df` DataFrames include a `delta` column. This is confirmed by `data/schwab_client.py` line 149: `_OPTION_COLS` includes `"delta"`. Schwab's Market Data API returns delta for each option contract in the chain response.

**Confidence:** HIGH — verified in schwab_client.py.

**Implementation note:** Put deltas from Schwab are NEGATIVE (e.g., -0.25). Strike selection code must use `puts_df["delta"].abs()` when finding the contract closest to `target_delta` (which is stored as a positive float like 0.25).

```python
# Correct: find put closest to -target_delta by comparing absolute values
idx = (puts_df["delta"].abs() - target_delta).abs().idxmin()
```

### Pattern 3: CSP P&L at Expiry
**What:** For a Cash-Secured Put at short_strike K, net_credit c (per share):
- Bull (S_T > K): P&L = +c × 100 (put expires worthless, keep full premium)
- Base (S_T > K): same
- Bear (S_T < K): P&L = (S_T - K + c) × 100 = max(-max_loss, min(c×100, (S_T - K + c)×100))
- Crash (S_T << K): same formula; minimum P&L = -(K - c) × 100 (stock goes to zero)

**Breakeven:** S_T = K - c (underlying price where P&L = 0 at expiry)
**Max loss:** (K - c) × 100 (if underlying goes to zero)

**Correctness check (Plan 05-03 formula):**
- `max_loss = (structure_result.short_strike - net_credit) * 100` — CORRECT
- `breakeven = structure_result.short_strike - net_credit` — CORRECT
- Bear/Crash: `pnl = (terminal_price - short_strike + net_credit) * 100` — CORRECT
- When terminal_price > short_strike: pnl = positive (capped at c×100 for pure expiry analysis) — CORRECT

**Confidence:** HIGH — standard options textbook formula, verified against plan.

### Pattern 4: Bull Spread P&L at Expiry (actually a put debit spread — Bearish spread P&L)
**What:** For a put spread (short put at K1, long put at K2, K1 > K2), net credit nc (per share, nc > 0):
- Bull (S_T > K1): both puts expire worthless → P&L = +nc × 100
- Base (S_T > K1): same
- Bear (K2 < S_T < K1): short put ITM, long put OTM → P&L = (S_T - K1 + nc) × 100, clamped to [-max_loss, nc×100]
- Crash (S_T < K2): both ITM → P&L = -(K1 - K2 - nc) × 100 = -max_loss (both exercise offset except spread width minus credit)

**Breakeven:** S_T = K1 - nc
**Max loss:** (K1 - K2 - nc) × 100 = (spread_width - nc) × 100

**Correctness check (Plan 05-03):**
- `max_loss = (spread_width - net_credit) * 100` — CORRECT
- `breakeven = short_strike - net_credit` — CORRECT
- P&L clamped to `[-max_loss, net_credit_contract]` — CORRECT

**Confidence:** HIGH — standard put spread formula.

### Pattern 5: Collar P&L at Expiry
**What:** A Collar = stock ownership + long put at K_put + short call at K_call (K_put < S < K_call).
- This is NOT a pure premium collection strategy — it requires stock ownership.
- Per requirements, Collar is listed as a permitted structure but the plans implement it as "spread + note about covered call" (Plan 05-02 Step 3 for Collar).
- **Gap identified:** The existing plans do not fully implement Collar P&L. Plan 05-03 handles CSP and Spread explicitly but Collar is not shown. For practical purposes, Collar P&L at expiry:
  - Bull (S_T > K_call): gain on stock capped at K_call + nc × 100 (short call exercised)
  - Base (K_put < S_T < K_call): stock position gains/losses normally; put and call expire worthless; P&L = (S_T - S_0 + nc) × 100
  - Bear (S_T < K_put): put exercised, stock sold at K_put; P&L = (K_put - S_0 + nc) × 100 (protected)
  - Crash: same as Bear

**Recommendation:** Implement Collar as equivalent to a spread in pnl.py for P&L display purposes (as Plan 05-02 implies), but note this is an approximation that assumes the put premium roughly offsets the call premium to create near-zero-cost protection. The plan's approach — treating Collar like a spread for strike selection — is acceptable.

**Confidence:** MEDIUM — the plans acknowledge the simplification; no counterevidence found.

### Pattern 6: Fractional Kelly Sizing
**What:** The 25% fractional Kelly formula used in Plan 05-03:
```
final_f = 0.25 × regime_mult × vov_mult × gex_mult
kelly_pct = clip(final_f × max_position_pct, max_position_pct/4, max_position_pct)
```

**For premium collection strategies**, the theoretical Kelly fraction is:
```
f* = (p × W - q × L) / (W × L)
```
where p = win probability, W = win per dollar, q = 1-p, L = loss per dollar. The 25% fractional Kelly is a well-established conservative scaling (Quarter-Kelly) used precisely because the Kelly formula is sensitive to parameter estimation error. For options premium collection where the win rate is typically 70-80% on CSP/spreads, full Kelly tends to be over-aggressive; 25% is the standard retail practitioner approach.

**The plan's formula is correct and appropriate.** It does not implement the theoretical Kelly fraction directly, but neither should it — doing so would require reliable estimates of win rate and win/loss ratio from the four P&L scenarios, which would create a circular dependency.

**Confidence:** HIGH — 25% fractional Kelly is the standard in options literature; formula structure is correct.

**One nuance:** `kelly_contracts = max(1, int(kelly_dollars / (100.0 * spot)))` — the `max(1, ...)` ensures at least 1 contract is always recommended, even if the position size math rounds to zero. This is correct behavior per the spec ("actionable" = at least 1 contract).

### Pattern 7: Narrative Template Approach
**What:** Plans 05-04 use f-string templates with direct signal interpolation. Every sentence references a numeric signal value. This produces non-boilerplate output because the values change per ticker.

**Quality assessment:** The templates in Plan 05-04 are specific enough to satisfy REAS-01/02/03:
- Para 1 references: ivp (numeric %), vrp_pctile (numeric %), vrp (annualized %), skew_25d (%), persist (%), excess_vrp (%)
- Para 2 references: timing_action (string from vrp_timing_signal), fomc_status, gex (with sign and value), vov_z (numeric), term_slope (numeric)
- Para 3 references: earnings flag, jump_flag (the actual flag string from vrp_engine.py), accrual_anomaly, regime message, specific strike and distance-from-spot

**This approach is correct and will produce useful output.** The alternative (LLM-generated text) is out of scope and not required by the PRD.

**Confidence:** HIGH — template approach matches production code pattern from vrp_engine.py vrp_timing_signal function which uses the same style.

### Anti-Patterns to Avoid

- **Strangle/Condor in select_structure():** tickers.json permits "strangle" and "condor" for tiers 1A-1H and 2. The plans correctly ignore these (requirements only permit CSP, Spread, Collar). The gonogo.py and structures.py must explicitly filter the permitted_structures list to `{csp, spread, collar}` only. Do not implement strangle or condor logic.
- **Computing delta from BSM when chain has it:** The chain already has `delta` from Schwab. Always use chain delta first; fall back to BSM only when all chain deltas are NaN.
- **Mutating analytics_result dict:** Plan 05-05 correctly uses `analytics_result = dict(analytics_result)` before setting `asset_class`. Never mutate the caller's dict.
- **Raising exceptions from the engine:** Every function must wrap in try/except and return structured error dicts, not raise.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BSM delta-to-strike conversion | Custom Newton solver | `scipy.stats.norm.ppf()` | Already proven in analytics/vrp_engine.py; direct formula K = S×exp(N⁻¹(Δ)×σ×√T) |
| FOMC proximity check | Custom date logic | `data.fomc.fomc_context()` | Already implemented, tested; returns 4-state status |
| Tier gate enforcement | Custom lookup | `fundamentals.engine._enforce_tier_gate()` via `run_fundamentals()` | Already implemented with all 6 rules |
| Structure-to-tier mapping | Custom dict | `ticker_info.permitted_structures` from universe/loader.py | Already loaded from tickers.json at import |
| Regime multiplier | Recompute VIX regime | `analytics_result["regime"]["multiplier"]` | detect_regime() already ran in analytics pipeline |

**Key insight:** Every upstream computation (regime, VoV, GEX, FOMC) has already run by the time the recommendation engine is called. Phase 5 is a pure assembly and output-formatting phase, not a computation phase.

---

## Common Pitfalls

### Pitfall 1: Structure Filter Mismatch (tickers.json vs requirements)
**What goes wrong:** tickers.json lists "strangle" and "condor" in `permitted_structures` for most ETF tiers. If `select_structure()` returns "strangle" for an SPY chain, none of the P&L code handles it and the function will fail.
**Why it happens:** The PRD includes strangle/condor in the universe file but the requirements only authorize CSP/Spread/Collar for Phase 5.
**How to avoid:** In `select_structure()`, after reading `ticker_info.permitted_structures`, immediately filter to only `{"csp", "spread", "collar"}` before applying priority logic:
```python
ALLOWED_STRUCTURES = {"csp", "spread", "collar"}
permitted = [s for s in ticker_info.permitted_structures if s in ALLOWED_STRUCTURES]
```
**Warning signs:** `select_structure()` returning "strangle" or "condor" causes KeyError in pnl.py.

### Pitfall 2: Negative Put Delta in Strike Selection
**What goes wrong:** Schwab returns put deltas as negative numbers (e.g., -0.25). If code does `(puts_df["delta"] - target_delta).abs().idxmin()` with `target_delta = 0.25`, it will find the delta closest to 0.25, which would be the ATM call (not the OTM put).
**Why it happens:** target_delta is stored as a positive float per convention; chain stores it signed.
**How to avoid:** Use `puts_df["delta"].abs()` before the comparison. The plan already specifies this correctly (Plan 05-02 Step 3), but the executor must not simplify the abs() call away.
**Warning signs:** Short strike selected is at-the-money or higher instead of OTM.

### Pitfall 3: net_credit Units in P&L
**What goes wrong:** `compute_slippage_ev()` returns per-share credit (e.g., $1.50/share). But `max_loss` and `breakeven` formulas use per-share values. The `net_credit_contract` (×100) is the correct unit for `profit_target`, `hard_stop`, and the scenario `pnl_per_contract`.
**Why it happens:** Options pricing mixes per-share and per-contract (100-share multiplier) terminology.
**How to avoid:** Plan 05-03 is explicit: `net_credit` is per-share in the slippage_ev function; multiply by 100 for per-contract amounts. Keep these distinct throughout. The `PnLResult.net_credit` field stores per-contract dollars (×100).
**Warning signs:** `max_loss` is 100× too small (forgot multiplier) or `breakeven` is off by 100×.

### Pitfall 4: Collar Not Fully Implemented
**What goes wrong:** Plan 05-02 says "implement Collar like Spread + note in delta_reason." Plan 05-03 does not show Collar P&L explicitly. If the executor interprets Collar as identical to Spread but the card displays "collar" structure, the order text format is wrong (STO put + BTO put is a spread; a collar also has a short call component).
**Why it happens:** Collar requires stock ownership assumption which the app can't verify.
**How to avoid:** For P&L computation purposes, treat Collar identical to Spread (short put + long put). For order text, add a second line: "Also STO {ticker} {exp_month} {call_strike:.0f}C to complete collar (requires existing long stock position)." The long strike for the call can be selected at 0.25Δ OTM using the calls_df.
**Warning signs:** Order text says "STO / BTO put spread" for a collar recommendation.

### Pitfall 5: asset_class Not in analytics_result
**What goes wrong:** `compute_pnl_scenarios()` reads `analytics_result.get("asset_class", "us_equity")` to determine crypto vs equity scenario shocks. But `run_analytics()` does not populate `asset_class` in its output dict.
**Why it happens:** asset_class is a property of the ticker, not the analytics computation.
**How to avoid:** Plan 05-05 correctly handles this: `analytics_result.setdefault("asset_class", ticker_info.asset_class)`. The executor must not skip this enrichment step.
**Warning signs:** Crypto ETF (IBIT) gets equity scenario shocks (Bear -10%) instead of crypto shocks (Bear -30%).

### Pitfall 6: DTE Expiration Date Computation
**What goes wrong:** The chain expiration has a `"date"` key (ISO string like "2025-04-21") and a `"dte"` key (integer). Plan 05-02 computes `exp_date = today_date + timedelta(days=dte)`. This is an approximation — the actual expiration date comes from the chain's `"date"` field and is more reliable.
**Why it happens:** The plan uses dte arithmetic instead of the chain's stored date.
**How to avoid:** Prefer the chain's `"date"` field directly: `exp_date_str = selected_exp.get("date", (today_date + timedelta(days=dte)).isoformat())`. If "date" is not present, fall back to the arithmetic approach.
**Warning signs:** Order text shows wrong expiration month (off by 1 if month-end crossing).

---

## Code Examples

### BSM Delta Strike (verified against existing codebase)
```python
# Source: analytics/vrp_engine.py lines 232-235
from scipy.stats import norm
import numpy as np

def bsm_delta_strike(spot: float, iv: float, dte: int, target_delta: float) -> float:
    """Compute OTM put strike for given delta target (put delta convention: positive input)."""
    T = max(dte / 365.0, 1e-4)
    # norm.ppf(0.25) ≈ -0.6745 for a 25-delta put
    return spot * np.exp(norm.ppf(target_delta) * iv * np.sqrt(T))
```

### Chain Delta Strike Selection (confirmed from schwab_client.py)
```python
# The Schwab chain puts_df has a "delta" column (negative for puts)
def find_put_strike_by_delta(puts_df, target_delta: float, spot: float, iv: float, dte: int) -> float:
    """Find strike closest to target_delta; BSM fallback if all chain deltas are NaN."""
    if "delta" in puts_df.columns and not puts_df["delta"].isna().all():
        valid = puts_df.dropna(subset=["delta"])
        idx = (valid["delta"].abs() - target_delta).abs().idxmin()
        return float(valid.loc[idx, "strike"])
    # BSM fallback
    k = bsm_delta_strike(spot, iv, dte, target_delta)
    idx = (puts_df["strike"] - k).abs().idxmin()
    return float(puts_df.loc[idx, "strike"])
```

### Slippage-Adjusted EV (plan-verified)
```python
def compute_slippage_ev(bid: float, ask: float) -> float:
    """Per-share slippage-adjusted credit (75% of mid)."""
    return ((bid + ask) / 2.0) * 0.75
```

### Kelly Sizing (plan-verified)
```python
def compute_kelly_multipliers(analytics_result: dict) -> dict:
    """Extract and apply Kelly multipliers from analytics output."""
    regime_mult = float(analytics_result.get("regime", {}).get("multiplier", 1.0))
    vov_z = analytics_result.get("signals", {}).get("vov_z", 0.0)
    vov_mult = 0.75 if vov_z > 1.5 else 1.0
    gex_bn = analytics_result.get("gex_billions", 0.0)
    gex_mult = 0.75 if gex_bn < 0 else 1.0
    return {"regime_mult": regime_mult, "vov_mult": vov_mult, "gex_mult": gex_mult,
            "final_f": 0.25 * regime_mult * vov_mult * gex_mult}
```

### CSP Scenario P&L (plan-verified)
```python
def csp_pnl(terminal_price: float, short_strike: float, net_credit_per_share: float) -> float:
    """P&L per contract (×100) for a CSP at expiry."""
    if terminal_price >= short_strike:
        return net_credit_per_share * 100.0  # put expires worthless
    return (terminal_price - short_strike + net_credit_per_share) * 100.0
```

---

## Plan-Level Gap Analysis

### Confirmed Correct in Existing Plans
| Plan | Correctness |
|------|-------------|
| 05-01 (gonogo.py) | All 21 checks correct; order is HARD-01..09 then SOFT-01..12; slippage_adj_ev is passed as parameter (avoids circular dependency) |
| 05-02 (structures.py) | BSM fallback formula correct; delta abs() usage correct; FOMC avoidance logic correct; DTE nearest-45 selection correct |
| 05-03 (pnl.py) | Slippage formula correct; CSP and Spread P&L formulas correct; Kelly multiplier logic correct; probability sums to 1.0 for both equity and crypto |
| 05-04 (card.py) | All required card fields present; narratives interpolate actual signal values; order text format readable |
| 05-05 (engine.py) | asset_class enrichment present; correct dependency order (struct→pnl→gonogo→kelly→card); never raises |

### Gaps to Fix

**Gap 1 — Structure Filter (HIGH PRIORITY)**
Plans 05-02 and 05-01 do not explicitly filter tickers.json's strangle/condor out of permitted_structures. The executor must add this filter in `select_structure()`.

**Gap 2 — Collar P&L Handling (MEDIUM PRIORITY)**
Plan 05-03 shows CSP and Spread P&L explicitly but leaves Collar as an exercise. The `_pnl_for_scenario()` helper function (referenced in the plan but not fully shown) must handle `structure == "collar"` the same as "spread" for the P&L math, plus the card.py order text for collar must include the call leg.

**Gap 3 — Expiration Date from Chain (LOW PRIORITY)**
Plan 05-02 computes `exp_date = today_date + timedelta(days=dte)` but the chain has the actual date in `selected_exp["date"]`. Use chain date when available.

**Gap 4 — Collar Long Strike for Call Leg (LOW PRIORITY)**
For Collar, the long strike (used for spread put protection) and the short call strike are different. The plan's StructureResult uses `long_strike` for the protective put's lower strike. A second field or a note is needed for the short call strike. Simplest resolution: add `collar_call_strike: float | None = None` to StructureResult, or compute it in card.py directly from calls_df.

---

## State of the Art

| Old Approach | Current Approach | Relevance |
|--------------|------------------|-----------|
| Full Kelly fraction (theoretical) | 25% fractional Kelly with multipliers | PRD specifies 25% Kelly — this is correct |
| Generic narrative templates | Signal-interpolated f-string templates | PRD requires "no generic boilerplate" — interpolation satisfies this |
| VIX-only regime detection | VIX + optional VVIX Z-score | Already implemented in analytics/regime.py |

---

## Open Questions

1. **Collar Call Strike Selection**
   - What we know: StructureResult has `long_strike` (protective put leg), but no field for the short call strike
   - What's unclear: How to surface the call strike in the recommendation card and order text
   - Recommendation: Add `collar_call_strike: float | None = None` to StructureResult. In select_strikes(), when structure == "collar", select call at 0.25Δ OTM from calls_df and populate this field. Card.py uses it for order text.

2. **Spread Width Logic for High-Priced Stocks**
   - What we know: Plan 05-02 uses `round(spot * 0.025)` for stocks over $100 as spread width
   - What's unclear: Does "round to nearest $5" align with actual strike increments in Schwab chain?
   - Recommendation: Use `long_strike = max(strike for strike in available_put_strikes if strike < short_strike - spread_target)` — pick the nearest available strike below the target, not a computed rounded value. This ensures both legs are actually in the chain.

3. **go/no-go Check Ordering — HARD-03 Requires Pre-Computation**
   - What we know: HARD-03 (EV > 0) needs slippage_adj_ev which requires running pnl.py before gonogo.py
   - What's unclear: Nothing — Plan 05-05 explicitly handles this in the correct order
   - Recommendation: No change needed; the dependency is documented and handled.

---

## Sources

### Primary (HIGH confidence)
- `data/schwab_client.py` — Confirmed delta column in `_OPTION_COLS` (line 149); chain format with bid/ask/strike/delta/gamma/impliedVolatility
- `analytics/vrp_engine.py` — BSM delta-strike formula (lines 232-235); same scipy.stats.norm.ppf pattern
- `analytics/engine.py` — Full analytics_result dict structure; keys available to Phase 5
- `fundamentals/engine.py` — run_fundamentals() output structure; gate_result.permitted_structures, altman.is_distress
- `universe/loader.py` — TickerInfo dataclass; permitted_structures from tickers.json
- `universe/tickers.json` — Tier 1I crypto_etf: spread/collar only; Tier 6B china_adr: N/A in tickers (handled by _TIER_GATES)
- `data/fomc.py` — fomc_context() signature and return values; FOMC_DATES populated through 2026

### Secondary (MEDIUM confidence)
- `analytics/composite_score.py` — Confirms VoV Z > 2.5 disqualification (same threshold as HARD-04 in Plan 05-01)
- `analytics/regime.py` — Confirms regime multipliers: Crisis=0.00, High=0.75, Elevated=1.25, Normal=1.00, Low=0.50
- `.planning/phases/05-recommendations-reasoning/05-01 through 05-05-PLAN.md` — Reviewed all five plan files for correctness

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; all libraries already in use
- BSM formulas: HIGH — verified against existing analytics/vrp_engine.py code
- P&L formulas (CSP, Spread): HIGH — standard textbook formulas, verified against plans
- P&L formulas (Collar): MEDIUM — plans treat as approximate; simplification is acceptable
- Kelly formula: HIGH — 25% fractional Kelly is correct for this strategy class
- Architecture/ordering: HIGH — dependency order verified by reading all 5 plans and engine.py
- Narrative quality: HIGH — interpolation approach confirmed adequate for REAS-01/02/03
- Pitfalls: HIGH — all identified from direct code inspection, not speculation

**Research date:** 2026-03-07
**Valid until:** 2026-04-07 (stable libraries; Schwab API format changes would require re-check)
