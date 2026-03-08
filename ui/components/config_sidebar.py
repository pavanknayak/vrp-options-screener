"""Configuration sidebar — persisted to config.json, loaded into st.session_state['config']."""
import json
import os

import streamlit as st

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")

DEFAULT_CONFIG = {
    # Portfolio
    "portfolio_value": 100_000.0,
    "max_position_pct": 0.05,       # max 5% of portfolio per position
    "max_positions": 10,
    # Screening thresholds
    "min_vrp_score": 50.0,          # minimum composite VRP score 0–100
    "min_ivp": 0.60,                # minimum IVP percentile (PRD: 60th)
    "min_dte": 21,
    "max_dte": 60,
    # Slippage factors
    "slippage_factor": 0.75,        # bid-ask × this factor per leg
    # Active universe tiers (list of strings: "1A","1B",...,"7")
    "active_tiers": ["1A","1B","1C","1D","1E","1F","1G","1H","1I","2","3","4","5","6","7"],
    # Schwab connection (read-only display)
    "schwab_app_key_set": False,
    # Risk-free rate (updated from FRED on startup)
    "risk_free_rate": 0.05,
}


def load_config() -> dict:
    """Load config from config.json; fall back to DEFAULT_CONFIG if missing or corrupt.

    Always merges with DEFAULT_CONFIG so new keys added in code are present even
    when reading an older config.json from disk.
    """
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    """Persist config dict to config.json."""
    target = os.path.abspath(CONFIG_PATH)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        json.dump(cfg, f, indent=2)


def render_config_sidebar() -> dict:
    """Render the configuration sidebar and return the current config dict.

    Loads config from st.session_state['config'] (populated at app startup via load_config()).
    Writes changes back to st.session_state['config'] and persists to config.json on Save.
    Returns the current config dict.
    """
    if "config" not in st.session_state:
        st.session_state["config"] = load_config()

    cfg = st.session_state["config"]

    with st.sidebar:
        st.header("Configuration")

        # --- Portfolio ---
        st.subheader("Portfolio")
        cfg["portfolio_value"] = st.number_input(
            "Portfolio Value ($)",
            min_value=10_000.0, max_value=10_000_000.0,
            value=float(cfg["portfolio_value"]), step=5_000.0,
            key="cfg_portfolio_value",
        )
        cfg["max_position_pct"] = st.slider(
            "Max Position % of Portfolio",
            min_value=0.01, max_value=0.20,
            value=float(cfg["max_position_pct"]), step=0.01,
            format="%.0f%%",
            key="cfg_max_position_pct",
        )
        cfg["max_positions"] = int(st.number_input(
            "Max Simultaneous Positions",
            min_value=1, max_value=50,
            value=int(cfg["max_positions"]), step=1,
            key="cfg_max_positions",
        ))

        # --- Screening Thresholds ---
        st.subheader("Screening Thresholds")
        cfg["min_vrp_score"] = st.slider(
            "Min VRP Composite Score",
            min_value=0.0, max_value=100.0,
            value=float(cfg["min_vrp_score"]), step=1.0,
            key="cfg_min_vrp_score",
        )
        cfg["min_ivp"] = st.slider(
            "Min IVP Percentile",
            min_value=0.0, max_value=1.0,
            value=float(cfg["min_ivp"]), step=0.01,
            format="%.2f",
            key="cfg_min_ivp",
        )
        col1, col2 = st.columns(2)
        with col1:
            cfg["min_dte"] = int(st.number_input(
                "Min DTE", min_value=1, max_value=120,
                value=int(cfg["min_dte"]), step=1, key="cfg_min_dte",
            ))
        with col2:
            cfg["max_dte"] = int(st.number_input(
                "Max DTE", min_value=1, max_value=365,
                value=int(cfg["max_dte"]), step=1, key="cfg_max_dte",
            ))

        # --- Slippage ---
        st.subheader("Slippage")
        cfg["slippage_factor"] = st.slider(
            "Slippage Factor (0=worst, 1=mid)",
            min_value=0.5, max_value=1.0,
            value=float(cfg["slippage_factor"]), step=0.01,
            format="%.2f",
            key="cfg_slippage_factor",
        )

        # --- Universe Tiers ---
        st.subheader("Active Universe Tiers")
        all_tiers = ["1A","1B","1C","1D","1E","1F","1G","1H","1I","2","3","4","5","6","7"]
        cfg["active_tiers"] = st.multiselect(
            "Active Tiers",
            options=all_tiers,
            default=cfg.get("active_tiers", all_tiers),
            key="cfg_active_tiers",
        )

        # --- Schwab Status (read-only) ---
        st.subheader("Schwab Connection")
        schwab_key    = os.environ.get("SCHWAB_APP_KEY", "")
        schwab_secret = os.environ.get("SCHWAB_APP_SECRET", "")
        if schwab_key and schwab_secret:
            st.success("Schwab credentials detected in environment.")
        else:
            st.warning(
                "SCHWAB_APP_KEY and/or SCHWAB_APP_SECRET not set. "
                "Schwab data unavailable — Stage 2 scan will not run."
            )

        # --- Save ---
        if st.button("Save Configuration", key="cfg_save_btn", type="primary"):
            save_config(cfg)
            st.session_state["config"] = cfg
            st.success("Configuration saved.")

    return cfg
