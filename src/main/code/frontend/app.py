"""Application frame, broker controls, and native Streamlit navigation."""
import streamlit as st

from . import styles, components
from .context import BROKERS, broker_for, clear_broker_state, connection, selected, selected_instrument
from .pages import automation, backtesting, dashboard, forecast, history, intelligence, risk, settings, trading


def _on_context_change():
    """Stop demo entries on a live switch; reject other active context changes."""
    previous_name = st.session_state.get("active_broker")
    previous_environment = st.session_state.get("active_environment", "DEMO")
    name = st.session_state.get("selected_broker", "IC Markets")
    environment = st.session_state.get("trading_environment", "DEMO")
    if previous_name and (previous_name, previous_environment) != (name, environment):
        previous = broker_for(previous_name, "real" if previous_environment == "LIVE" else "demo")
        if previous.auto.settings().get("enabled"):
            switching_demo_to_live = (previous_environment == "DEMO" and environment == "LIVE"
                                      and name == previous_name)
            if switching_demo_to_live:
                try:
                    previous.auto.stop("Stopped when switching to LIVE")
                    if previous.auto.settings().get("enabled"):
                        raise RuntimeError("entry scanning is still enabled")
                except Exception as exc:
                    st.session_state.selection_error = f"Could not stop DEMO entries: {exc}"
                    st.session_state.selected_broker = previous_name
                    st.session_state.trading_environment = previous_environment
                    return
                st.session_state.selection_notice = (
                    "DEMO entry scanning stopped. Switching modes does not start LIVE automation.")
            else:
                st.session_state.selected_broker = previous_name
                st.session_state.trading_environment = previous_environment
                st.session_state.selection_blocked = True
                return
    if (previous_name, previous_environment) != (name, environment):
        clear_broker_state()
        st.session_state.active_broker = name
        st.session_state.active_environment = environment


def main():
    st.set_page_config(page_title="Gold terminal", page_icon=":material/candlestick_chart:", layout="wide",
                       initial_sidebar_state="auto")
    styles.apply()
    st.session_state.setdefault("trading_environment", "DEMO")
    with st.sidebar:
        st.markdown('<div class="terminal-eyebrow">Gold terminal / MT5</div>', unsafe_allow_html=True)
        broker_name = st.selectbox("Broker", tuple(BROKERS), key="selected_broker",
                                   on_change=_on_context_change)
        environment = st.segmented_control("Trading environment", ("DEMO", "LIVE"),
                                           key="trading_environment",
                                           on_change=_on_context_change) or "DEMO"
        if "active_broker" not in st.session_state:
            _on_context_change()
        if st.session_state.pop("selection_blocked", False):
            st.warning("Stop automatic entries in Automation center before changing broker or environment.")
        if error := st.session_state.pop("selection_error", None):
            st.error(error)
        if notice := st.session_state.pop("selection_notice", None):
            st.info(notice)
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
        if environment == "LIVE":
            st.error("LIVE · REAL MONEY. Connecting does not start automatic trading.")
        st.divider()
        st.caption("Local terminal · broker orders require explicit controls")

    worker = broker.module("gold_worker").status()
    components.status_bar(broker, account, broker.environment, worker)
    if environment == "LIVE":
        st.error(f"LIVE · REAL MONEY · {broker.name}" +
                 (f" · account {account.login} · {account.server}" if account else " · disconnected"))

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
