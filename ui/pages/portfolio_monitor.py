"""Portfolio Monitor page — correlation matrix, CVaR, short-vol exposure."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from ui.components.regime_banner import render_regime_banner
from portfolio.db import save_position, load_positions, delete_position, Position


# --- Risk Computation ---

def _fetch_returns(tickers: list[str], lookback_days: int = 90) -> pd.DataFrame:
    """Fetch OHLCV and compute daily log-returns for the given tickers.
    Returns DataFrame indexed by date with one column per ticker.
    Uses yfinance directly (data is cached by yfinance internally).
    """
    if not tickers:
        return pd.DataFrame()
    try:
        raw = yf.download(tickers, period=f"{lookback_days}d",
                          auto_adjust=True, progress=False)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])
        returns = np.log(close / close.shift(1)).dropna()
        return returns
    except Exception as exc:
        st.warning(f"Could not fetch returns: {exc}")
        return pd.DataFrame()


def _compute_correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """60-day rolling pairwise correlation using pandas .tail(60).corr()."""
    if returns.empty or returns.shape[1] < 2:
        return pd.DataFrame()
    # Use last 60 trading days
    window_returns = returns.tail(60)
    corr = window_returns.corr()
    return corr


def _compute_cvar_monte_carlo(
    returns: pd.DataFrame,
    weights: np.ndarray,
    n_samples: int = 10_000,
    confidence: float = 0.99,
    portfolio_value: float = 100_000.0,
) -> float:
    """Compute 1d 99% CVaR via Monte Carlo with multivariate normal.

    Uses 60-day historical covariance matrix. Returns CVaR in dollars (positive = loss).
    """
    if returns.empty or len(weights) != returns.shape[1]:
        return 0.0
    window = returns.tail(60)
    mu = window.mean().values       # daily mean returns
    cov = window.cov().values       # 60-day covariance
    # Monte Carlo: 10,000 samples from multivariate normal
    rng = np.random.default_rng(42)
    sim_returns = rng.multivariate_normal(mu, cov, size=n_samples)  # (10000, n_assets)
    portfolio_returns = sim_returns @ weights                         # (10000,)
    portfolio_pnl = portfolio_returns * portfolio_value               # dollar P&L
    # VaR at 99th percentile (worst 1%)
    var_threshold = np.percentile(portfolio_pnl, (1 - confidence) * 100)
    # CVaR = mean of losses beyond VaR
    cvar = -portfolio_pnl[portfolio_pnl <= var_threshold].mean()
    return float(cvar)


def _tail_hedge_recommendation(
    short_vol_pct: float,
    cvar: float,
    portfolio_value: float,
    corr_matrix: pd.DataFrame,
) -> str:
    """Generate a plain-English tail hedge recommendation."""
    high_corr_pairs = []
    if not corr_matrix.empty:
        tickers = corr_matrix.columns.tolist()
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                rho = corr_matrix.iloc[i, j]
                if rho > 0.70:
                    high_corr_pairs.append((tickers[i], tickers[j], rho))

    cvar_pct = cvar / portfolio_value * 100 if portfolio_value else 0.0
    parts = []

    if short_vol_pct > 0.60:
        parts.append(
            f"Short-vol exposure is elevated at {short_vol_pct:.0%}. "
            "Consider adding long-vol positions (e.g., VIX calls, UVXY calls) to hedge."
        )
    if cvar_pct > 3.0:
        parts.append(
            f"1d 99% CVaR is {cvar_pct:.1f}% of portfolio (${cvar:,.0f}). "
            "Consider reducing position sizes or adding protective puts on the largest positions."
        )
    if high_corr_pairs:
        pair_strs = ", ".join(f"{a}/{b} (rho={rho:.2f})" for a, b, rho in high_corr_pairs[:3])
        parts.append(
            f"High correlation detected: {pair_strs}. "
            "These positions move together — consider treating as a single exposure."
        )
    if not parts:
        return "Portfolio risk appears manageable. No immediate hedging action required."
    return " ".join(parts)


# --- A2: Position Management Alerts ---

def _compute_position_alert(pos: Position, current_prices: dict) -> dict:
    """Compute management alert for a position using BSM approximation.

    Returns dict with: alert_level, alert_text, action, pnl_pct
    """
    try:
        from datetime import datetime, date
        from scipy.stats import norm

        ticker = pos.ticker
        short_strike = float(pos.short_strike)
        entry_credit = float(pos.net_credit)  # Position uses net_credit, not entry_credit
        expiration = pos.expiry               # Position uses expiry, not expiration_date
        contracts = int(pos.quantity)         # Position uses quantity, not contracts

        if not expiration:
            return {
                "alert_level": "info",
                "alert_text": "No expiration date set",
                "action": "Update position",
                "pnl_pct": 0,
            }

        today = date.today()
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        dte = max((exp_date - today).days, 0)

        # Current underlying price (use entry_price if no live price available)
        current_price = current_prices.get(
            ticker, pos.entry_price if pos.entry_price else short_strike / 0.95
        )

        # BSM put approximation for current option value
        if dte > 0:
            T = dte / 252
            sigma = 0.25  # assume 25% IV
            r = 0.05
            d1 = (np.log(current_price / short_strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
            d2 = d1 - sigma * np.sqrt(T)
            current_option_value = (
                short_strike * np.exp(-r * T) * norm.cdf(-d2)
                - current_price * norm.cdf(-d1)
            )
            current_option_value = max(current_option_value, 0)
        else:
            current_option_value = max(short_strike - current_price, 0)

        current_pnl = (entry_credit - current_option_value) * 100 * contracts
        max_profit = entry_credit * 100 * contracts
        pnl_pct = current_pnl / max_profit if max_profit > 0 else 0

        # Alert logic
        breakeven = short_strike - entry_credit
        loss_pct = -current_pnl / max_profit if current_pnl < 0 else 0

        if pnl_pct >= 0.50:
            return {
                "alert_level": "success",
                "alert_text": f"Take Profit — {pnl_pct:.0%} of max profit reached",
                "action": "Close position now — eliminate remaining risk",
                "pnl_pct": pnl_pct,
            }
        elif dte <= 21:
            return {
                "alert_level": "warning",
                "alert_text": f"Time to Roll — only {dte} DTE remaining",
                "action": f"Roll forward to avoid gamma risk near expiration",
                "pnl_pct": pnl_pct,
            }
        elif current_price <= breakeven * 1.03:
            return {
                "alert_level": "warning",
                "alert_text": f"Delta Breach — underlying near short strike",
                "action": (
                    f"Manage position: underlying ${current_price:.2f} "
                    f"near breakeven ${breakeven:.2f}"
                ),
                "pnl_pct": pnl_pct,
            }
        elif loss_pct >= 2.0:
            return {
                "alert_level": "error",
                "alert_text": f"Hard Stop Hit — loss = {loss_pct:.1f}x credit",
                "action": "Close immediately — 2x credit stop loss reached",
                "pnl_pct": pnl_pct,
            }
        else:
            return {
                "alert_level": "info",
                "alert_text": f"Holding — {pnl_pct:.0%} profit, {dte} DTE remaining",
                "action": "Continue holding — theta decay working",
                "pnl_pct": pnl_pct,
            }
    except Exception as e:
        return {
            "alert_level": "info",
            "alert_text": "Unable to compute alert",
            "action": str(e),
            "pnl_pct": 0,
        }


@st.cache_data(ttl=900)
def _get_current_prices(tickers: tuple) -> dict:
    """Fetch current prices via yfinance (cached 15 min)."""
    try:
        prices = {}
        for t in tickers:
            hist = yf.download(t, period="1d", auto_adjust=True, progress=False)
            if not hist.empty:
                prices[t] = float(hist["Close"].iloc[-1])
        return prices
    except Exception:
        return {}


# --- B5: Circuit Breaker ---

def _render_circuit_breaker_status(portfolio_value: float) -> None:
    """Show portfolio drawdown status and circuit breaker."""
    try:
        from portfolio.risk import get_portfolio_drawdown
        dd = get_portfolio_drawdown(portfolio_value)

        st.subheader("Portfolio Health")
        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Current Drawdown", f"{dd['drawdown_pct']:.1%}",
            delta=f"Peak: ${dd['peak_nav']:,.0f}", delta_color="inverse",
        )
        col2.metric(
            "Circuit Breaker",
            "HARD STOP" if dd["hard_limit_hit"] else (
                "SOFT LIMIT" if dd["soft_limit_hit"] else "OK"
            ),
            delta_color="inverse" if dd["hard_limit_hit"] else "normal",
        )
        col3.metric(
            "Sizing Reduction",
            "100% (blocked)" if dd["hard_limit_hit"] else (
                "50%" if dd["soft_limit_hit"] else "None"
            ),
        )

        if dd["hard_limit_hit"]:
            st.error("HARD STOP: Drawdown >=15% — no new positions until recovery or manual override.")
            if st.checkbox(
                "Override circuit breaker (I understand the risks)",
                key="cb_override",
            ):
                st.session_state["circuit_breaker_override"] = True
                st.warning("Override active. Proceed with caution.")
        elif dd["soft_limit_hit"]:
            st.warning("SOFT LIMIT: Drawdown >=8% — position sizes automatically reduced by 50%.")
    except Exception:
        pass  # Never block the portfolio monitor


# --- Streamlit Page ---

def render_portfolio_monitor() -> None:
    """Render the Portfolio Monitor page."""
    render_regime_banner()
    st.title("Portfolio Monitor")

    portfolio_value = st.session_state.get("config", {}).get("portfolio_value", 100_000.0)

    # --- B5: Circuit Breaker Status (top of page) ---
    _render_circuit_breaker_status(portfolio_value)

    st.divider()

    # --- Tabs: Real Positions | Paper Trading (B7) ---
    real_tab, paper_tab = st.tabs(["Real Positions", "Paper Trading"])

    with real_tab:
        _render_real_positions(portfolio_value)

    with paper_tab:
        _render_paper_trading()


def _render_real_positions(portfolio_value: float) -> None:
    """Render the real positions tab including alerts and risk analytics."""

    # --- Position Entry Form ---
    st.header("Open Positions")
    with st.expander("Add Position", expanded=False):
        with st.form("add_position_form", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                p_ticker    = st.text_input("Ticker").strip().upper()
                p_structure = st.selectbox(
                    "Structure",
                    ["csp", "spread", "collar", "covered_call", "condor", "strangle"],
                )
            with fc2:
                p_expiry        = st.date_input("Expiry")
                p_short_strike  = st.number_input("Short Strike", min_value=0.0, step=0.5)
            with fc3:
                p_long_strike = st.number_input("Long Strike (0 if N/A)", min_value=0.0, step=0.5)
                p_credit      = st.number_input("Net Credit ($/share)", min_value=0.0, step=0.01)
                p_qty         = st.number_input("Contracts", min_value=1, step=1, value=1)
            p_notes = st.text_input("Notes (optional)")
            is_short_vol = st.checkbox("Short-vol position?", value=True)
            submitted = st.form_submit_button("Add Position")

        if submitted and p_ticker:
            pos = Position(
                id=None,
                ticker=p_ticker,
                structure=p_structure,
                expiry=p_expiry.isoformat(),
                short_strike=p_short_strike,
                long_strike=p_long_strike if p_long_strike > 0 else None,
                net_credit=p_credit,
                quantity=int(p_qty),
                is_short_vol=is_short_vol,
                notes=p_notes,
            )
            save_position(pos)
            st.success(f"Position added: {p_ticker} {p_structure}")
            st.rerun()

    # --- Load Positions ---
    positions = load_positions()

    if not positions:
        st.info("No positions entered yet. Use 'Add Position' above.")
        return

    # Display position table with delete buttons
    pos_data = []
    for p in positions:
        pos_data.append({
            "ID": p.id,
            "Ticker": p.ticker,
            "Structure": p.structure,
            "Expiry": p.expiry,
            "Short Strike": p.short_strike,
            "Long Strike": p.long_strike or "N/A",
            "Credit": f"${p.net_credit:.2f}",
            "Qty": p.quantity,
            "Short Vol": "Yes" if p.is_short_vol else "No",
        })

    pos_df = pd.DataFrame(pos_data)
    st.dataframe(pos_df.drop(columns=["ID"]), use_container_width=True, hide_index=True)

    # Delete controls
    del_id = st.selectbox(
        "Delete position by ID",
        options=[p.id for p in positions],
        format_func=lambda i: f"ID {i}: {next((p.ticker for p in positions if p.id == i), '?')}",
        key="delete_position_select",
    )
    if st.button("Delete Selected Position", key="btn_delete_pos"):
        delete_position(del_id)
        st.success("Position deleted.")
        st.rerun()

    st.divider()

    # --- A2: Position Management Alerts ---
    st.subheader("Position Management Alerts")

    alert_tickers = tuple(set(p.ticker for p in positions if p.ticker))
    current_prices = _get_current_prices(alert_tickers)

    for pos in positions:
        alert = _compute_position_alert(pos, current_prices)
        ticker = pos.ticker
        structure = pos.structure.upper()
        strike = pos.short_strike
        exp = pos.expiry

        with st.expander(
            f"{ticker} {structure} ${strike} exp {exp} — {alert['alert_text']}",
            expanded=(alert["alert_level"] != "info"),
        ):
            if alert["alert_level"] == "success":
                st.success(alert["action"])
            elif alert["alert_level"] == "warning":
                st.warning(alert["action"])
            elif alert["alert_level"] == "error":
                st.error(alert["action"])
            else:
                st.info(alert["action"])

            pnl_pct = alert["pnl_pct"]
            st.progress(
                max(0.0, min(1.0, pnl_pct)),
                text=f"P&L: {pnl_pct:.0%} of max profit",
            )

    st.divider()

    # --- Risk Analytics ---
    tickers = list({p.ticker for p in positions})

    st.header("Risk Analytics")
    with st.spinner("Fetching returns and computing risk metrics..."):
        returns = _fetch_returns(tickers, lookback_days=90)

    if returns.empty or returns.shape[1] < 1:
        st.warning("Could not fetch return data for the entered tickers.")
        return

    # Reindex to only tickers we have returns for
    available_tickers = [t for t in tickers if t in returns.columns]
    returns = returns[available_tickers]

    # --- Portfolio Summary Metrics ---
    total_qty = sum(p.quantity for p in positions)
    short_vol_qty = sum(p.quantity for p in positions if p.is_short_vol)
    short_vol_pct = short_vol_qty / total_qty if total_qty else 0.0

    # Equal-weight by contract count across tickers
    ticker_weights = {}
    for p in positions:
        ticker_weights[p.ticker] = ticker_weights.get(p.ticker, 0) + p.quantity
    total_w = sum(ticker_weights.values())
    weights = np.array([
        ticker_weights.get(t, 0) / total_w for t in available_tickers
    ])

    # CVaR
    cvar = _compute_cvar_monte_carlo(returns, weights,
                                      n_samples=10_000, confidence=0.99,
                                      portfolio_value=portfolio_value)

    # Correlation matrix
    corr = _compute_correlation_matrix(returns)

    # --- Summary Metrics Row ---
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Positions", len(positions))
        st.metric("Unique Tickers", len(available_tickers))
    with col2:
        st.metric("Short-Vol Exposure", f"{short_vol_pct:.0%}")
        st.metric("Short-Vol Contracts", short_vol_qty)
    with col3:
        st.metric("1d 99% CVaR", f"${cvar:,.0f}")
        st.metric("CVaR % of Portfolio", f"{cvar / portfolio_value * 100:.2f}%")

    # --- Correlation Matrix Heatmap ---
    if not corr.empty and len(available_tickers) >= 2:
        st.subheader("60-Day Pairwise Correlation Matrix")

        # Flag pairs > 0.70
        high_corr_pairs = []
        for i in range(len(available_tickers)):
            for j in range(i + 1, len(available_tickers)):
                if i < corr.shape[0] and j < corr.shape[1]:
                    rho = corr.iloc[i, j]
                    if abs(rho) > 0.70:
                        high_corr_pairs.append(
                            f"{available_tickers[i]} / {available_tickers[j]}: rho = {rho:.2f}"
                        )

        if high_corr_pairs:
            st.warning("High-correlation pairs (rho > 0.70): " + ", ".join(high_corr_pairs))

        # Heatmap
        corr_vals = corr.values
        fig_corr = go.Figure(go.Heatmap(
            z=corr_vals,
            x=available_tickers,
            y=available_tickers,
            colorscale="RdYlGn",
            zmin=-1, zmax=1,
            text=[[f"{corr_vals[i][j]:.2f}" for j in range(len(available_tickers))]
                  for i in range(len(available_tickers))],
            texttemplate="%{text}",
            showscale=True,
        ))
        fig_corr.update_layout(
            title="60-Day Pairwise Correlation (Daily Log-Returns)",
            height=max(300, len(available_tickers) * 60),
            margin=dict(t=50, b=30, l=80, r=20),
        )
        st.plotly_chart(fig_corr, use_container_width=True)

    # --- Tail Hedge Recommendation ---
    st.subheader("Tail Hedge Recommendation")
    rec = _tail_hedge_recommendation(short_vol_pct, cvar, portfolio_value,
                                      corr if not corr.empty else pd.DataFrame())
    st.info(rec)


def _render_paper_trading() -> None:
    """Render the Paper Trading tab (B7)."""
    st.info(
        "Paper trading lets you practice strategies without real money. "
        "Track hypothetical positions and review performance before going live."
    )

    # Add paper position form
    with st.form("add_paper_position"):
        st.subheader("Add Paper Trade")
        col1, col2 = st.columns(2)
        with col1:
            paper_ticker = st.text_input("Ticker", placeholder="e.g. SPY")
            paper_structure = st.selectbox(
                "Structure", ["csp", "spread", "collar", "iron_condor"],
            )
            paper_strike = st.number_input("Short Strike", min_value=0.0, value=400.0)
            paper_credit = st.number_input(
                "Net Credit (per share)", min_value=0.0, value=1.0, step=0.05,
            )
        with col2:
            paper_expiry = st.date_input("Expiration Date")
            paper_contracts = st.number_input("Contracts", min_value=1, value=1)
            paper_entry_price = st.number_input(
                "Underlying Price at Entry", min_value=0.0, value=400.0,
            )
            paper_long_strike = st.number_input(
                "Long Strike (spread only)", min_value=0.0, value=0.0,
            )

        if st.form_submit_button("Add Paper Trade"):
            try:
                from portfolio.db import save_paper_position
                pos = Position(
                    id=None,
                    ticker=paper_ticker.strip().upper(),
                    structure=paper_structure,
                    expiry=paper_expiry.isoformat(),
                    short_strike=paper_strike,
                    long_strike=paper_long_strike if paper_long_strike > 0 else None,
                    net_credit=paper_credit,
                    quantity=int(paper_contracts),
                    is_short_vol=True,
                    notes="",
                    entry_price=paper_entry_price,
                    sector="Unknown",
                    paper=True,
                )
                save_paper_position(pos)
                st.success(f"Paper trade added: {paper_ticker.strip().upper()} {paper_structure}")
                st.rerun()
            except Exception as e:
                st.error(f"Error adding paper trade: {e}")

    # Show paper positions
    try:
        from portfolio.db import load_paper_positions, delete_paper_position
        paper_positions = load_paper_positions()
        if paper_positions:
            st.subheader("Active Paper Trades")
            for p in paper_positions:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(
                        f"{p.get('ticker')} {p.get('structure', '').upper()} "
                        f"${p.get('short_strike', 0):.0f} exp {p.get('expiration_date', '')} "
                        f"— Credit: ${p.get('entry_credit', 0):.2f}"
                    )
                with col2:
                    if st.button("Remove", key=f"del_paper_{p.get('id')}"):
                        delete_paper_position(p["id"])
                        st.rerun()
        else:
            st.info("No paper trades yet. Add one above.")
    except Exception as e:
        st.warning(f"Paper trading not available: {e}")
