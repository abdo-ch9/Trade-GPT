"""Application frame, broker controls, and native Streamlit navigation."""
import streamlit as st

from . import styles, components
from .context import BROKERS, clear_broker_state, connection, selected, selected_instrument
from .pages import automation, backtesting, dashboard, forecast, history, intelligence, risk, settings, trading


def main():
    st.set_page_config(page_title="Gold terminal", page_icon=":material/candlestick_chart:", layout="wide",
                       initial_sidebar_state="auto")
    styles.apply()
    with st.sidebar:
        st.markdown('<div class="terminal-eyebrow">Gold terminal / MT5</div>', unsafe_allow_html=True)
        broker_name = st.selectbox("Broker", tuple(BROKERS), key="selected_broker")
        if st.session_state.get("active_broker") != broker_name:
            clear_broker_state()
            st.session_state.active_broker = broker_name
        broker = selected()
        if not broker.is_exness:
            st.selectbox("MT5 server time", (2, 3, 0),
                         format_func=lambda value: f"UTC + {value} hours", key="gold_offset")
        if st.button("Connect MT5", use_container_width=True, key="connect_account"):
            try:
                st.session_state.gold_identity = broker.connect()
                st.rerun()
            except broker.bridge.DemoError as exc:
                st.error(str(exc))
        account, instruments, error = connection(broker)
        if account:
            mode = broker.mode(account)
            st.caption(f"{mode.upper()} · account {account.login} · {account.server}")
            choices = [item for item in instruments if broker.gold.eligible_symbol(item)]
            if choices:
                selected_instrument(broker, instruments)
                st.selectbox("Gold instrument", [item.name for item in choices], key="gold_symbol")
            else:
                st.warning("No supported USD gold instrument on this account.")
        else:
            st.caption(error or "Disconnected")
        st.divider()
        st.caption("Local terminal · broker orders require explicit controls")

    worker = broker.module("gold_worker").status()
    components.status_bar(broker, account, broker.mode(account) if account else "—", worker)
    if account and broker.mode(account) == "real":
        st.warning("Exness real account connected. Trading controls can use real funds.")

    pages = {
        "Workspace": [
            st.Page(dashboard.render, title="Dashboard", icon=":material/dashboard:", url_path="dashboard", default=True),
            st.Page(trading.render, title="Trading terminal", icon=":material/candlestick_chart:", url_path="trading"),
            st.Page(intelligence.render, title="AI market intelligence", icon=":material/psychology:", url_path="intelligence"),
        ],
        "Control": [
            st.Page(automation.render, title="Automation center", icon=":material/smart_toy:", url_path="automation"),
            st.Page(risk.render, title="Risk management", icon=":material/monitoring:", url_path="risk"),
            st.Page(settings.render, title="Settings", icon=":material/tune:", url_path="settings"),
        ],
        "Research": [
            st.Page(backtesting.render, title="Strategy & backtesting", icon=":material/query_stats:", url_path="backtesting"),
            st.Page(forecast.render, title="Paper forecasts", icon=":material/insights:", url_path="forecasts"),
            st.Page(history.render, title="Trade history & analytics", icon=":material/history:", url_path="history"),
        ],
    }
    st.navigation(pages, position="sidebar").run()
