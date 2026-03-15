"""Ticker Analysis page — recommendation card + 5 supplementary charts."""
import streamlit as st
from ui.components.regime_banner import render_regime_banner
from ui.charts import (
    chart_iv_term_structure, chart_vrp_history, chart_skew,
    chart_scenario_pnl, chart_gex_history, chart_pnl_simulator,
)


def _render_score_explanation(signals: dict, composite_score: float) -> None:
    """Render plain-language explanation of why the composite score is what it is."""
    with st.expander("Why this score?", expanded=False):
        st.caption("Each signal contributes to the overall score. ✓ = favorable, ✗ = unfavorable")

        checks = [
            ("IV Percentile", signals.get("ivp", 0), 0.60,
             f"{signals.get('ivp', 0)*100:.0f}th percentile — options are {'unusually expensive' if signals.get('ivp', 0) > 0.6 else 'near normal'} right now"),
            ("VRP Magnitude", signals.get("vrp_pctile", 0), 0.50,
             f"Premium is at the {signals.get('vrp_pctile', 0)*100:.0f}th percentile of its 1-year history"),
            ("VRP Persistence", signals.get("vrp_persist_30d", 0), 0.50,
             f"VRP was positive {signals.get('vrp_persist_30d', 0)*100:.0f}% of the last 30 days"),
            ("Statistical Significance", signals.get("vrp_zscore", 0), 1.0,
             f"VRP is {signals.get('vrp_zscore', 0):.1f} standard deviations above its mean"),
            ("Expected Move Ratio", signals.get("em_ratio", 1.0), 1.1,
             f"Options price in {'more' if signals.get('em_ratio', 1) > 1 else 'less'} movement than historically realized (ratio: {signals.get('em_ratio', 1):.2f}x)"),
            ("Put-Call Skew", signals.get("skew_25d", 0), 0.02,
             f"Put premium over call premium: {signals.get('skew_25d', 0)*100:.1f} vol points"),
            ("Dealer Positioning", signals.get("gex_billions", 0), 0,
             f"Dealer GEX: ${signals.get('gex_billions', 0):.2f}B — {'supportive' if signals.get('gex_billions', 0) > 0 else 'adverse'}"),
            ("Vol Stability", signals.get("vov_z", 0), 0,
             f"Vol-of-vol Z: {signals.get('vov_z', 0):.1f} — {'stable' if signals.get('vov_z', 0) < 1.5 else 'unstable'} IV environment"),
        ]

        for name, value, threshold, description in checks:
            is_good = (value >= threshold) if name != "Vol Stability" else (value < 1.5)
            icon = "✓" if is_good else "✗"
            color = "green" if is_good else "orange"
            st.markdown(f":{color}[{icon}] **{name}** — {description}")


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

    # Score Explanation
    signals = result.get("signals") or {}
    composite_score = (
        result.get("composite_score")
        or signals.get("composite_score")
        or 0.0
    )
    _render_score_explanation(signals, composite_score)

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

    # P&L Simulator
    try:
        rec = result.get("recommendation", {}) or {}
        structure_res = rec.get("structure_result", {}) or {}
        if not structure_res:
            # Fallback: pull top-level fields that stage2 may store directly
            structure_res = result

        spot = float(result.get("spot") or 100)
        short_strike = float(
            structure_res.get("short_strike") or rec.get("short_strike") or result.get("short_strike") or spot * 0.95
        )
        long_strike = structure_res.get("long_strike") or rec.get("long_strike") or result.get("long_strike")
        net_credit = float(rec.get("net_credit") or result.get("net_credit") or 0)
        max_loss = float(rec.get("max_loss") or result.get("max_loss") or short_strike * 100)
        expiration = str(
            structure_res.get("expiration_date") or rec.get("expiration_date") or result.get("expiration_date") or ""
        )
        structure_name = str(
            structure_res.get("structure") or rec.get("structure") or result.get("structure") or "csp"
        )

        if net_credit > 0:
            st.divider()
            st.subheader("P&L Simulator")
            st.caption("Explore what happens at different underlying prices at expiration.")

            price_range = (float(spot * 0.50), float(spot * 1.30))
            simulated_price = st.slider(
                "Underlying price at expiration",
                min_value=price_range[0],
                max_value=price_range[1],
                value=float(spot),
                step=float(spot * 0.01),
                format="$%.2f",
                key=f"pnl_sim_{result.get('ticker', 'x')}",
            )

            net_credit_contract = net_credit * 100
            max_loss_contract = max_loss

            if structure_name == "csp":
                sim_pnl = (
                    net_credit_contract if simulated_price >= short_strike
                    else (simulated_price - short_strike + net_credit) * 100
                )
            else:
                raw = (simulated_price - short_strike + net_credit) * 100
                sim_pnl = max(-max_loss_contract, min(net_credit_contract, raw))

            breakeven = short_strike - net_credit
            status = (
                "Full Profit" if simulated_price >= short_strike
                else ("Partial Profit" if sim_pnl > 0 else "Loss")
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("P&L at this price", f"${sim_pnl:,.0f}", delta=status)
            col2.metric("Breakeven", f"${breakeven:.2f}")
            col3.metric("Max Profit", f"${net_credit_contract:,.0f}")

            st.plotly_chart(
                chart_pnl_simulator(
                    structure_name, spot, short_strike, long_strike,
                    net_credit, max_loss, expiration,
                ),
                use_container_width=True,
            )
    except Exception:
        pass  # Never block the page if the simulator fails

    # Go/No-Go Detail
    with st.expander("Go/No-Go Check Detail", expanded=False):
        checks = result.get("gonogo_checks") or []
        if checks:
            import pandas as pd
            checks_df = pd.DataFrame(checks)
            st.dataframe(checks_df, use_container_width=True, hide_index=True)
        else:
            st.info("No go/no-go check detail available.")
