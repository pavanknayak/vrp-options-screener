"""Scanner Dashboard page.

Primary user-facing view: shows all Stage 2 scan results in a sortable,
filterable 13-column table with row-click navigation and CSV export.
"""
import pandas as pd
import streamlit as st
from datetime import datetime
from ui.components.regime_banner import render_regime_banner
from ui.components.onboarding import render_onboarding, render_onboarding_button


def _build_dataframe(results: list[dict]) -> pd.DataFrame:
    """Convert scan result dicts to the 13-column display DataFrame."""
    rows = []
    for r in results:
        signals = r.get("signals") or {}
        iv30 = r.get("iv30") or 0.0
        vrp = r.get("vrp") or 0.0
        rows.append({
            "Ticker":      r.get("ticker", ""),
            "Tier":        r.get("tier", "N/A"),
            "Score":       round(
                r.get("composite_score") or signals.get("composite_score") or 0.0, 1
            ),
            "IV30":        round(iv30 * 100, 1),           # display as percent
            "VRP":         round(vrp * 100, 2),            # display as percent
            "VRP%":        round(vrp / iv30 * 100, 1) if iv30 else 0.0,
            "IVP":         round(
                (signals.get("ivp") or r.get("ivp") or 0.0) * 100, 1
            ),
            "Persistence": round(signals.get("vrp_persist_30d") or 0.0, 2),
            "Excess VRP":  round((signals.get("excess_vrp") or 0.0) * 100, 2),
            "Skew":        round(signals.get("skew_25d") or 0.0, 3),
            "EM Ratio":    round(
                signals.get("em_ratio") or r.get("em_ratio") or 0.0, 2
            ),
            "Earnings":    str(r.get("next_earnings") or "N/A"),
            "GO/NO-GO":    "GO" if r.get("passed") else "NO-GO",
        })
    return pd.DataFrame(rows)


def _score_badge(score: float) -> str:
    """Return plain-language score interpretation."""
    if score >= 90:   return "Exceptional"
    if score >= 75:   return "Strong"
    if score >= 60:   return "Good"
    if score >= 40:   return "Moderate"
    return "Weak"


def _score_color(score: float) -> str:
    if score >= 75:  return "normal"   # green in Streamlit
    if score >= 60:  return "off"      # light green
    if score >= 40:  return "inverse"  # yellow/orange
    return "off"


def _render_risk_panel() -> None:
    """Show leading risk indicators: VVIX z-score, HYG stress, correlation pulse."""
    try:
        import yfinance as yf
        import numpy as np

        # Fetch HYG (high-yield bonds) and SPY for credit stress signal
        @st.cache_data(ttl=1800)
        def _fetch_risk_data():
            hyg = yf.download("HYG", period="60d", auto_adjust=True, progress=False)["Close"]
            spy = yf.download("SPY", period="60d", auto_adjust=True, progress=False)["Close"]
            vvix = yf.download("^VVIX", period="260d", auto_adjust=True, progress=False)["Close"]
            return hyg, spy, vvix

        hyg, spy, vvix = _fetch_risk_data()

        indicators_hit = 0
        indicator_details = []

        # 1. VVIX Z-score
        if vvix is not None and len(vvix) > 30:
            vvix_z = float((float(vvix.iloc[-1]) - vvix.mean()) / vvix.std())
            if vvix_z > 1.5:
                indicators_hit += 1
                indicator_details.append(f"VVIX elevated (Z={vvix_z:.1f})")

        # 2. HYG/SPY stress ratio
        if hyg is not None and spy is not None and len(hyg) > 10 and len(spy) > 10:
            ratio = (hyg / hyg.iloc[0]) / (spy / spy.iloc[0])  # relative performance
            ratio_z = float((ratio.iloc[-1] - ratio.mean()) / max(ratio.std(), 1e-6))
            if ratio_z < -1.5:  # HYG underperforming SPY = credit stress
                indicators_hit += 1
                indicator_details.append(f"Credit stress (HYG/SPY ratio Z={ratio_z:.1f})")

        # Display
        if indicators_hit == 0:
            st.success("Risk Indicators: All Clear", icon="✅")
        elif indicators_hit == 1:
            st.warning(
                f"Risk Indicators: {indicators_hit} signal elevated — {', '.join(indicator_details)}",
                icon="⚠️",
            )
        else:
            st.error(
                f"Risk Indicators: {indicators_hit} signals elevated — {', '.join(indicator_details)}",
                icon="🚨",
            )
    except Exception:
        pass  # Never block the dashboard if risk panel fails


