"""
data/fomc.py — Static FOMC meeting calendar and context helper.

FOMC_DATES lists the announcement day (second day of each meeting) for
2025 and 2026.  No external API is ever called; update this list annually.

fomc_context() is consumed by the recommendation engine (Phase 5) to flag
high-event-risk windows around FOMC decisions.
"""
from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Static FOMC decision dates — update each year
# ---------------------------------------------------------------------------
FOMC_DATES: list[str] = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def fomc_context(today: date, expiration_date: date) -> tuple[str, str]:
    """Return (status, message) describing how upcoming FOMC dates affect a trade.

    Priority order (first match wins):
      AVOID          — FOMC is 1–2 days away; enter after the announcement.
      PRIORITY_ENTRY — FOMC concluded yesterday; vol crush likely in progress.
      FOMC_IN_WINDOW — An FOMC date falls between today and expiration.
      CLEAR          — No FOMC event in the expiration window.

    Args:
        today:           The evaluation date.
        expiration_date: The option's expiration date.

    Returns:
        A (status, message) tuple.
    """
    fomc_dates_parsed = [date.fromisoformat(d) for d in FOMC_DATES]

    # --- Pass 1: AVOID (1-2 days before FOMC) ---
    for fomc_date in fomc_dates_parsed:
        days_until = (fomc_date - today).days
        if 0 < days_until <= 2:
            return (
                "AVOID",
                f"FOMC in {days_until} days. High event risk. Wait for post-FOMC entry.",
            )

    # --- Pass 2: PRIORITY_ENTRY (FOMC was yesterday) ---
    for fomc_date in fomc_dates_parsed:
        days_since = (today - fomc_date).days
        if days_since == 1:
            return (
                "PRIORITY_ENTRY",
                "FOMC concluded yesterday. Vol crush likely in progress. Prime entry window.",
            )

    # --- Pass 3: FOMC_IN_WINDOW (FOMC falls between today and expiration) ---
    for fomc_date in fomc_dates_parsed:
        if today < fomc_date < expiration_date:
            return (
                "FOMC_IN_WINDOW",
                f"FOMC on {fomc_date} falls within this expiration window. Moderate event risk.",
            )

    # --- Default: CLEAR ---
    return ("CLEAR", "No FOMC meeting in expiration window.")
