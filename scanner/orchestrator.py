from __future__ import annotations
import logging
import threading
from datetime import datetime, timezone
from typing import Optional
from scanner.stage1 import run_stage1
from scanner.stage2 import run_stage2
from scanner.modes import (
    run_quick_refresh,
    run_single_ticker,
    run_event_refresh,
    check_vix_event_trigger,
)
from data.fred_fetcher import get_risk_free_rate, fetch_vix_history
from universe.loader import load_universe

logger = logging.getLogger(__name__)


def _stage1_to_dict(s1) -> dict:
    """Convert a Stage1Result into the minimal dict format expected by the dashboard.

    Used when Schwab is not configured so Stage 1 results are still displayable.
    Fields that require Stage 2 (full analytics, signals, recommendation) are
    set to sensible defaults so _build_dataframe() in dashboard.py doesn't error.
    """
    return {
        "ticker": s1.ticker,
        "tier": s1.tier,
        "composite_score": round(s1.score * 100, 1),   # scale to 0-100 range
        "iv30": s1.atm_iv,
        "vrp": s1.vrp_approx,
        "ivp": s1.ivp_approx,
        "next_earnings": str(s1.earnings_date) if s1.earnings_date else None,
        "passed": False,   # can't determine GO/NO-GO without full Stage 2 analysis
        "signals": {
            "ivp": s1.ivp_approx,
            "composite_score": round(s1.score * 100, 1),
        },
        "_stage1_only": True,   # flag so UI can show a disclaimer
    }


