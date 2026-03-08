# Plan 03-01 Summary — Stage 1 Scanner

## Status: COMPLETE

## What was built
- `scanner/__init__.py` — package marker
- `scanner/stage1.py` — Stage 1 parallel pre-filter

## Key behaviors
- ThreadPoolExecutor(20 workers) with as_completed() — NOT executor.map()
- Per-ticker timeout: 8s — timeout → skip_reason="timeout", no crash
- Earnings in DTE window → WARNING log + skip_reason="earnings_in_window:{date}"
- Liquidity gate: bid_ask_pct and atm_oi filters from TickerInfo.options_filter
- IVP × max(VRP, 0) scoring; top 175 returned sorted descending

## Exports
- `run_stage1(universe, n_workers, top_n, min_dte, max_dte, per_ticker_timeout) -> list[Stage1Result]`
- `Stage1Result` dataclass (9 fields)
- `_score_ticker` (per-ticker worker)
