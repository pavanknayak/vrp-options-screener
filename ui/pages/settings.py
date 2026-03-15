"""Settings / Configuration page — full-width config + universe management + Schwab status."""
import os
import json
import streamlit as st
from ui.components.regime_banner import render_regime_banner
from ui.components.config_sidebar import (
    load_config, save_config, DEFAULT_CONFIG, render_config_sidebar
)


UNIVERSE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "universe", "tickers.json"
)

ALL_TIERS = ["1A","1B","1C","1D","1E","1F","1G","1H","1I","2","3","4","5","6","7"]

TIER_DESCRIPTIONS = {
    "1A": "US Broad Index ETFs (SPY, QQQ, IWM...)",
    "1B": "US Sector ETFs",
    "1C": "US Factor ETFs",
    "1D": "Fixed Income ETFs",
    "1E": "Commodity ETFs",
    "1F": "Volatility ETFs/ETNs",
    "1G": "Crypto ETFs (Spread/Collar only)",
    "1H": "Leveraged ETFs",
    "1I": "International Broad ETFs",
    "2":  "S&P 500 Large Cap",
    "3":  "Mid Cap / Russell 1000",
    "4":  "Small Cap / Russell 2000",
    "5":  "Growth / Speculative Large Cap",
    "6":  "China ADRs (Spread/Collar only)",
    "7":  "Rest-of-World ADRs",
}


