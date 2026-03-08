---
phase: 05-recommendations-reasoning
plan: "03"
subsystem: recommendations
tags: [pnl, kelly-sizing, scenario-analysis, slippage, ev]
dependency_graph:
  requires:
    - recommendations/structures.py (StructureResult)
    - analytics/regime.py (regime multiplier)
    - universe/loader.py (TickerInfo.max_position_pct)
  provides:
    - recommendations/pnl.py (ScenarioPnL, PnLResult, compute_slippage_ev, compute_pnl_scenarios, compute_kelly_size)
  affects:
    - recommendations/engine.py (will call compute_pnl_scenarios + compute_kelly_size)
    - recommendations/gonogo.py (slippage_adj_ev input computed here)
tech_stack:
  added: []
  patterns:
    - Slippage adjustment: mid_price * 0.75 per leg for realistic fill modeling
    - Four-scenario P&L: Bull/Base/Bear/Crash with asset-class-specific probabilities and price moves
    - Fractional Kelly: 0.25 base * regime_mult * vov_mult * gex_mult, clamped to [max_pos/4, max_pos]
    - Collar approximated as spread equivalent for net payoff computation
key_files:
  created:
    - recommendations/pnl.py
  modified: []
decisions:
  - Collar P&L uses spread-equivalent formula (call_ev - put_ev credit, same clamped payoff as spread) to avoid requiring full stock position P&L tracking in Phase 5 scope
  - net_credit floored at $0.01 for spread/collar to prevent degenerate max_loss = spread_width * 100 scenarios
  - kelly_contracts floored at 1 contract (never returns 0) to ensure usable recommendation output
metrics:
  duration_minutes: 15
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
  completed_date: "2026-03-08"
---

# Phase 5 Plan 03: P&L Scenarios, Slippage EV, and Kelly Sizing Summary

**One-liner:** Slippage-adjusted EV (mid*0.75), four-scenario P&L (Bull/Base/Bear/Crash with asset-class probabilities), and fractional Kelly sizing (0.25 base × regime × VoV × GEX multipliers).

## What Was Built

`recommendations/pnl.py` — the quantitative core of the recommendation card. Every dollar-denominated figure the user acts on flows through this module.

### Exports

| Symbol | Type | Purpose |
|--------|------|---------|
| `ScenarioPnL` | dataclass | Per-scenario P&L (name, move, terminal price, pnl, probability, weighted_pnl) |
| `PnLResult` | dataclass | Full trade P&L result (net_credit, max_loss, breakeven, scenarios, EV, Kelly fields) |
| `compute_slippage_ev(bid, ask)` | function | Returns `(bid+ask)/2 * 0.75` per-leg slippage-adjusted credit |
| `compute_pnl_scenarios(...)` | function | 4-scenario P&L + trade management levels (profit_target, hard_stop, roll_trigger) |
| `compute_kelly_size(...)` | function | Fractional Kelly in dollars, contracts, and pct with breakdown dict |

### Key Formulas

**Slippage EV:** `mid * 0.75` — 75% of the bid-ask midpoint models realistic fill quality.

**Scenario parameters:**
- US equity: Bull +15% (p=0.25), Base 0% (p=0.45), Bear -10% (p=0.20), Crash -25% (p=0.10)
- Crypto ETF: Bull +50% (p=0.25), Base 0% (p=0.40), Bear -30% (p=0.20), Crash -50% (p=0.15)

**CSP payoff:** Full credit if terminal >= short_strike; otherwise `(terminal - K + credit) * 100`

**Spread/Collar payoff:** Clamped `max(-max_loss, min(credit_contract, (terminal - K + credit) * 100))`

**Kelly formula:** `final_f = 0.25 * regime_mult * vov_mult * gex_mult`, then `kelly_pct = clip(final_f * max_pos, max_pos/4, max_pos)`

**Trade management levels:**
- Profit target: `net_credit_contract * 0.50` (close at 50% of max profit)
- Hard stop: `net_credit_contract * 2.0` (close if loss = 2x credit)
- Roll trigger: `breakeven * 0.97` (underlying drops 3% below breakeven)

## Verification

All assertions from the plan's verification block passed:
- `compute_slippage_ev(1.80, 2.20)` returns `1.50` (mid=2.00 * 0.75)
- CSP produces 4 ScenarioPnL objects with names `['Bull', 'Base', 'Bear', 'Crash']`
- Scenario probabilities sum to exactly 1.0 for US equity (0.25+0.45+0.20+0.10)
- CSP Bull and Base scenarios return full net_credit_contract (put expires worthless)
- Collar structure runs without error using spread-equivalent approximation
- Kelly: positive dollars, >= 1 contract, pct in (0, 0.05], multipliers correct for vov_z=0.5 and gex=+0.5

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

- [x] `recommendations/pnl.py` exists and exports all required symbols
- [x] Commit `2a8d1ab` verified in git log
- [x] All plan assertions pass with "ALL ASSERTIONS PASSED"
- [x] Collar comment "# Collar P&L approximated as spread equivalent (near zero-cost collar assumption)" present in code

## Self-Check: PASSED
