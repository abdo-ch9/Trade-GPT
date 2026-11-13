"""Consistent broker and connection handling for every page."""
import streamlit as st

from frontend import components
from frontend.context import connection, offset, selected, selected_instrument


def page_state(*, need_connection=True):
    broker = selected()
    identity = st.session_state.get("gold_identity")
    account, instruments, error = connection(broker)
    instrument = selected_instrument(broker, instruments) if account else None
    if need_connection and error:
        components.empty("MT5 account disconnected", error + " Use Connect in the sidebar.")
        return None
    if need_connection and instrument is None:
        components.empty("Gold instrument unavailable", "Choose a supported USD gold symbol in MT5 Market Watch.")
        return None
    return broker, identity, account, instruments, instrument, offset(broker)
