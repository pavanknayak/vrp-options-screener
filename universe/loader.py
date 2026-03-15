"""
universe/loader.py
------------------
Ticker universe loader for the VRP Options Screener.

Loads universe/tickers.json at module import time and materializes every
ticker into a typed TickerInfo dataclass.  All downstream components should
call get_ticker_info(symbol) to resolve tier rules for a given ticker.

No network calls are made at any point — this module is pure file I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class TickerInfo:
    """Resolved tier metadata for a single ticker symbol."""

    symbol: str
    tier: str                           # e.g. "1A", "1I", "6B"
    tier_description: str
    asset_class: str                    # e.g. "crypto_etf", "china_adr", "us_equity"
    permitted_structures: list[str]     # e.g. ["spread", "collar"]
    max_position_pct: float             # 0.05 default, 0.02 for crypto
    requires_fundamental_score: bool    # False for ETFs, True for equity tiers 2-7
    options_filter: dict                # atm_bid_ask_max_pct, min_oi, etc.
    no_entry_days: list[str] = field(default_factory=list)  # ["thursday_after_2pm","friday"] for 1I
    notes: Optional[str] = None         # per-ticker override notes
    sector: str = "Unknown"             # e.g. "Technology", "Healthcare", "Financials", etc.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_sector(tier: str, asset_class: str) -> str:
    """Infer sector from tier/asset_class when not specified in tickers.json."""
    sector_map = {
        "broad_market_etf": "Diversified",
        "sector_etf": "Diversified",
        "crypto_etf": "Cryptocurrency",
        "bond_etf": "Fixed Income",
        "china_adr": "International",
        "india_adr": "International",
        "row_adr": "International",
        "reit": "Real Estate",
        "bank": "Financials",
        "insurance": "Financials",
        "financial": "Financials",
    }
    return sector_map.get(asset_class, "Equity")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_TICKERS_JSON = Path(__file__).parent / "tickers.json"


def load_universe() -> dict[str, TickerInfo]:
    """
    Load universe/tickers.json and return a flat dict mapping each ticker
    symbol (uppercase) to its resolved TickerInfo.

    For tickers that carry a per-ticker override dict in the JSON (e.g. INDL,
    YINN, ARKK), the override_structures field replaces the tier-level
    permitted_structures.  All other fields inherit from the tier.

    Returns
    -------
    dict[str, TickerInfo]
        Keys are uppercase ticker symbols.
    """
    with _TICKERS_JSON.open(encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    universe: dict[str, TickerInfo] = {}

    for tier_id, tier_data in raw.items():
        tier_description: str = tier_data.get("description", "")
        asset_class: str = tier_data.get("asset_class", "")
        tier_permitted: list[str] = tier_data.get("permitted_structures", [])
        max_pos: float = float(tier_data.get("max_position_pct", 0.05))
        req_fundamental: bool = bool(tier_data.get("requires_fundamental_score", False))
        options_filter: dict = tier_data.get("options_filter", {})
        no_entry_days: list[str] = tier_data.get("no_entry_days", [])

        for entry in tier_data.get("tickers", []):
            if isinstance(entry, str):
                symbol = entry.upper()
                effective_structures = list(tier_permitted)
                notes: Optional[str] = None
                ticker_sector: str = _infer_sector(tier_id, asset_class)
            else:
                # Per-ticker override dict: {"symbol": "INDL", "override_structures": [...], "note": "..."}
                symbol = entry["symbol"].upper()
                effective_structures = list(
                    entry.get("override_structures", tier_permitted)
                )
                notes = entry.get("note")
                ticker_sector = entry.get("sector", _infer_sector(tier_id, asset_class))

            if symbol in universe:
                # Skip duplicates — first occurrence (lowest tier) wins.
                continue

            universe[symbol] = TickerInfo(
                symbol=symbol,
                tier=tier_id,
                tier_description=tier_description,
                asset_class=asset_class,
                permitted_structures=effective_structures,
                max_position_pct=max_pos,
                requires_fundamental_score=req_fundamental,
                options_filter=dict(options_filter),
                no_entry_days=list(no_entry_days),
                notes=notes,
                sector=ticker_sector,
            )

    return universe


# ---------------------------------------------------------------------------
# Module-level singleton — loaded once at import time
# ---------------------------------------------------------------------------

UNIVERSE: dict[str, TickerInfo] = load_universe()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_ticker_info(symbol: str) -> Optional[TickerInfo]:
    """
    Look up a ticker symbol in the pre-loaded universe.

    Parameters
    ----------
    symbol : str
        Ticker symbol (case-insensitive).

    Returns
    -------
    TickerInfo | None
        Resolved TickerInfo, or None if the symbol is not in the universe.
    """
    return UNIVERSE.get(symbol.upper())
