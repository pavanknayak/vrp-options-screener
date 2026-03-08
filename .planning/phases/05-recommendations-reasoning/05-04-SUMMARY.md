---
phase: 05-recommendations-reasoning
plan: "04"
subsystem: recommendations
tags: [card-assembly, narrative-paragraphs, order-text, dataclass]
dependency_graph:
  requires:
    - 05-01  # GoNoGoResult from gonogo.py
    - 05-02  # StructureResult from structures.py
    - 05-03  # PnLResult / ScenarioPnL from pnl.py
  provides:
    - RecommendationCard dataclass
    - build_recommendation_card() public function
  affects:
    - Phase 6 UI (consumes RecommendationCard fields for display)
    - recommendations/engine.py (will call build_recommendation_card as final assembly step)
tech_stack:
  added: []
  patterns:
    - Dataclass assembly from multiple upstream result types
    - Try/except never-raise pattern for public entry points
    - f-string narrative interpolation with actual signal values
key_files:
  created:
    - recommendations/card.py
  modified: []
decisions:
  - Collar order_text puts/call debit and credit displayed separately using net_credit_per_share as put_debit proxy (call_credit defaults to 0.0 when chain not queried at card layer — collar net displayed as net option cost)
  - paragraph_3 loss_condition selects among CSP/Spread/Collar templates using structure_result.structure; Collar includes call ceiling reference
metrics:
  duration_seconds: 146
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
  completed_date: "2026-03-08"
---

# Phase 5 Plan 04: Recommendation Card Assembly Summary

**One-liner:** RecommendationCard dataclass + build_recommendation_card() assembling gonogo, structure, and P&L into three interpolated narrative paragraphs and broker-ready order text.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement RecommendationCard and build_recommendation_card() | a6060d4 | recommendations/card.py (created, 427 lines) |

---

## What Was Built

`recommendations/card.py` is the human-facing output layer of the recommendation engine. It exports:

**`RecommendationCard`** — dataclass with 28 fields covering:
- Go/No-Go verdict (passed, gonogo_summary, gonogo_checks)
- Trade parameters (structure, expiration_date, dte, short_strike, long_strike, collar_call_strike, spot, target_delta, fomc_status, fomc_message)
- Trade economics per contract (net_credit, max_loss, breakeven, profit_target, hard_stop, roll_trigger)
- P&L scenarios (scenarios list, probability_weighted_ev, slippage_adj_ev)
- Position sizing (kelly_dollars, kelly_contracts, kelly_pct, kelly_breakdown)
- Narratives (paragraph_1, paragraph_2, paragraph_3)
- Order text (order_text)

**`build_recommendation_card()`** — public entry point that:
1. Extracts `signals = analytics_result.get("signals", {})`
2. Constructs gonogo_summary as "PASS" or "FAIL: {criterion} — {reason}"
3. Calls three paragraph builders and the order text builder
4. Forwards `structure_result.collar_call_strike` directly to card field
5. Never raises — wraps in try/except returning minimal error card on failure

**Paragraph builders:**
- `_build_paragraph_1`: Interpolates ivp, vrp_pctile, vrp, skew_25d, vrp_persist_30d, excess_vrp
- `_build_paragraph_2`: Interpolates timing_action, timing_reason, fomc_status, fomc_message, gex_billions (sign + value + context), vov_z (with size flag), term_slope (contango/backwardation)
- `_build_paragraph_3`: Priority-ordered primary risk (earnings > jump_flag > accrual anomaly > macro), jump_pct with threshold interpretation, regime_label + regime message, structure-specific loss condition with live price/distance data

**Order text builder:**
- CSP: `STO {ticker} {exp_month} {strike}P at ${credit} credit`
- Spread: `BTO {ticker} {exp_month} {long_strike}P / STO {ticker} {exp_month} {short_strike}P at ${credit} net credit`
- Collar: Multi-line with BUY stock, BUY put, STO call, net collar cost

---

## Verification

All assertions from the plan's verify block passed:
- `RecommendationCard` instance returned
- `card.passed is True` for passing gonogo
- `card.collar_call_strike is None` for CSP
- `len(card.scenarios) == 4`
- paragraph_1 contains '68' (IVP) and '72' (VRP pctile)
- paragraph_2 contains 'ENTER NOW' (timing_action)
- CSP order_text contains 'STO', 'AAPL', '145'
- Collar card: `collar_call_strike == 160.0`, order_text contains '160', 'BUY', '145'

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Self-Check

**Files:**
- `recommendations/card.py`: FOUND

**Commits:**
- `a6060d4`: FOUND (feat(05-04): implement RecommendationCard and build_recommendation_card())

## Self-Check: PASSED
