"""
universe
--------
Ticker universe package for the VRP Options Screener.

Public API
----------
    from universe import TickerInfo, load_universe, get_ticker_info, UNIVERSE
"""

from universe.loader import (
    UNIVERSE,
    TickerInfo,
    get_ticker_info,
    load_universe,
)

__all__ = [
    "TickerInfo",
    "load_universe",
    "get_ticker_info",
    "UNIVERSE",
]
