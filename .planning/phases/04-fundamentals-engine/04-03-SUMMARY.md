# Plan 04-03 Summary — Fundamentals Engine Orchestrator

**Status:** COMPLETE
**Date:** 2026-03-07

## Files Created
- `fundamentals/engine.py` — run_fundamentals() orchestrator and _enforce_tier_gate()

## What Was Built

### _enforce_tier_gate()
Per-tier fundamental gate with 6 evaluation rules in strict priority order:
1. CSP structural block (6B China ADRs) — always blocks CSP, spread/collar remain permitted
2. No fundamental check required (ETF tiers 1A-1I) — immediate pass
3. Altman distress hard block — blocks all structures when altman_zone == "distress"
4. Altman minimum score — numeric floor (Tier 3: 1.23, Tier 4: 2.50, Tier 5: 2.99)
5. Piotroski minimum — F-Score floor (Tier 3: 5, Tier 4: 6, Tier 5: 7, 6A: 6)
6. Combined score minimum — floor (Tier 2: 40, Tier 3: 55, Tier 4: 65, Tier 5: 75, 6A: 65, Tier 7: 40)

### run_fundamentals()
Single public entry point:
- ETF fast path: returns immediately with requires_fundamental_score=False, gate_result.passed=True
- Equity path: fetches OHLCV (last close price), EDGAR extended financials, runs all 4 models
- Combined score formula: `0.45 * (f_score/9*100) + 0.55 * mos_score`
- Never raises — returns `{"ticker": ticker, "error": str(exc)}` on any exception

## Verification Results
All 9 tests passed:
- ETF fast path (SPY/1A)
- 6B CSP block with spread/collar permitted
- Tier 2 gray zone pass
- Tier 2 Altman distress hard block
- Tier 3 combined score fail (45 < 55)
- Tier 4 Piotroski fail (5 < 6)
- Tier 5 Altman minimum fail (2.50 < 2.99)
- Combined score formula verification
- run_fundamentals never raises on unknown ticker