def render_dashboard() -> None:
    """Render the Scanner Dashboard page."""
    render_onboarding()
    render_regime_banner()
    _render_risk_panel()
    st.title("Scanner Dashboard")

    # --- Scan Status ---
    results: list[dict] = st.session_state.get("scan_results", [])
    last_scan: str | None = st.session_state.get("last_scan_time")
    scan_mode: str = st.session_state.get("scan_mode", "Full")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Results", len(results))
    with col2:
        st.metric("Scan Mode", scan_mode)
    with col3:
        st.metric("Last Scan", last_scan or "Never")

    # --- Run Scan Controls ---
    st.divider()
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
    with btn_col1:
        if st.button("Run Full Scan", type="primary", key="btn_full_scan"):
            _trigger_scan("full")
    with btn_col2:
        if st.button("Quick Refresh (Top 30)", key="btn_quick_scan"):
            _trigger_scan("quick")
    with btn_col3:
        if st.button("Event Refresh", key="btn_event_scan"):
            _trigger_scan("event")
    with btn_col4:
        render_onboarding_button()

    if not results:
        st.info("No scan results yet. Run a scan to populate the dashboard.")
        return

    # --- Stage 1 only disclaimer (no Schwab keys) ---
    if results and results[0].get("_stage1_only"):
        st.warning(
            "Schwab credentials not configured — showing Stage 1 (yfinance) pre-screening results. "
            "Scores, IVP, and VRP are approximate. GO/NO-GO requires Stage 2. "
            "Add SCHWAB_APP_KEY + SCHWAB_APP_SECRET to enable full analysis."
        )

    # --- Build DataFrame ---
    df = _build_dataframe(results)

    # --- Filters ---
    with st.expander("Filters", expanded=False):
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            gonogo_filter = st.multiselect(
                "GO/NO-GO",
                options=["GO", "NO-GO"],
                default=["GO", "NO-GO"],
                key="filter_gonogo",
            )
        with fcol2:
            tier_options = sorted(df["Tier"].unique().tolist())
            tier_filter = st.multiselect(
                "Tier",
                options=tier_options,
                default=tier_options,
                key="filter_tier",
            )
        with fcol3:
            min_score = st.slider(
                "Min Score",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=1.0,
                key="filter_min_score",
            )

    mask = (
        df["GO/NO-GO"].isin(gonogo_filter)
        & df["Tier"].isin(tier_filter)
        & (df["Score"] >= min_score)
    )
    df_filtered = df[mask].reset_index(drop=True)

    # --- Score Guide ---
    with st.expander("Score Guide", expanded=False):
        cols = st.columns(5)
        for i, (label, rng, color) in enumerate([
            ("Weak (0-39)", "Premium not elevated enough", "🔴"),
            ("Moderate (40-59)", "Some premium available", "🟡"),
            ("Good (60-74)", "Clear premium, favorable conditions", "🟢"),
            ("Strong (75-89)", "High premium, persistent signal", "🟢"),
            ("Exceptional (90+)", "Rare convergence of all signals", "⭐"),
        ]):
            with cols[i]:
                st.caption(f"{color} **{label}**")
                st.caption(rng)

    # --- CSV Export (UI-06) ---
    csv_bytes = df_filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Export to CSV",
        data=csv_bytes,
        file_name=f"vrp_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="btn_export_csv",
    )

    # --- Interactive Table ---
    def _style_gonogo(val: str) -> str:
        if val == "GO":
            return "color: #2ecc71; font-weight:700"
        return "color: #e74c3c; font-weight:700"

    styled = df_filtered.style.applymap(_style_gonogo, subset=["GO/NO-GO"])

    # Row selection via st.dataframe (requires Streamlit >= 1.36)
    event = st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="dashboard_table",
    )

    selected_rows = (
        event.selection.rows
        if event and hasattr(event, "selection")
        else []
    )
    # --- Column Definitions ---
    with st.expander("Column Definitions", expanded=False):
        st.markdown("""
    | Column | Meaning |
    |--------|---------|
    | **Score** | Composite VRP score 0-100. Higher = more overpriced options. ≥60 is worth analyzing. |
    | **IV30** | 30-day implied volatility (%). How expensive options are in annualized terms. |
    | **VRP** | Volatility Risk Premium (%). How much IV exceeds recent realized volatility. Positive = you're being overpaid. |
    | **VRP%** | VRP as a % of IV30 — measures the relative richness of the premium. |
    | **IVP** | IV Percentile. 80 means options are pricier than 80% of the past year's days. |
    | **Persistence** | Fraction of the last 30 days where VRP was positive. Higher = more reliable premium. |
    | **Excess VRP** | VRP above and beyond what beta to the market explains. Pure idiosyncratic premium. |
    | **Skew** | Put-call IV spread at 25-delta. Higher = more demand for downside protection (good for sellers). |
    | **EM Ratio** | Implied Move ÷ Expected Move. >1.0 = options overpriced vs how much stock actually moves. |
    | **GO/NO-GO** | Whether the trade passed all 21 quality gates (requires Schwab Stage 2). |
        """)

    if selected_rows:
        idx = selected_rows[0]
        selected_ticker = df_filtered.iloc[idx]["Ticker"]
        st.session_state["selected_ticker"] = selected_ticker
        # Store the full result dict for the Ticker Analysis page
        for r in results:
            if r.get("ticker") == selected_ticker:
                st.session_state["selected_result"] = r
                break
        st.switch_page(st.session_state["_pages"]["ticker_analysis"])


def _trigger_scan(mode: str) -> None:
    """Trigger a scan via the orchestrator and store results in session state."""
    from scanner.orchestrator import get_orchestrator

    orchestrator = get_orchestrator()
    with st.spinner(f"Running {mode} scan..."):
        try:
            if mode == "full":
                results = orchestrator.run_full_scan()
            elif mode == "quick":
                results = orchestrator.run_quick_refresh()
            elif mode == "event":
                results = orchestrator.run_event_refresh()
            else:
                results = orchestrator.run_full_scan()
            st.session_state["scan_results"] = results or []
            st.session_state["last_scan_time"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
            st.session_state["scan_mode"] = mode.capitalize()
            st.success(f"Scan complete — {len(results or [])} results.")
        except Exception as exc:
            st.error(f"Scan failed: {exc}")
