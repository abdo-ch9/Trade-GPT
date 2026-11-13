"""Operational overview with no chart or order controls."""
import time

import streamlit as st

from frontend import components, services
from .common import page_state


def render():
    components.heading("Overview / live account", "Dashboard",
                       "Account, exposure, risk headroom, and system health in one place.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    config = broker.auto.settings()
    worker_module = broker.module("gold_worker")
    if not worker_module.status():
        worker_module.ensure_running()
    worker = worker_module.status()
    mode = broker.mode(account)
    risk = None
    try:
        risk = broker.module("gold_snapshot").risk_summary(identity, config)
    except broker.bridge.DemoError as exc:
        st.warning("Risk headroom unavailable: " + str(exc))
    try:
        positions, orders = services.current_orders(broker, identity)
    except broker.bridge.DemoError as exc:
        positions, orders = [], []
        st.warning("Exposure unavailable: " + str(exc))
    try:
        daily_pnl = services.daily_trading_pnl(broker.name, tuple(identity))
    except broker.bridge.DemoError as exc:
        daily_pnl = None
        st.warning("Today's realized trading P&L unavailable: " + str(exc))

    components.metrics([
        ("Equity", components.number(getattr(account, "equity", None), unit=account.currency)),
        ("Balance", components.number(getattr(account, "balance", None), unit=account.currency)),
        ("Free margin", components.number(getattr(account, "margin_free", None), unit=account.currency)),
        ("Open P&L", components.number(getattr(account, "profit", None), unit=account.currency)),
        ("Today · trade deals", components.number(daily_pnl, unit=account.currency)),
    ])
    components.section("Risk and automation")
    components.metrics([
        ("Daily risk budget", components.number(risk["budget"], unit=risk["currency"]) if risk else "—"),
        ("Remaining", components.number(risk["remaining"], unit=risk["currency"]) if risk else "—"),
        ("Positions / orders", f"{len(positions)} / {len(orders)}"),
        ("Automation", "Running" if config.get("enabled") else "Stopped"),
    ])
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        components.section("Current account exposure")
        if positions:
            st.dataframe([{key: row.get(key) for key in
                           ("ticket", "symbol", "type", "volume", "price_open", "sl", "tp", "profit")}
                          for row in positions], hide_index=True, width="stretch")
        else:
            components.empty("No open positions", "MT5 reports no positions for the connected account.")
        components.section("Latest signal")
        decisions = services.latest_decisions(broker, identity, [instrument.name], limit=1)
        if decisions:
            row = decisions[0]
            st.markdown(f"**{row.get('Decision', '—')} · {row.get('Direction', '—')}**")
            st.caption(row.get("Reason") or row.get("Execution status") or "No explanation recorded.")
            st.caption("Saved decision · " + row.get("Saved at (UTC)", "time unavailable"))
        else:
            components.empty("No saved directional signal", "Chart decisions appear here after a qualifying BUY or SELL direction is evaluated.")
    with right:
        components.section("System health")
        fresh = 0 <= time.time() - worker.get("heartbeat", 0) < 15
        st.metric("Worker heartbeat", components.age(worker.get("heartbeat")))
        st.metric("Last completed scan", components.age(worker.get("last_scan")))
        st.caption("Scanner: " + worker.get("scanner", "Not started"))
        if not config.get("identity") and fresh:
            st.info("Worker is online and waiting for an automation account session.")
        elif not worker_module.healthy(worker):
            st.warning("Exit watchdog is not ready for this account. Open Automation center for details.")
        if worker.get("exit_error"):
            st.error(worker["exit_error"])
        if mode == "real":
            st.warning("Real account connected. Orders use real funds.")
        report = services.validation_report(broker, instrument.name)
        if report and not report.get("eligible"):
            st.warning("Historical validation failed: " + report.get("reason", "No reason recorded."))
