"""
ui/pages/backtest.py — Backtesting page for signal validation.

Allows users to run historical backtests on any ticker or the full universe
to validate VRP signal quality before committing real capital.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go


def render_backtest() -> None:
    """Render the Backtesting page."""
    st.title("Signal Backtester")
    st.caption("Validate VRP signal quality using historical data. Results are approximate (uses OHLCV-derived IV proxy, not live options chains).")

    st.info(
        "The backtester simulates weekly entries when IVP > 40% and VRP > 0, selling a "
        "30 DTE ~5% OTM put. This validates whether the signal would have been profitable historically.",
        icon="ℹ️",
    )

    tab1, tab2 = st.tabs(["Single Ticker", "Batch Test"])

    with tab1:
        _render_single_backtest()

    with tab2:
        _render_batch_backtest()


def _render_single_backtest() -> None:
    col1, col2 = st.columns([3, 1])
    with col1:
        ticker = st.text_input("Ticker", placeholder="e.g. SPY, AAPL", key="bt_ticker")
    with col2:
        lookback = st.selectbox(
            "Lookback", [6, 12, 24], index=1,
            format_func=lambda x: f"{x} months", key="bt_lookback",
        )

    if st.button("Run Backtest", type="primary", key="btn_run_bt") and ticker:
        with st.spinner(f"Running backtest for {ticker.upper()}..."):
            try:
                from backtest.engine import run_backtest
                result = run_backtest(ticker.upper(), lookback_months=lookback)

                if result is None or not result.trades:
                    st.warning(
                        f"Insufficient data or no signal opportunities for "
                        f"{ticker.upper()} in the selected period."
                    )
                    return

                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Win Rate", f"{result.win_rate:.0%}")
                col2.metric("Avg P&L", f"{result.avg_pnl_pct:.0%} of max profit")
                col3.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
                col4.metric("Trades Tested", result.total_trades)

                if result.win_rate >= 0.65:
                    st.success(
                        f"Strong historical signal — {result.win_rate:.0%} win rate "
                        f"over {result.total_trades} simulated trades."
                    )
                elif result.win_rate >= 0.50:
                    st.warning(
                        f"Moderate historical signal — {result.win_rate:.0%} win rate. "
                        "Confirm with live data."
                    )
                else:
                    st.error(
                        f"Weak historical signal — only {result.win_rate:.0%} win rate. "
                        "Proceed with caution."
                    )

                # Trade history chart
                trades_df = pd.DataFrame([
                    {
                        "Date": t.entry_date,
                        "Score": t.signal_score,
                        "P&L %": t.actual_pnl_pct * 100,
                        "Win": "✓" if t.win else "✗",
                    }
                    for t in result.trades
                ])

                fig = go.Figure()
                wins = trades_df[trades_df["Win"] == "✓"]
                losses = trades_df[trades_df["Win"] == "✗"]

                if not wins.empty:
                    fig.add_trace(go.Scatter(
                        x=wins["Date"], y=wins["P&L %"], mode="markers",
                        marker=dict(color="green", size=8), name="Win",
                    ))
                if not losses.empty:
                    fig.add_trace(go.Scatter(
                        x=losses["Date"], y=losses["P&L %"], mode="markers",
                        marker=dict(color="red", size=8), name="Loss",
                    ))

                fig.add_hline(y=0, line_color="gray")
                fig.update_layout(
                    title=f"{ticker.upper()} Backtest — P&L per Trade",
                    xaxis_title="Entry Date",
                    yaxis_title="P&L (% of max profit)",
                    template="plotly_dark",
                    height=350,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Trade table
                with st.expander("Trade Details"):
                    st.dataframe(trades_df, use_container_width=True)

            except Exception as e:
                st.error(f"Backtest error: {e}")


def _render_batch_backtest() -> None:
    st.markdown("Run backtests on multiple tickers from your universe.")

    col1, col2 = st.columns(2)
    with col1:
        lookback = st.selectbox(
            "Lookback Period", [6, 12], index=1,
            format_func=lambda x: f"{x} months", key="bt_batch_lookback",
        )
    with col2:
        max_tickers = st.number_input(
            "Max Tickers to Test", min_value=5, max_value=50, value=20, key="bt_max",
        )

    if st.button("Run Batch Backtest", type="primary", key="btn_batch_bt"):
        try:
            from universe.loader import load_universe
            from backtest.simulator import run_portfolio_backtest, get_backtest_summary

            universe = load_universe()
            # Focus on Tier 1A-2 for batch test (most liquid)
            liquid_tickers = [
                sym for sym, info in universe.items()
                if str(info.tier) in ("1A", "1B", "2")
            ][:max_tickers]

            if not liquid_tickers:
                st.warning("No liquid tickers found in universe. Add tickers to Tiers 1A, 1B, or 2 in Settings.")
                return

            progress = st.progress(0)
            status = st.empty()

            def update_progress(i: int, total: int) -> None:
                progress.progress(i / total)
                status.text(f"Testing ticker {i + 1}/{total}...")

            results = run_portfolio_backtest(liquid_tickers, lookback, update_progress)
            progress.progress(1.0)
            status.text("Complete!")

            if not results:
                st.warning("No results. Try a longer lookback or more tickers.")
                return

            summary = get_backtest_summary(results)

            col1, col2, col3 = st.columns(3)
            col1.metric("Tickers Tested", summary["tickers_tested"])
            col2.metric("Avg Win Rate", f"{summary['avg_win_rate']:.0%}")
            col3.metric("Avg Sharpe", f"{summary['avg_sharpe']:.2f}")

            # Results table
            rows = []
            for ticker, r in sorted(results.items(), key=lambda x: x[1].sharpe_ratio, reverse=True):
                rows.append({
                    "Ticker": ticker,
                    "Win Rate": f"{r.win_rate:.0%}",
                    "Avg P&L%": f"{r.avg_pnl_pct:.0%}",
                    "Sharpe": f"{r.sharpe_ratio:.2f}",
                    "Trades": r.total_trades,
                    "Max DD": f"{r.max_drawdown_pct:.1%}",
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Batch backtest error: {e}")
