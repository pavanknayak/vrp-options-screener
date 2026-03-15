"""Five Plotly chart builder functions for the Ticker Analysis page.

Each function accepts data directly from the recommendation result dict or sub-dicts
within it, and returns a plotly.graph_objects.Figure.
"""
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Optional


def chart_iv_term_structure(analytics_result: dict) -> go.Figure:
    """IV term structure: x = DTE, y = IV (annualized %).

    Data source: analytics_result['iv_surface'] — list of dicts with keys 'dte' and 'iv'.
    If iv_surface absent or empty, show a placeholder figure with 'No IV surface data' annotation.
    Adds a horizontal line at analytics_result.get('iv30', 0) labeled 'IV30'.
    """
    surface = analytics_result.get("iv_surface") or []
    fig = go.Figure()
    if surface:
        dtes = [pt["dte"] for pt in surface]
        ivs  = [pt["iv"] * 100 for pt in surface]
        fig.add_trace(go.Scatter(x=dtes, y=ivs, mode="lines+markers",
                                  name="IV", line=dict(color="#3498db", width=2)))
        iv30 = (analytics_result.get("iv30") or 0.0) * 100
        fig.add_hline(y=iv30, line_dash="dash", line_color="orange",
                      annotation_text=f"IV30 {iv30:.1f}%")
    else:
        fig.add_annotation(text="No IV surface data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_layout(title="IV Term Structure", xaxis_title="DTE", yaxis_title="IV (%)",
                      height=300, margin=dict(t=40, b=30, l=50, r=20))
    return fig


def chart_vrp_history(analytics_result: dict) -> go.Figure:
    """VRP history: x = date, y = VRP (annualized %).

    Data source: analytics_result['vrp_history'] — list of dicts with keys 'date' and 'vrp'.
    Plots VRP line with zero reference line. Shades positive VRP area green, negative red.
    """
    history = analytics_result.get("vrp_history") or []
    fig = go.Figure()
    if history:
        dates = [h["date"] for h in history]
        vrps  = [h["vrp"] * 100 for h in history]
        fig.add_trace(go.Scatter(x=dates, y=vrps, mode="lines", name="VRP",
                                  line=dict(color="#2ecc71", width=2),
                                  fill="tozeroy",
                                  fillcolor="rgba(46,204,113,0.15)"))
        fig.add_hline(y=0, line_color="white", line_dash="dash", line_width=1)
    else:
        fig.add_annotation(text="No VRP history data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_layout(title="VRP History (30d Rolling)", xaxis_title="Date",
                      yaxis_title="VRP (%)", height=300,
                      margin=dict(t=40, b=30, l=50, r=20))
    return fig


def chart_skew(analytics_result: dict) -> go.Figure:
    """Skew chart: x = delta, y = IV (annualized %).

    Data source: analytics_result['skew_data'] — list of dicts with keys 'delta' and 'iv'.
    Shows the put-wing smile at the 30d expiry. If absent, shows placeholder.
    """
    skew_data = analytics_result.get("skew_data") or []
    fig = go.Figure()
    if skew_data:
        deltas = [pt["delta"] for pt in skew_data]
        ivs    = [pt["iv"] * 100 for pt in skew_data]
        fig.add_trace(go.Scatter(x=deltas, y=ivs, mode="lines+markers",
                                  name="Skew", line=dict(color="#9b59b6", width=2)))
        skew_25d = (analytics_result.get("signals") or {}).get("skew_25d", 0.0)
        fig.add_annotation(text=f"25\u0394 skew: {skew_25d:.3f}", xref="paper", yref="paper",
                           x=0.02, y=0.95, showarrow=False)
    else:
        fig.add_annotation(text="No skew data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_layout(title="IV Skew (30d Expiry)", xaxis_title="Delta",
                      yaxis_title="IV (%)", height=300,
                      margin=dict(t=40, b=30, l=50, r=20))
    return fig


def chart_scenario_pnl(result: dict) -> go.Figure:
    """Scenario P&L bar chart: x = scenario label, y = P&L in dollars.

    Data source: result['scenarios'] — list of dicts with keys 'label', 'pnl', 'probability'.
    Colors: positive bars green, negative bars red.
    Adds probability labels above each bar.
    """
    scenarios = result.get("scenarios") or []
    fig = go.Figure()
    if scenarios:
        labels = [s["label"] for s in scenarios]
        pnls   = [s["pnl"] for s in scenarios]
        probs  = [s.get("probability", 0.25) for s in scenarios]
        colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in pnls]
        fig.add_trace(go.Bar(
            x=labels, y=pnls,
            marker_color=colors,
            text=[f"{prob:.0%}" for prob in probs],
            textposition="outside",
            name="P&L",
        ))
        ev = result.get("probability_weighted_ev") or 0.0
        fig.add_hline(y=0, line_color="white", line_dash="dash")
        fig.add_annotation(text=f"Prob-Weighted EV: ${ev:.2f}",
                           xref="paper", yref="paper", x=0.02, y=0.95, showarrow=False)
    else:
        fig.add_annotation(text="No scenario data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_layout(title="Scenario P&L", xaxis_title="Scenario",
                      yaxis_title="P&L ($)", height=300,
                      margin=dict(t=40, b=30, l=50, r=20))
    return fig


