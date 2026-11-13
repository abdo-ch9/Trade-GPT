"""Paper-only forecast workspace from the main-branch research module."""
import streamlit as st

from frontend.context import offset, selected


def render():
    broker = selected()
    directory = broker.module("paths").LIB_DIR
    st.caption("Research / paper forecasts · no order submission")
    from scalp_lab.forecast.dashboard import render as render_forecasts
    render_forecasts(broker.bridge, directory, offset(broker))
