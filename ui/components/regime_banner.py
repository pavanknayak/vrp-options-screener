"""Regime banner component — rendered at top of every page.

Thresholds and multipliers come from analytics.regime.detect_regime().
This module NEVER embeds VIX thresholds inline; all regime logic lives in analytics/regime.py.
"""
import streamlit as st
import yfinance as yf

from analytics.regime import detect_regime

REGIME_COLORS = {
    "Low":          "#2ecc71",   # green
    "Normal":       "#3498db",   # blue
    "Elevated":     "#e67e22",   # orange
    "High":         "#e74c3c",   # red
    "Crisis":       "#7b241c",   # dark red
    "VOL_UNSTABLE": "#8e44ad",   # purple
}


def _fetch_regime_data() -> dict:
    """Fetch VIX, VVIX, and T-bill rate; delegate regime logic to analytics.regime.detect_regime().

    Returns dict with keys: vix, vvix, regime_label, regime_multiplier, tbill_rate, gex_billions.
    Falls back to cached values in st.session_state['last_regime'] on error.
    """
    try:
        vix_ticker  = yf.Ticker("^VIX")
        vvix_ticker = yf.Ticker("^VVIX")
        vix_hist  = vix_ticker.history(period="2d")
        vvix_hist = vvix_ticker.history(period="2d")
        vix  = float(vix_hist["Close"].iloc[-1])  if not vix_hist.empty  else 20.0
        vvix = float(vvix_hist["Close"].iloc[-1]) if not vvix_hist.empty else 90.0
    except Exception:
        cached = st.session_state.get("last_regime", {})
        vix  = cached.get("vix",  20.0)
        vvix = cached.get("vvix", 90.0)

    # Delegate ALL regime logic to analytics.regime — no thresholds duplicated here.
    # Pass vvix so detect_regime can apply VOL_UNSTABLE if VVIX history is available;
    # without history the Z-score path is skipped and VIX thresholds govern.
    regime = detect_regime(vix=vix, vvix=vvix)

    # T-bill rate from session_state config (fetched by FRED fetcher at startup)
    tbill_rate = st.session_state.get("config", {}).get("risk_free_rate", 0.05)

    # GEX from last scan result if available
    scan_results = st.session_state.get("scan_results", [])
    gex = 0.0
    if scan_results:
        gex_vals = [r.get("gex_billions", 0.0) or 0.0 for r in scan_results[:10]]
        gex = sum(gex_vals) / len(gex_vals) if gex_vals else 0.0

    return {
        "vix":              vix,
        "vvix":             vvix,
        "regime_label":     regime["label"],
        "regime_multiplier": regime["multiplier"],
        "tbill_rate":       tbill_rate,
        "gex_billions":     gex,
    }


def render_regime_banner() -> None:
    """Render the regime banner at the top of the current page.

    Fetches live VIX / VVIX on each call (Streamlit reruns on navigation).
    Stores result in st.session_state['last_regime'] for downstream use.
    """
    data = _fetch_regime_data()
    st.session_state["last_regime"] = data

    label = data["regime_label"]
    color = REGIME_COLORS.get(label, "#3498db")
    vix   = data["vix"]
    vvix  = data["vvix"]
    mult  = data["regime_multiplier"]
    tbill = data["tbill_rate"] * 100   # display as percent
    gex   = data["gex_billions"]

    st.markdown(
        f"""
        <div style="background-color:{color}22; border-left:4px solid {color};
                    padding:8px 16px; border-radius:4px; margin-bottom:12px;
                    display:flex; flex-wrap:wrap; gap:24px; align-items:center;">
            <span style="color:{color}; font-weight:700; font-size:1.1em;">
                {label} Regime
            </span>
            <span>VIX: <b>{vix:.1f}</b></span>
            <span>VVIX: <b>{vvix:.1f}</b></span>
            <span>T-Bill: <b>{tbill:.2f}%</b></span>
            <span>GEX: <b>{gex:+.2f}B</b></span>
            <span>Size Mult: <b>{mult:.2f}x</b></span>
        </div>
        """,
        unsafe_allow_html=True,
    )