def chart_pnl_simulator(
    structure: str,
    spot: float,
    short_strike: float,
    long_strike: "float | None",
    net_credit: float,
    max_loss: float,
    expiration: str = "",
) -> go.Figure:
    """Interactive P&L chart for manual price exploration.

    Shows payoff diagram across a range of underlying prices.
    Color-coded: green (full profit), yellow (partial), red (loss), dark red (max loss).
    """
    # Price range: -50% to +30% of spot
    prices = np.linspace(spot * 0.50, spot * 1.30, 300)
    net_credit_contract = net_credit * 100
    max_loss_contract = max_loss  # already per-contract

    pnls = []
    for p in prices:
        if structure == "csp":
            if p >= short_strike:
                pnl = net_credit_contract
            else:
                pnl = (p - short_strike + net_credit) * 100
        elif structure in ("spread", "collar", "iron_condor"):
            raw = (p - short_strike + net_credit) * 100
            pnl = max(-max_loss_contract, min(net_credit_contract, raw))
        else:
            pnl = net_credit_contract
        pnls.append(pnl)

    pnls = np.array(pnls)

    # Breakeven and key levels
    breakeven = short_strike - net_credit
    net_credit_contract = net_credit * 100

    fig = go.Figure()

    # P&L line
    fig.add_trace(go.Scatter(
        x=prices, y=pnls,
        mode='lines',
        line=dict(color='white', width=2),
        fill='tozeroy',
        fillcolor='rgba(59, 130, 246, 0.15)',
        name='P&L',
        hovertemplate='Price: $%{x:.2f}<br>P&L: $%{y:.0f}<extra></extra>',
    ))

    # Key level lines
    fig.add_vline(x=spot, line_dash="dot", line_color="white",
                  annotation_text="Current", annotation_position="top")
    fig.add_vline(x=short_strike, line_dash="dash", line_color="orange",
                  annotation_text=f"Short Strike ${short_strike:.0f}",
                  annotation_position="top right")
    fig.add_vline(x=breakeven, line_dash="dash", line_color="red",
                  annotation_text=f"Breakeven ${breakeven:.2f}",
                  annotation_position="bottom right")
    fig.add_hline(y=0, line_color="gray", line_width=1)
    fig.add_hline(y=net_credit_contract, line_dash="dot", line_color="green",
                  annotation_text=f"Max Profit ${net_credit_contract:.0f}",
                  annotation_position="right")

    if max_loss_contract > 0:
        fig.add_hline(y=-max_loss_contract, line_dash="dot", line_color="red",
                      annotation_text=f"Max Loss -${max_loss_contract:.0f}",
                      annotation_position="right")

    fig.update_layout(
        title=f"P&L at Expiration — {structure.upper()} {expiration}",
        xaxis_title="Underlying Price at Expiration ($)",
        yaxis_title="P&L per Contract ($)",
        template="plotly_dark",
        height=380,
        showlegend=False,
        margin=dict(l=60, r=80, t=50, b=50),
    )

    return fig


def chart_gex_history(analytics_result: dict) -> go.Figure:
    """GEX history: x = date, y = GEX in billions.

    Data source: analytics_result['gex_history'] — list of dicts with keys 'date' and 'gex_billions'.
    Positive GEX shaded green (dealer long gamma = dampening), negative red (dealer short = amplifying).
    """
    gex_hist = analytics_result.get("gex_history") or []
    fig = go.Figure()
    if gex_hist:
        dates = [h["date"] for h in gex_hist]
        gexs  = [h["gex_billions"] for h in gex_hist]
        fig.add_trace(go.Scatter(x=dates, y=gexs, mode="lines", name="GEX",
                                  line=dict(color="#f39c12", width=2),
                                  fill="tozeroy",
                                  fillcolor="rgba(243,156,18,0.15)"))
        fig.add_hline(y=0, line_color="white", line_dash="dash", line_width=1)
        current_gex = analytics_result.get("gex_billions", 0.0)
        fig.add_annotation(text=f"Current: {current_gex:+.2f}B",
                           xref="paper", yref="paper", x=0.02, y=0.95, showarrow=False)
    else:
        # Show single data point from current analytics if no history
        current_gex = analytics_result.get("gex_billions")
        if current_gex is not None:
            fig.add_annotation(
                text=f"Current GEX: {current_gex:+.2f}B\n(No history available)",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14),
            )
        else:
            fig.add_annotation(text="No GEX data", xref="paper", yref="paper",
                               x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_layout(title="GEX History", xaxis_title="Date",
                      yaxis_title="GEX ($ Billions)", height=300,
                      margin=dict(t=40, b=30, l=50, r=20))
    return fig
