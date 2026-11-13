"""Choose a broker before connecting to its MT5 terminal."""
import importlib
import streamlit as st

st.set_page_config(page_title="Gold research desk", layout="wide")
st.title("Gold research desk")
broker = st.selectbox("Broker", ("IC Markets", "Exness"), key="selected_broker")
if st.session_state.get("active_broker") != broker:
    for key in list(st.session_state):
        if key.startswith("gold_") or key.startswith("xm_"):
            del st.session_state[key]
    st.session_state.active_broker = broker
module = "dashboard_ic" if broker == "IC Markets" else "dashboard_exness"
importlib.import_module(module).workspace()