def _load_universe() -> dict[str, list[str]]:
    """Load the ticker universe JSON file. Returns dict mapping tier -> list of tickers.

    Note: reads universe/tickers.json directly (not via universe/loader.py) because
    this is a write path — we need raw file access to add/remove tickers.
    """
    try:
        with open(UNIVERSE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {tier: [] for tier in ALL_TIERS}


def _save_universe(universe: dict[str, list[str]]) -> None:
    """Persist universe changes to tickers.json."""
    with open(UNIVERSE_FILE, "w") as f:
        json.dump(universe, f, indent=2)


def _schwab_status() -> tuple[bool, bool, str]:
    """Returns (has_credentials, token_valid, status_message).

    Checks SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables.
    If both are set, attempts a lightweight client initialization to verify OAuth validity.
    """
    key_set    = bool(os.environ.get("SCHWAB_APP_KEY", "").strip())
    secret_set = bool(os.environ.get("SCHWAB_APP_SECRET", "").strip())
    if not key_set or not secret_set:
        return False, False, "Schwab credentials not set. Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET environment variables."

    # Attempt a lightweight token check
    try:
        from data.schwab_client import get_schwab_client
        client = get_schwab_client()
        # Token validity test: if client initializes without error, credentials are available
        return True, True, "Schwab connected. OAuth token valid."
    except Exception as exc:
        return True, False, f"Schwab credentials found but OAuth failed: {exc}"


def render_settings() -> None:
    """Render the Settings page."""
    render_regime_banner()
    st.title("Settings & Configuration")

    # === Section 1: Core Configuration ===
    st.header("Core Configuration")
    st.caption(
        "These settings are also accessible from the sidebar on every page. "
        "Changes saved here persist to config.json."
    )

    if "config" not in st.session_state:
        st.session_state["config"] = load_config()

    cfg = st.session_state["config"]

    with st.form("settings_core_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Portfolio")
            cfg["portfolio_value"] = st.number_input(
                "Portfolio Value ($)", min_value=10_000.0, max_value=10_000_000.0,
                value=float(cfg["portfolio_value"]), step=5_000.0, key="settings_pv",
            )
            cfg["max_position_pct"] = st.number_input(
                "Max Position % (0–1)", min_value=0.01, max_value=0.25,
                value=float(cfg["max_position_pct"]), step=0.01, format="%.2f",
                key="settings_max_pct",
            )
            cfg["max_positions"] = st.number_input(
                "Max Simultaneous Positions", min_value=1, max_value=50,
                value=int(cfg["max_positions"]), step=1, key="settings_max_pos",
            )

        with col2:
            st.subheader("Screening Thresholds")
            cfg["min_vrp_score"] = st.number_input(
                "Min VRP Score (0–100)", min_value=0.0, max_value=100.0,
                value=float(cfg["min_vrp_score"]), step=1.0, key="settings_min_score",
            )
            cfg["min_ivp"] = st.number_input(
                "Min IVP Percentile (0–1)", min_value=0.0, max_value=1.0,
                value=float(cfg["min_ivp"]), step=0.01, format="%.2f",
                key="settings_min_ivp",
            )
            col_dte1, col_dte2 = st.columns(2)
            with col_dte1:
                cfg["min_dte"] = st.number_input(
                    "Min DTE", min_value=1, max_value=90,
                    value=int(cfg["min_dte"]), step=1, key="settings_min_dte",
                )
            with col_dte2:
                cfg["max_dte"] = st.number_input(
                    "Max DTE", min_value=1, max_value=365,
                    value=int(cfg["max_dte"]), step=1, key="settings_max_dte",
                )
            cfg["slippage_factor"] = st.number_input(
                "Slippage Factor (0.5–1.0)", min_value=0.5, max_value=1.0,
                value=float(cfg["slippage_factor"]), step=0.01, format="%.2f",
                key="settings_slippage",
            )

        save_core = st.form_submit_button("Save Core Settings", type="primary")

    if save_core:
        st.session_state["config"] = cfg
        save_config(cfg)
        st.success("Core settings saved to config.json.")

    st.divider()

    # === Section 2: Active Universe Tiers ===
    st.header("Active Universe Tiers")
    st.caption(
        "Deactivated tiers are excluded from Stage 1 scanning. "
        "Changes take effect on the next scan."
    )

    current_active = cfg.get("active_tiers", ALL_TIERS)
    new_active = st.multiselect(
        "Active Tiers",
        options=ALL_TIERS,
        default=[t for t in current_active if t in ALL_TIERS],
        format_func=lambda t: f"{t} — {TIER_DESCRIPTIONS.get(t, '')}",
        key="settings_active_tiers",
    )
    if st.button("Save Active Tiers", key="btn_save_tiers"):
        cfg["active_tiers"] = new_active
        st.session_state["config"] = cfg
        save_config(cfg)
        st.success(f"Active tiers updated: {', '.join(new_active)}")

    st.divider()

    # === Section 3: Universe Ticker Management ===
    st.header("Universe Ticker Management")
    st.caption(
        "Add or remove custom tickers from any tier. "
        "Changes are saved to universe/tickers.json and take effect on next app restart."
    )

    universe = _load_universe()

    tier_sel = st.selectbox(
        "Select Tier to Edit",
        options=ALL_TIERS,
        format_func=lambda t: f"{t} — {TIER_DESCRIPTIONS.get(t, '')}",
        key="settings_tier_sel",
    )

    tickers_in_tier = universe.get(tier_sel, [])
    st.write(f"**{len(tickers_in_tier)} tickers** in Tier {tier_sel}")
    if tickers_in_tier:
        st.code(", ".join(sorted(tickers_in_tier)[:50]) +
                ("..." if len(tickers_in_tier) > 50 else ""), language=None)

    col_add, col_rem = st.columns(2)
    with col_add:
        new_ticker = st.text_input("Add ticker to this tier", key="settings_add_ticker").strip().upper()
        if st.button("Add Ticker", key="btn_add_ticker") and new_ticker:
            if new_ticker not in tickers_in_tier:
                tickers_in_tier.append(new_ticker)
                universe[tier_sel] = tickers_in_tier
                _save_universe(universe)
                st.success(f"Added {new_ticker} to Tier {tier_sel}.")
            else:
                st.info(f"{new_ticker} already in Tier {tier_sel}.")

    with col_rem:
        rem_ticker = st.text_input("Remove ticker from this tier", key="settings_rem_ticker").strip().upper()
        if st.button("Remove Ticker", key="btn_rem_ticker") and rem_ticker:
            if rem_ticker in tickers_in_tier:
                tickers_in_tier.remove(rem_ticker)
                universe[tier_sel] = tickers_in_tier
                _save_universe(universe)
                st.success(f"Removed {rem_ticker} from Tier {tier_sel}.")
            else:
                st.warning(f"{rem_ticker} not found in Tier {tier_sel}.")

    st.divider()

    # === Section 3b: Risk Management (Circuit Breaker) ===
    st.header("Risk Management")
    st.caption(
        "Set drawdown thresholds for the portfolio circuit breaker. "
        "When the portfolio NAV drops below these levels, position sizing is reduced automatically."
    )

    with st.form("settings_risk_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Soft Limit")
            st.caption("Position sizes reduced 50% when drawdown exceeds this level.")
            cfg["cb_soft_limit"] = st.number_input(
                "Soft Limit Drawdown (%)",
                min_value=1.0, max_value=50.0,
                value=float(cfg.get("cb_soft_limit", 8.0)),
                step=0.5, format="%.1f",
                key="settings_cb_soft",
                help="When portfolio NAV drops this % below peak, position sizing is halved.",
            )
        with col2:
            st.subheader("Hard Limit")
            st.caption("All new positions blocked when drawdown exceeds this level.")
            cfg["cb_hard_limit"] = st.number_input(
                "Hard Limit Drawdown (%)",
                min_value=1.0, max_value=100.0,
                value=float(cfg.get("cb_hard_limit", 15.0)),
                step=0.5, format="%.1f",
                key="settings_cb_hard",
                help="When portfolio NAV drops this % below peak, no new trades are permitted.",
            )

        save_risk = st.form_submit_button("Save Risk Settings", type="primary")

    if save_risk:
        if cfg["cb_soft_limit"] >= cfg["cb_hard_limit"]:
            st.error("Soft limit must be less than hard limit.")
        else:
            st.session_state["config"] = cfg
            save_config(cfg)
            st.success(
                f"Risk settings saved: soft limit {cfg['cb_soft_limit']:.1f}%, "
                f"hard limit {cfg['cb_hard_limit']:.1f}%."
            )

    st.divider()

    # === Section 4: Schwab Connection Status ===
    st.header("Schwab Connection")
    has_creds, token_valid, status_msg = _schwab_status()
    if has_creds and token_valid:
        st.success(status_msg)
    elif has_creds:
        st.warning(status_msg)
    else:
        st.error(status_msg)
        st.markdown(
            "**Setup instructions:**\n"
            "1. Create a Schwab Developer account at developer.schwab.com\n"
            "2. Create an app with Market Data API scope\n"
            "3. Set environment variables: `SCHWAB_APP_KEY` and `SCHWAB_APP_SECRET`\n"
            "4. On first run, the app will open a browser for OAuth authorization\n"
        )
