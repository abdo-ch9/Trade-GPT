"""Separate broker positions, journaled fills, and historical proposals."""
import json
import sqlite3

import streamlit as st

from frontend import components, services
from .common import page_state


def _filtered(rows, query):
    if not query:
        return rows
    needle = query.casefold()
    return [row for row in rows if needle in " ".join(str(value) for value in row.values()).casefold()]


def render():
    components.heading("Review / broker and journal", "Trade history & analytics",
                       "Signals, orders, fills, and closed trades are shown as different records.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    query = st.text_input("Search visible records", placeholder="Symbol, setup, order, or reason")
    try:
        positions, orders = services.current_orders(broker, identity)
    except broker.bridge.DemoError as exc:
        positions, orders = [], []
        st.warning(str(exc))
    try:
        forward = services.performance(broker, identity)
    except (OSError, ValueError, sqlite3.Error) as exc:
        st.warning("Journal report unavailable: " + str(exc))
        forward = {"closed_trades": 0, "net_pnl": None, "win_rate": None,
                   "profit_factor": None, "mean_r": None, "mean_latency_seconds": None,
                   "trades": [], "unresolved_entries": 0, "unresolved_exits": 0}
    components.metrics([
        ("Open positions", str(len(positions))),
        ("Pending orders", str(len(orders))),
        ("Closed bot trades", str(forward["closed_trades"])),
        ("Closed bot P&L", components.number(forward["net_pnl"], unit=account.currency)),
    ])
    tabs = st.tabs(["Open positions", "Pending orders", "Closed trades", "Saved signals", "Events"])
    with tabs[0]:
        rows = _filtered(positions, query)
        st.dataframe(rows, hide_index=True, width="stretch") if rows else components.empty(
            "No matching positions", "MT5 reports no open position matching this search.")
    with tabs[1]:
        rows = _filtered(orders, query)
        st.dataframe(rows, hide_index=True, width="stretch") if rows else components.empty(
            "No matching orders", "MT5 reports no pending order matching this search.")
    with tabs[2]:
        trades = _filtered(forward.get("trades") or [], query)
        components.metrics([
            ("Win rate", components.number(forward.get("win_rate") * 100, 1, "%")
             if isinstance(forward.get("win_rate"), (int, float)) else "—"),
            ("Profit factor", components.number(forward.get("profit_factor"), 2)),
            ("Mean R", components.number(forward.get("mean_r"), 3)),
            ("Mean latency", components.number(forward.get("mean_latency_seconds"), 2, "s")),
        ])
        if forward.get("unresolved_entries") or forward.get("unresolved_exits"):
            st.warning("Some broker/journal outcomes remain unresolved. Review them before retrying an order.")
        st.dataframe(trades, hide_index=True, width="stretch") if trades else components.empty(
            "No matching closed bot trades", "This table counts reconciled fills and exits, not proposed signals.")
        st.download_button("Download forward report", json.dumps(forward, indent=2),
                           "forward_report.json", mime="application/json")
    with tabs[3]:
        decisions = _filtered(services.latest_decisions(broker, identity, [instrument.name]), query)
        if st.checkbox("Show rejected decisions only", key="history_rejected_only"):
            decisions = [row for row in decisions if row.get("Decision") == "BLOCKED"]
        st.dataframe(decisions, hide_index=True, width="stretch") if decisions else components.empty(
            "No matching saved signals", "Directional proposals are saved separately from broker orders.")
        if decisions:
            st.download_button("Download saved signals", services.csv_output(decisions),
                               "gold_decisions.csv", mime="text/csv")
    with tabs[4]:
        rows = _filtered(services.events(broker, limit=200), query)
        compact = [{"Time (UTC)": components.utc(row.get("time")),
                    "Type": row.get("kind"), "Message": row.get("message")}
                   for row in rows]
        st.dataframe(compact, hide_index=True, width="stretch") if compact else components.empty(
            "No matching events", "Worker and execution events will appear here.")
        if compact:
            st.download_button("Download event log", json.dumps(rows, indent=2),
                               "gold_events.json", mime="application/json")
