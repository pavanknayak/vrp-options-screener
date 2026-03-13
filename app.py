"""VRP Options Screener — Streamlit app entry point.

Run with:  streamlit run app.py
"""
import streamlit as st

# ---- Page Config (must be first Streamlit call) ----
st.set_page_config(
    page_title="VRP Options Screener",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _initialize_session() -> None:
    """Run once at startup (guarded by session_state flag).

    Loads config, seeds scan_results, starts APScheduler via ScanOrchestrator.
    Uses st.session_state['_initialized'] flag to avoid re-running on every Streamlit rerun.
    """
    if st.session_state.get("_initialized"):
        return

    # Load config into session state
    from ui.components.config_sidebar import load_config
    st.session_state["config"] = load_config()

    # Initialize empty scan results
    if "scan_results" not in st.session_state:
        st.session_state["scan_results"] = []
    if "last_scan_time" not in st.session_state:
        st.session_state["last_scan_time"] = None
    if "scan_mode" not in st.session_state:
        st.session_state["scan_mode"] = "Full"

    # Start the ScanOrchestrator (starts APScheduler for 9:45 AM auto-scan).
    # Note: get_orchestrator() only creates the singleton — start_scheduler() must
    # be called explicitly to start the APScheduler BackgroundScheduler.
    try:
        from scanner.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        orchestrator.start_scheduler()
        # Store reference so it is not garbage-collected
        st.session_state["_orchestrator"] = orchestrator
    except Exception as exc:
        st.session_state["_orchestrator_error"] = str(exc)

    st.session_state["_initialized"] = True


def main() -> None:
    """Define navigation and render the selected page."""
    _initialize_session()

    # ---- Navigation Definition ----
    # st.Page references file paths relative to the working directory.
    # default=True marks the landing page.
    pages = [
        st.Page(
            "ui/pages/dashboard.py",
            title="Scanner Dashboard",
            icon=":material/dashboard:",
            default=True,
        ),
        st.Page(
            "ui/pages/ticker_analysis.py",
            title="Ticker Analysis",
            icon=":material/candlestick_chart:",
        ),
        st.Page(
            "ui/pages/custom_lookup.py",
            title="Custom Lookup",
            icon=":material/search:",
        ),
        st.Page(
            "ui/pages/portfolio_monitor.py",
            title="Portfolio Monitor",
            icon=":material/pie_chart:",
        ),
        st.Page(
            "ui/pages/settings.py",
            title="Settings",
            icon=":material/settings:",
        ),
    ]

    pg = st.navigation(pages)

    # ---- Shared Sidebar: Config Controls ----
    from ui.components.config_sidebar import render_config_sidebar
    render_config_sidebar()

    # ---- Show orchestrator error if startup failed ----
    orch_error = st.session_state.get("_orchestrator_error")
    if orch_error:
        with st.sidebar:
            st.error(f"Orchestrator init failed: {orch_error}")

    # ---- Run Selected Page ----
    pg.run()


if __name__ == "__main__":
    main()
