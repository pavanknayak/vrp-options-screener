"""Ticker Analysis page — recommendation card + 5 supplementary charts."""
import streamlit as st
from ui.components.regime_banner import render_regime_banner
from ui.charts import (
    chart_iv_term_structure, chart_vrp_history, chart_skew,
    chart_scenario_pnl, chart_gex_history,
)


def _render_recommendation_card(result: dict) -> None:
    """Render the recommendation card from a run_recommendation() result dict."""
    passed = result.get("passed", False)
    gonogo_summary = result.get("gonogo_summary", "Unknown")

    # Header
    status_color = "#2ecc71" if passed else "#e74c3c"
    status_label = "GO" if passed else "NO-GO"
    st.markdown(
        f"""<div style="border-left:6px solid {status_color}; padding:8px 16px;
                        background:{status_color}15; border-radius:4px; margin-bottom:16px;">
            <span style="font-size:1.3em; font-weight:700; color:{status_color};">
                {status_label}
            </span>
            &nbsp;&nbsp;<span style="color:#aaa;">{gonogo_summary}</span>
            </div>""",
        unsafe_allow_html=True,
    )

    if not passed:
        st.warning(f"This ticker did not pass the go/no-go screen: {gonogo_summary}")
        # Still show narrative if available
        for i, para_key in enumerate(["paragraph_1", "paragraph_2", "paragraph_3"], 1):
            para = result.get(para_key)
            if para:
                st.markdown(f"**Paragraph {i}:** {para}")
        return

    # Trade Parameters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Structure", result.get("structure", "N/A"))
        st.metric("Short Strike", f"${result.get('short_strike', 0):.1f}")
    with col2:
        st.metric("DTE", result.get("dte", "N/A"))
        long_strike = result.get("long_strike")
        st.metric("Long Strike", f"${long_strike:.1f}" if long_strike else "N/A")
    with col3:
        st.metric("Net Credit", f"${result.get('net_credit', 0):.2f}")
        st.metric("Max Loss", f"${result.get('max_loss', 0):.2f}")
    with col4:
        st.metric("Kelly Contracts", result.get("kelly_contracts", 0))
        kelly_pct = result.get("kelly_pct", 0.0) or 0.0
        st.metric("Kelly %", f"{kelly_pct:.1%}")

    st.divider()

    # Risk Levels
    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("Breakeven", f"${result.get('breakeven', 0):.2f}")
    with col6:
        st.metric("Hard Stop", f"${result.get('hard_stop', 0):.2f}")
    with col7:
        st.metric("Roll Trigger", f"${result.get('roll_trigger', 0):.2f}")

    # FOMC Status
    fomc_status = result.get("fomc_status")
    fomc_msg = result.get("fomc_message", "")
    if fomc_status:
        if fomc_status == "AVOID":
            st.warning(f"FOMC Warning: {fomc_msg}")
        else:
            st.info(f"FOMC: {fomc_msg}")

    st.divider()

    # Narratives
    st.subheader("Trade Reasoning")
    for label, key in [
        ("Why premium exists:", "paragraph_1"),
        ("Why enter now:", "paragraph_2"),
        ("What could go wrong:", "paragraph_3"),
    ]:
        para = result.get(key)
        if para:
            st.markdown(f"**{label}** {para}")

    # Order Text
    order_text = result.get("order_text")
    if order_text:
        st.subheader("Broker Order")
        st.code(order_text, language=None)


def render_ticker_analysis() -> None:
    """Render the Ticker Analysis page."""
    render_regime_banner()

    result = st.session_state.get("selected_result")
    ticker = st.session_state.get("selected_ticker", "")

    if not result:
        st.info("No ticker selected. Return to the Dashboard and click a row.")
        if st.button("Go to Dashboard"):
            st.switch_page("ui/pages/dashboard.py")
        return

    st.title(f"Ticker Analysis: {ticker}")

    # Back button
    if st.button("Back to Dashboard", key="btn_back_dashboard"):
        st.switch_page("ui/pages/dashboard.py")

    # Recommendation Card
    st.header("Recommendation")
    _render_recommendation_card(result)

    st.divider()

    # Five Charts in 2-column grid
    st.header("Supplementary Charts")

    # Use analytics_result embedded in the full result (stage2 stores analytics under 'analytics')
    analytics = result.get("analytics") or result  # fallback: top-level fields

    col_left, col_right = st.columns(2)
    with col_left:
        st.plotly_chart(chart_iv_term_structure(analytics), use_container_width=True)
        st.plotly_chart(chart_skew(analytics), use_container_width=True)
        st.plotly_chart(chart_gex_history(analytics), use_container_width=True)
    with col_right:
        st.plotly_chart(chart_vrp_history(analytics), use_container_width=True)
        st.plotly_chart(chart_scenario_pnl(result), use_container_width=True)

    # Go/No-Go Detail
    with st.expander("Go/No-Go Check Detail", expanded=False):
        checks = result.get("gonogo_checks") or []
        if checks:
            import pandas as pd
            checks_df = pd.DataFrame(checks)
            st.dataframe(checks_df, use_container_width=True, hide_index=True)
        else:
            st.info("No go/no-go check detail available.")
