"""
ui/components/onboarding.py — First-run onboarding modal for new users.

Shows a guided setup wizard on first launch (guarded by session_state).
Accessible again via a "Getting Started" button in the dashboard.
"""
import streamlit as st


def render_onboarding() -> None:
    """Render the onboarding flow if this is the user's first visit."""
    if st.session_state.get("_onboarding_complete"):
        return

    _show_onboarding_modal()


def render_onboarding_button() -> None:
    """Render a 'Getting Started' button that re-opens onboarding."""
    if st.button("Getting Started Guide", key="btn_onboarding_open"):
        st.session_state["_onboarding_step"] = 0
        st.session_state["_show_onboarding"] = True
        st.rerun()


def _show_onboarding_modal() -> None:
    """Show multi-step onboarding wizard."""
    if not st.session_state.get("_show_onboarding", True):
        return

    step = st.session_state.get("_onboarding_step", 0)

    with st.container():
        st.divider()
        st.subheader("Welcome to VRP Options Screener")

        steps = [
            _step_what_is_this,
            _step_portfolio_setup,
            _step_how_scanning_works,
            _step_reading_results,
            _step_ready,
        ]

        if step < len(steps):
            steps[step]()

        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if step > 0:
                if st.button("← Back", key="onboard_back"):
                    st.session_state["_onboarding_step"] = step - 1
                    st.rerun()
        with col2:
            st.caption(f"Step {step + 1} of {len(steps)}")
        with col3:
            if step < len(steps) - 1:
                if st.button("Next →", key="onboard_next", type="primary"):
                    st.session_state["_onboarding_step"] = step + 1
                    st.rerun()
            else:
                if st.button("Start Screening!", key="onboard_finish", type="primary"):
                    st.session_state["_onboarding_complete"] = True
                    st.session_state["_show_onboarding"] = False
                    st.rerun()

        if st.button("Skip", key="onboard_skip"):
            st.session_state["_onboarding_complete"] = True
            st.session_state["_show_onboarding"] = False
            st.rerun()

        st.divider()


def _step_what_is_this() -> None:
    st.markdown("""
    ### What does this screener do?

    Every day, options (contracts giving the right to buy/sell a stock) are priced slightly higher than
    they should be. **Sellers of options collect this extra premium** — it's called the **Volatility Risk Premium (VRP)**.

    This app scans **1,485 stocks and ETFs** to find the ones where:
    - Options are **most overpriced** (high VRP)
    - The **fundamentals are healthy** (you don't want to own a distressed company)
    - The **timing is right** (no earnings surprises around your trade)

    Then it tells you **exactly what to trade, at what price, and how much to put on**.
    """)
    st.info("Think of it as a systematic way to find the best premium-selling opportunities each day.", icon="💡")


def _step_portfolio_setup() -> None:
    st.markdown("""
    ### Set Up Your Portfolio

    The screener uses your **portfolio size** to calculate how many contracts to trade.

    Go to **Settings** (left sidebar) and set:
    - **Portfolio Value** — your total trading account size
    - **Max Position %** — the maximum % of your portfolio for any single trade

    **Recommended starting settings:**
    - Conservative: Max Position = 2-3%
    - Moderate: Max Position = 4-5%
    - Aggressive: Max Position = 7-10%

    > **Paper Trading Tip:** Start with paper trading in the Portfolio Monitor page to practice without risking real money.
    """)


def _step_how_scanning_works() -> None:
    st.markdown("""
    ### How the Scan Works

    **Stage 1 (2-4 minutes):** Scans all 1,485 tickers using free Yahoo Finance data.
    Narrows down to the top 175 based on approximate VRP scores.

    **Stage 2 (2-4 minutes, requires Schwab API):** Deep-dives the top 175 with live options
    data, running 18+ signals, fundamental health checks, and full P&L modeling.

    **Without Schwab keys:** You get Stage 1 results — approximate scores that are still
    useful for identifying candidates to research further.

    Click **Run Full Scan** on the Scanner Dashboard to start.
    """)


def _step_reading_results() -> None:
    st.markdown("""
    ### Reading the Results

    | Score | Meaning |
    |-------|---------|
    | 90-100 | **Exceptional** — rare alignment of all signals |
    | 75-89 | **Strong** — high premium, persistent signal |
    | 60-74 | **Good** — clear opportunity worth analyzing |
    | 40-59 | **Moderate** — some premium but not compelling |
    | 0-39 | **Weak** — skip for now |

    Click any row to see the **full trade recommendation** — including:
    - Exactly what to trade (strike, expiration, credit)
    - What happens in 4 different scenarios
    - How much to put on (Kelly-sized position)
    - Copy-paste order text for your broker
    """)


def _step_ready() -> None:
    st.markdown("""
    ### You're Ready!

    **Next steps:**
    1. Click **Run Full Scan** on the Scanner Dashboard
    2. Sort by **Score** (descending) to see best opportunities
    3. Click a row to see the full recommendation
    4. Use **Custom Lookup** to analyze any specific ticker
    5. Track your trades in **Portfolio Monitor**

    > **Remember:** This is informational only. Always do your own research before trading options.
    > Options involve substantial risk of loss.
    """)
    st.success("Ready to find premium-selling opportunities!", icon="✅")
