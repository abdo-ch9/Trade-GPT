"""Broker selection and read-only connection state for frontend pages."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class Broker:
    name: str
    package: str

    def module(self, name):
        return import_module(f"{self.package}.{name}")

    @property
    def bridge(self):
        return self.module("mt5_demo")

    @property
    def gold(self):
        return self.module("gold")

    @property
    def auto(self):
        return self.module("auto_demo")

    @property
    def is_exness(self):
        return self.name == "Exness"

    def connect(self):
        bridge = self.bridge
        return bridge.connect(read_only=True) if self.is_exness else bridge.connect()

    def inspect(self, identity):
        bridge = self.bridge
        return bridge.inspect(identity, read_only=True) if self.is_exness else bridge.inspect(identity)

    def account(self, identity):
        bridge = self.bridge
        with bridge.LOCK:
            mt5 = bridge.api()
            return (bridge.checked_account(mt5, identity, read_only=True)
                    if self.is_exness else bridge.checked_account(mt5, identity))

    def mode(self, account):
        if not self.is_exness:
            return "demo"
        return ("real" if account.trade_mode == self.bridge.api().ACCOUNT_TRADE_MODE_REAL
                else "demo")


BROKERS = {
    "IC Markets": Broker("IC Markets", "scalp_lab"),
    "Exness": Broker("Exness", "scalp_lab_exness"),
}


def selected():
    import streamlit as st
    return BROKERS[st.session_state.get("selected_broker", "IC Markets")]


def clear_broker_state():
    """Drop account-scoped widgets when the broker changes, never broker records."""
    import streamlit as st
    for key in list(st.session_state):
        if key.startswith(("gold_", "xm_", "terminal_", "confirm_", "forecast_")):
            del st.session_state[key]


def connection(broker):
    """Return current account and instruments, or a displayable connection error."""
    import streamlit as st
    identity = st.session_state.get("gold_identity")
    if not identity:
        return None, [], "Connect the selected MT5 account to view live data."
    try:
        account, instruments = broker.inspect(identity)
        return account, instruments, None
    except broker.bridge.DemoError as exc:
        return None, [], str(exc)


def selected_instrument(broker, instruments):
    """Keep the exact gold symbol stable across pages and account refreshes."""
    import streamlit as st
    choices = [item for item in instruments if broker.gold.eligible_symbol(item)]
    if not choices:
        return None
    names = [item.name for item in choices]
    key = "gold_symbol"
    if st.session_state.get(key) not in names:
        st.session_state[key] = names[0]
    return next(item for item in choices if item.name == st.session_state[key])


def offset(broker):
    import streamlit as st
    return broker.bridge.UTC_OFFSET_HOURS if broker.is_exness else st.session_state.get("gold_offset", 2)
