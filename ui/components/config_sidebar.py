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
            help="Your total account size. Used to calculate the maximum dollar amount allowed per position.",
        )
        cfg["max_position_pct"] = st.slider(
            "Max Position % of Portfolio",
            min_value=1, max_value=20,
            value=max(1, int(round(float(cfg["max_position_pct"]) * 100))),
            step=1,
            format="%d%%",
            key="cfg_max_position_pct",
            help="The largest slice of your portfolio that can go into a single trade. E.g. 5% means no more than $5,000 on a $100k account.",
        ) / 100
        cfg["max_positions"] = int(st.number_input(
            "Max Simultaneous Positions",
            min_value=1, max_value=50,
            value=int(cfg["max_positions"]), step=1,
            key="cfg_max_positions",
            help="How many open trades you can hold at once. Keeps you from putting too much risk into the market at the same time.",
        ))

        # --- Screening Thresholds ---
        st.subheader("Screening Thresholds")
        cfg["min_vrp_score"] = st.slider(
            "Min VRP Composite Score",
            min_value=0.0, max_value=100.0,
            value=float(cfg["min_vrp_score"]), step=1.0,
            key="cfg_min_vrp_score",
            help=(
                "Overall attractiveness score (0–100) for selling options premium on a stock. "
                "Higher = better opportunity. Stocks below this threshold are filtered out.\n\n"
                "How it's calculated: 12 signals are blended using a weighted average —\n"
                "• VRP size vs. history (18%) — how big the current premium is\n"
                "• VRP consistency (12%) — how reliably it's been positive lately\n"
                "• VRP statistical significance (12%) — is it a real edge or noise?\n"
                "• Expected move ratio (10%) — does implied vol overshoot reality?\n"
                "• Excess VRP (10%) — premium above what the market alone explains\n"
                "• IV Percentile (8%) — are options expensive vs. the past year?\n"
                "• Put-call skew (8%) — how much traders are paying for downside protection\n"
                "• Term structure (7%), jump cleanliness (5%), put/call ratio (4%), dealer positioning (3%), IV stability (3%)\n\n"
                "Penalties reduce the score if earnings fall inside the expiration window (−30%), "
                "if the stock has frequent price gaps (up to −20%), or if IV itself is erratic (up to −25%, or zero if extreme)."
            ),
        )
        cfg["min_ivp"] = st.slider(
            "Min IVP Percentile",
            min_value=0.0, max_value=1.0,
            value=float(cfg["min_ivp"]), step=0.01,
            format="%.2f",
            key="cfg_min_ivp",
            help="IV Percentile — how expensive options are right now vs. the past year. 0.60 means current IV is higher than 60% of all past readings, so options are relatively pricey to sell.",
        )
        col1, col2 = st.columns(2)
        with col1:
            cfg["min_dte"] = int(st.number_input(
                "Min DTE", min_value=1, max_value=120,
                value=int(cfg["min_dte"]), step=1, key="cfg_min_dte",
                help="Minimum days until expiration. Options closer to expiry than this are skipped — very short-dated options carry outsized risk from rapid price swings.",
            ))
        with col2:
            cfg["max_dte"] = int(st.number_input(
                "Max DTE", min_value=1, max_value=365,
                value=int(cfg["max_dte"]), step=1, key="cfg_max_dte",
                help="Maximum days until expiration. The 30–60 day window is the sweet spot where time decay accelerates without the option being too far out.",
            ))

        # --- Slippage ---
        st.subheader("Slippage")
        cfg["slippage_factor"] = st.slider(
            "Slippage Factor (0=worst, 1=mid)",
            min_value=0.5, max_value=1.0,
            value=float(cfg["slippage_factor"]), step=0.01,
            format="%.2f",
            key="cfg_slippage_factor",
            help="How much of the bid-ask spread you expect to capture when filling an order. 1.0 = mid price (optimistic), 0.5 = at the bid (conservative). 0.75 is a realistic default for liquid options.",
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
