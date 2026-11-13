"""Choose a broker before connecting to its MT5 terminal."""
import importlib
import streamlit as st

st.set_page_config(page_title="Gold research desk", layout="wide")
st.title("Gold research desk")
broker = st.selectbox("Broker", ("IC Markets", "Exness"), key="selected_broker")
if st.session_state.get("active_broker") != broker:
    for key in list(st.session_state):
        if key.startswith(("gold_", "xm_", "forecast_")):
            del st.session_state[key]
    st.session_state.active_broker = broker
workspace = st.radio("Workspace", ("Broker dashboard", "Paper forecasts"), horizontal=True)
if workspace == "Paper forecasts":
    from scalp_lab.forecast.dashboard import render

    package = "scalp_lab" if broker == "IC Markets" else "scalp_lab_exness"
    bridge = importlib.import_module(f"{package}.mt5_demo")
    directory = importlib.import_module(f"{package}.paths").LIB_DIR
    offset = (st.selectbox("MT5 server UTC offset", (2, 3, 0), key="forecast_offset")
              if broker == "IC Markets" else bridge.UTC_OFFSET_HOURS)
    render(bridge, directory, offset)
else:
    module = "dashboard_ic" if broker == "IC Markets" else "dashboard_exness"
    importlib.import_module(module).workspace()
