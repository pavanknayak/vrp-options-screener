"""Custom Ticker Lookup page — on-demand full Stage 2 analysis for any ticker.

Self-contained: does not require a prior scan to have run.  Calls the
ScanOrchestrator single-ticker path which chains analytics + fundamentals +
recommendations and returns one result dict.
"""
import time
import streamlit as st
from ui.components.regime_banner import render_regime_banner
from ui.pages.ticker_analysis import _render_recommendation_card
from ui.charts import (
    chart_iv_term_structure,
    chart_vrp_history,
    chart_skew,
    chart_scenario_pnl,
    chart_gex_history,
)


def _run_single_analysis(ticker: str) -> dict | None:
    """Run a full Stage 2 single-ticker analysis via the orchestrator.

    Returns the recommendation result dict or None on total failure.
    Stores result in st.session_state['lookup_result'] for display persistence.

    Note: orchestrator.run_single_ticker() delegates to modes.run_single_ticker()
    which returns a single dict (not a list).  This function handles both shapes
    for safety — list wrapping is normalised to a single dict.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        st.error("Please enter a ticker symbol.")
        return None

    from scanner.orchestrator import get_orchestrator

    orchestrator = get_orchestrator()
    start = time.time()
    try:
        result = orchestrator.run_single_ticker(ticker)
        elapsed = time.time() - start

        # Normalise: modes.run_single_ticker returns a plain dict, but guard
        # against a future list-returning wrapper just in case.
        if isinstance(result, list):
            if not result:
                st.error(
                    f"No result returned for {ticker}. "
                    "Check that it is a valid ticker with options data."
                )
                return None
            result = result[0]

        if not result or result.get("error") == "no_result":
            st.error(
                f"No result returned for {ticker}. "
                "Check that it is in the universe or has valid options data."
            )
            return None

        result["_lookup_elapsed"] = elapsed
        return result

    except Exception as exc:
        elapsed = time.time() - start
        st.error(f"Analysis failed for {ticker} after {elapsed:.1f}s: {exc}")
        return None


def render_custom_lookup() -> None:
    """Render the Custom Ticker Lookup page.

    Layout:
      - Regime banner
      - Ticker text input + Analyze button
      - Spinner during analysis
      - On success: success message, optional navigation to Ticker Analysis page,
        recommendation card, five charts in 2-column grid, go/no-go detail expander
    """
    render_regime_banner()
    st.title("Custom Ticker Lookup")
    st.caption(
        "Run a full Stage 2 analysis on any ticker on demand. "
        "Results depend on Schwab data availability and may take up to 30 seconds."
    )

    # --- Input row ---
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        ticker_input = st.text_input(
            "Ticker Symbol",
            value=st.session_state.get("lookup_ticker", ""),
            placeholder="e.g. AAPL, SPY, QQQ",
            key="custom_lookup_input",
            label_visibility="collapsed",
        ).strip().upper()
    with col_btn:
        analyze_clicked = st.button("Analyze", type="primary", key="btn_analyze_custom")

    # --- Run analysis when button clicked ---
    if analyze_clicked:
        if not ticker_input:
            st.warning("Enter a ticker symbol before clicking Analyze.")
        else:
            st.session_state["lookup_ticker"] = ticker_input
            # Clear previous result so stale data isn't shown if this fails
            st.session_state.pop("lookup_result", None)
            with st.spinner(f"Running full Stage 2 analysis for {ticker_input}..."):
                result = _run_single_analysis(ticker_input)
            if result:
                st.session_state["lookup_result"] = result

    # --- Display Result ---
    result = st.session_state.get("lookup_result")
    ticker_label = st.session_state.get("lookup_ticker", "")

    if not result:
        st.info("Enter a ticker symbol above and click Analyze to see results.")
        return

    elapsed = result.get("_lookup_elapsed", 0.0)
    st.success(f"Analysis complete for **{ticker_label}** in {elapsed:.1f}s")

    # Offer navigation to the full Ticker Analysis page
    if st.button("View in Ticker Analysis Page", key="btn_view_full"):
        st.session_state["selected_ticker"] = ticker_label
        st.session_state["selected_result"] = result
        st.switch_page("ui/pages/ticker_analysis.py")

    st.divider()

    # --- Recommendation Card (reuses component from ticker_analysis) ---
    st.header("Recommendation")
    _render_recommendation_card(result)

    st.divider()

    # --- Five Charts ---
    st.header("Charts")

    # Stage 2 stores the analytics sub-dict under 'analytics'; fall back to
    # top-level result fields when that key is absent.
    analytics = result.get("analytics") or result

    col_left, col_right = st.columns(2)
    with col_left:
        st.plotly_chart(chart_iv_term_structure(analytics), use_container_width=True)
        st.plotly_chart(chart_skew(analytics), use_container_width=True)
        st.plotly_chart(chart_gex_history(analytics), use_container_width=True)
    with col_right:
        st.plotly_chart(chart_vrp_history(analytics), use_container_width=True)
        st.plotly_chart(chart_scenario_pnl(result), use_container_width=True)

    # --- Go/No-Go Detail ---
    with st.expander("Go/No-Go Detail", expanded=False):
        checks = result.get("gonogo_checks") or []
        if checks:
            import pandas as pd
            st.dataframe(
                pd.DataFrame(checks),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No go/no-go check detail available.")