class ScanOrchestrator:
    """
    Coordinates the two-stage VRP scanner and all supplementary scan modes.

    Thread-safe: a threading.Lock guards _results and _status writes.
    Designed to be instantiated once and shared across Streamlit reruns.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: list[dict] = []
        self._stage1_candidates: list = []
        self._status: dict = {
            "state": "idle",
            "last_run_utc": None,
            "candidate_count": 0,
            "error": None,
        }
        self._scheduler = None

    def run_full_scan(self, n_workers: int = 20, top_n: int = 175) -> list[dict]:
        """Run Stage 1 (yfinance pre-filter) then Stage 2 (Schwab deep analysis).

        If Schwab credentials are not configured, Stage 2 is skipped and Stage 1
        results are returned directly as minimal result dicts so the dashboard
        is still populated without Schwab keys.

        Updates internal cache. Thread-safe — concurrent calls are serialized
        by the lock (second caller blocks until first scan completes).
        Returns the results list.
        """
        with self._lock:
            self._set_status(state="running", error=None)

        try:
            logger.info("[ORCHESTRATOR] Full scan starting")

            r = get_risk_free_rate()
            vix = self._get_vix()

            universe = load_universe()
            stage1_results = run_stage1(universe=universe, n_workers=n_workers, top_n=top_n)

            from data.schwab_client import get_schwab_client
            schwab_available = get_schwab_client() is not None

            if schwab_available:
                final_results = run_stage2(stage1_results, r=r, vix=vix)
            else:
                logger.info(
                    "[ORCHESTRATOR] Schwab not configured — returning Stage 1 results (%d)",
                    len(stage1_results),
                )
                final_results = [_stage1_to_dict(s1) for s1 in stage1_results]

            with self._lock:
                self._results = final_results
                self._stage1_candidates = stage1_results
                self._set_status(
                    state="complete",
                    last_run_utc=datetime.now(timezone.utc).isoformat(),
                    candidate_count=len(final_results),
                    error=None,
                )

            logger.info("[ORCHESTRATOR] Full scan complete — %d results", len(final_results))
            return final_results

        except Exception as exc:
            logger.error("[ORCHESTRATOR] Full scan failed: %s", exc)
            with self._lock:
                self._set_status(state="error", error=str(exc))
            return []

    def run_quick_refresh(self, top_n: int = 30) -> list[dict]:
        with self._lock:
            prev = list(self._results)
        if not prev:
            logger.warning("[ORCHESTRATOR] Quick refresh called with no prior results — run full scan first")
            return []
        updated = run_quick_refresh(prev, top_n=top_n)
        with self._lock:
            updated_by_ticker = {r["ticker"]: r for r in updated}
            self._results = [updated_by_ticker.get(r["ticker"], r) for r in self._results]
        return updated

    def run_single_ticker(self, ticker: str) -> dict:
        return run_single_ticker(ticker)

    def run_event_refresh(self) -> list[dict]:
        with self._lock:
            prev = list(self._results)
        if not prev:
            return []
        updated = run_event_refresh(prev, top_n=50)
        with self._lock:
            updated_by_ticker = {r["ticker"]: r for r in updated}
            self._results = [updated_by_ticker.get(r["ticker"], r) for r in self._results]
        return updated

    def get_results(self) -> list[dict]:
        with self._lock:
            return list(self._results)

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _set_status(self, **kwargs) -> None:
        """Must be called while self._lock is held."""
        self._status.update(kwargs)

    def _get_vix(self) -> float:
        try:
            hist = fetch_vix_history(lookback_days=5)
            if hist is not None and not hist.empty:
                return float(hist.iloc[-1])
        except Exception:
            pass
        return 20.0

    def start_scheduler(self) -> None:
        """Start the APScheduler BackgroundScheduler for 9:45 AM ET daily trigger.

        Safe to call multiple times — will not start a second scheduler.
        """
        if self._scheduler is not None and self._scheduler.running:
            logger.debug("[ORCHESTRATOR] Scheduler already running")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.error("[ORCHESTRATOR] APScheduler not installed — auto-trigger disabled")
            return

        self._scheduler = BackgroundScheduler(timezone="US/Eastern")
        self._scheduler.add_job(
            func=self._scheduled_full_scan,
            trigger=CronTrigger(hour=9, minute=45, day_of_week="mon-fri", timezone="US/Eastern"),
            id="full_scan_9_45",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            func=self._check_and_run_event_refresh,
            trigger=CronTrigger(
                hour="9-15", minute="*/5", day_of_week="mon-fri", timezone="US/Eastern"
            ),
            id="vix_event_poll",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("[ORCHESTRATOR] Scheduler started — full scan at 09:45, VIX poll every 5min Mon-Fri")

    def stop_scheduler(self) -> None:
        """Stop the APScheduler gracefully. Safe to call if scheduler not running."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[ORCHESTRATOR] Scheduler stopped")

    def _scheduled_full_scan(self) -> None:
        """APScheduler job body — runs full scan, logs any failure."""
        logger.info("[ORCHESTRATOR] APScheduler triggered full scan at %s", datetime.now())
        try:
            self.run_full_scan()
        except Exception as exc:
            logger.error("[ORCHESTRATOR] Scheduled full scan failed: %s", exc)

    def _check_and_run_event_refresh(self) -> None:
        """APScheduler VIX polling job — fires every 5 min during market hours.

        Calls check_vix_event_trigger(); if VIX has risen >= 5% vs prior close,
        automatically triggers run_event_refresh().
        """
        try:
            if check_vix_event_trigger():
                logger.warning("[ORCHESTRATOR] VIX spike detected (>=5%%) — triggering Event Refresh")
                self.run_event_refresh()
        except Exception as exc:
            logger.error("[ORCHESTRATOR] VIX event check failed: %s", exc)


# Module-level singleton — created once, shared across Streamlit reruns
_ORCHESTRATOR: Optional[ScanOrchestrator] = None
_ORCH_LOCK = threading.Lock()


def get_orchestrator() -> ScanOrchestrator:
    """Return the module-level ScanOrchestrator singleton, creating it on first call."""
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        with _ORCH_LOCK:
            if _ORCHESTRATOR is None:
                _ORCHESTRATOR = ScanOrchestrator()
    return _ORCHESTRATOR


def get_scan_results() -> list[dict]:
    """Convenience: return latest Stage 2 results from the singleton orchestrator."""
    return get_orchestrator().get_results()


def get_scan_status() -> dict:
    """Convenience: return status dict from the singleton orchestrator."""
    return get_orchestrator().get_status()
