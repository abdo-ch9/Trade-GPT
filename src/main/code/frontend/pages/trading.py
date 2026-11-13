"""Chart-first trading workspace; only explicit row buttons can submit orders."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend import components, services
from .common import page_state


def _display_bars(frame, timeframe):
    bars = frame.tail(900).copy()
    if timeframe == "M1":
        return bars.tail(240)
    interval = 5 if timeframe == "M5" else 15
    bars["bucket"] = (bars["time"] // (interval * 60)) * interval * 60
    grouped = bars.groupby("bucket", as_index=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), ema9=("ema9", "last"),
        ema20=("ema20", "last"), vwap_proxy=("vwap_proxy", "last"),
        count=("time", "size"))
    grouped = grouped[grouped["count"] == interval].rename(columns={"bucket": "time"})
    return grouped.tail(120)


def _chart(result, symbol, timeframe):
    bars = _display_bars(result["frame"], timeframe)
    if bars.empty:
        components.empty("Chart data is warming up", "Wait for completed broker candles.")
        return
    x = pd.to_datetime(bars.time, unit="s", utc=True)
    figure = go.Figure(go.Candlestick(
        x=x, open=bars.open, high=bars.high, low=bars.low, close=bars.close,
        increasing_line_color="#8dbba3", decreasing_line_color="#dd9296",
        name=symbol))
    for field, label, color in (
        ("ema9", "EMA 9", "#e2bb83"),
        ("ema20", "EMA 20", "#8bb7c4"),
        ("vwap_proxy", "M1 tick VWAP proxy", "#b4a6d5"),
    ):
        if field in bars:
            figure.add_trace(go.Scatter(x=x, y=bars[field], mode="lines", name=label,
                                        line={"color": color, "width": 1.35}))
    figure.update_layout(
        height=610, margin={"l": 10, "r": 10, "t": 18, "b": 12},
        paper_bgcolor="#111a22", plot_bgcolor="#111a22", font={"color": "#a9bac3"},
        xaxis_rangeslider_visible=False, uirevision=f"{symbol}:{timeframe}",
        legend={"orientation": "h", "y": 1.02, "x": 0},
        xaxis={"gridcolor": "#263741"}, yaxis={"gridcolor": "#263741"})
    st.plotly_chart(figure, use_container_width=True, key=f"chart_{symbol}_{timeframe}")
    if timeframe != "M1":
        st.caption("M5/M15 candles are display-only aggregates of completed M1 bars. Indicator overlays retain the M1 research values; trading decisions are unchanged.")


def _position_management(broker, identity, account, offset, positions, orders):
    """Explicit broker actions with a fresh backend account and ticket check."""
    manager = broker.module("trade_management")
    mode = broker.mode(account)
    with st.expander("Manage broker positions and pending orders"):
        st.caption(f"{broker.name} {mode.upper()} · account {account.login}. Every action is checked again at MT5.")
        if mode == "real":
            st.error("LIVE · REAL MONEY. Changes and closes affect the real broker account.")
        if positions:
            tickets = {int(row["ticket"]): row for row in positions}
            ticket = st.selectbox("Open position", list(tickets),
                                  format_func=lambda key: f"{key} · {tickets[key]['symbol']} · {tickets[key]['volume']} lot",
                                  key="terminal_manage_position")
            position = tickets[ticket]
            with st.form("position_stops_form"):
                st.write("Update stop loss and take profit")
                stop = st.number_input("Stop loss price", min_value=0.00001,
                                       value=float(position.get("sl") or 0.00001), format="%.5f")
                target = st.number_input("Take profit price", min_value=0.00001,
                                         value=float(position.get("tp") or 0.00001), format="%.5f")
                reviewed = st.checkbox("I reviewed this position and both new levels")
                typed = (st.text_input(f"Type LIVE account {account.login}", autocomplete="off")
                         if mode == "real" else str(account.login))
                update = st.form_submit_button("Update broker stops")
            if update:
                if not reviewed or typed.strip() != str(account.login):
                    st.error("Review the levels and confirm the selected account first.")
                else:
                    try:
                        st.session_state.terminal_manage_outcome = manager.update_stops(
                            identity, ticket, position["symbol"], stop, target,
                            confirm_live=mode == "real")
                        st.rerun()
                    except broker.bridge.DemoError as exc:
                        st.error(str(exc))
            with st.form("position_close_form"):
                st.write(f"Close position {ticket} · {position['symbol']} · {position['volume']} lot")
                reviewed_close = st.checkbox("I understand this sends a market close order")
                typed_close = (st.text_input(f"Type LIVE account {account.login} to close",
                                             autocomplete="off") if mode == "real" else str(account.login))
                close = st.form_submit_button("Close this position")
            if close:
                if not reviewed_close or typed_close.strip() != str(account.login):
                    st.error("Confirm the selected account and close action first.")
                else:
                    try:
                        st.session_state.terminal_manage_outcome = manager.close_position(
                            identity, ticket, position["symbol"], offset, confirm_live=mode == "real")
                        st.rerun()
                    except broker.bridge.DemoError as exc:
                        st.error(str(exc))
        if orders:
            pending = {int(row["ticket"]): row for row in orders}
            order_ticket = st.selectbox("Pending order", list(pending),
                                        format_func=lambda key: f"{key} · {pending[key]['symbol']}",
                                        key="terminal_manage_order")
            selected_order = pending[order_ticket]
            with st.form("pending_stops_form"):
                st.write(f"Update pending order {order_ticket} stops")
                order_stop = st.number_input("Pending stop loss", min_value=0.00001,
                                             value=float(selected_order.get("sl") or 0.00001),
                                             format="%.5f")
                order_target = st.number_input("Pending take profit", min_value=0.00001,
                                               value=float(selected_order.get("tp") or 0.00001),
                                               format="%.5f")
                reviewed_pending = st.checkbox("I reviewed the pending order and both new levels")
                typed_pending = (st.text_input(f"Type LIVE account {account.login} to modify",
                                               autocomplete="off") if mode == "real" else str(account.login))
                update_pending = st.form_submit_button("Update pending order stops")
            if update_pending:
                if not reviewed_pending or typed_pending.strip() != str(account.login):
                    st.error("Confirm the selected account and order levels first.")
                else:
                    try:
                        st.session_state.terminal_manage_outcome = manager.update_pending_stops(
                            identity, order_ticket, selected_order["symbol"], order_stop,
                            order_target, confirm_live=mode == "real")
                        st.rerun()
                    except broker.bridge.DemoError as exc:
                        st.error(str(exc))
            with st.form("pending_cancel_form"):
                reviewed_order = st.checkbox("I reviewed the pending order to cancel")
                typed_order = (st.text_input(f"Type LIVE account {account.login} to cancel",
                                             autocomplete="off") if mode == "real" else str(account.login))
                cancel = st.form_submit_button("Cancel pending order")
            if cancel:
                if not reviewed_order or typed_order.strip() != str(account.login):
                    st.error("Confirm the selected account and pending order first.")
                else:
                    try:
                        st.session_state.terminal_manage_outcome = manager.cancel_pending(
                            identity, order_ticket, pending[order_ticket]["symbol"],
                            confirm_live=mode == "real")
                        st.rerun()
                    except broker.bridge.DemoError as exc:
                        st.error(str(exc))
        if not positions and not orders:
            st.caption("No open position or pending order on this account.")
    outcome = st.session_state.get("terminal_manage_outcome")
    if outcome:
        (st.success if outcome.get("state") == "filled" else st.warning)(
            f"Broker action: {outcome.get('state')} · {outcome.get('message', '')}")


def render():
    components.heading("Execution / XAUUSD", "Trading terminal",
                       "Live broker chart and reviewed order controls.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    symbol = instrument.name
    exposure_error = None
    try:
        positions, orders = services.current_orders(broker, identity)
    except broker.bridge.DemoError as exc:
        positions, orders = [], []
        exposure_error = str(exc)
        st.warning("Account exposure unavailable: " + str(exc))
    if exposure_error is None:
        _position_management(broker, identity, account, offset, positions, orders)
    timeframe = st.segmented_control("Chart timeframe", ("M1", "M5", "M15"),
                                     default=st.session_state.get("display_timeframe", "M1"),
                                     key="terminal_timeframe")
    refresh = st.button("Refresh market data", key="terminal_refresh")
    try:
        result, pending = services.analysis(broker, identity, symbol, offset, refresh=refresh)
    except (broker.bridge.DemoError, ValueError) as exc:
        st.error(str(exc))
        return
    if pending:
        st.warning(pending)
        return
    try:
        with broker.bridge.LOCK:
            tick = broker.bridge.quote(broker.bridge.api(), symbol, offset)
        bid, ask = tick.bid, tick.ask
    except broker.bridge.DemoError as exc:
        bid = ask = None
        st.warning("Current quote unavailable: " + str(exc))
    components.metrics([
        ("Bid", components.number(bid, 3)),
        ("Ask", components.number(ask, 3)),
        ("Spread", components.number(ask - bid, 3) if bid is not None else "—"),
        ("Decision", result.get("action", "—")),
    ])
    st.caption("Market analysis observed " + components.utc(result.get("observed_at")) +
               " · completed candle age " + components.number(result.get("candle_age_seconds"), 0, "s"))
    _chart(result, symbol, timeframe or "M1")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        components.section("Signal and proposed levels")
        st.write(f"**{result.get('action', 'NO SETUP')}** · {result.get('regime', 'Unknown regime')} · {result.get('setup', 'No setup')}")
        reasons = result.get("reasons") or []
        st.caption(reasons[0] if reasons else "No entry pattern has qualified.")
        side = result.get("chart_signal")
        scenario = result.get("scenarios", {}).get(side, {})
        if scenario:
            entry, stop, target = (scenario.get(key) for key in ("entry", "sl", "tp"))
            reward_ratio = (abs(target - entry) / abs(entry - stop)
                            if all(isinstance(value, (int, float)) for value in (entry, stop, target))
                            and entry != stop else None)
            components.metrics([
                ("Lots", components.number(scenario.get("lots"), 2)),
                ("Entry", components.number(scenario.get("entry"), 3)),
                ("Stop loss", components.number(scenario.get("sl"), 3)),
                ("Take profit", components.number(scenario.get("tp"), 3)),
                ("Reward / risk", components.number(reward_ratio, 2)),
                ("Estimated loss at stop", components.number(scenario.get("risk_amount"), 2,
                                                            account.currency)),
                ("Risk / equity", components.number(scenario.get("risk_pct"), 2, "%")),
            ])
            st.caption("Calculated, read-only proposal. Risk excludes fees and slippage. Orders and fills appear in the history page.")
        with st.expander("Detailed validation checks"):
            st.dataframe(result.get("checks", []), hide_index=True, width="stretch")
    with right:
        components.section("Open positions and pending orders")
        st.metric("Open positions", len(positions))
        st.metric("Pending orders", len(orders))
        if positions:
            st.dataframe([{key: row.get(key) for key in
                           ("ticket", "symbol", "volume", "price_open", "sl", "tp", "profit")}
                          for row in positions], hide_index=True, width="stretch")
        else:
            st.caption("No open positions on this account.")
    components.section("Reviewed manual execution")
    live_confirmed = True
    if broker.mode(account) == "real":
        st.error(f"LIVE · REAL MONEY · {broker.name} account {account.login}. This button can place a real order.")
        acknowledged = st.checkbox("I understand this order will use real money",
                                   key="confirm_real_manual")
        typed_account = st.text_input(f"Type account number {account.login} to enable the LIVE order",
                                      key="confirm_live_manual_account", autocomplete="off")
        live_confirmed = acknowledged and typed_account.strip() == str(account.login)
    config = broker.auto.settings()
    lots = config.get("lots", .01)
    side = result.get("chart_signal")
    qualifies = side in ("BUY", "SELL") and result.get("action") == f"{side} setup"
    bound = (tuple(config.get("identity") or ()) == tuple(identity)
             and symbol in (config.get("symbols") or []) and config.get("offset") == offset)
    if not bound:
        st.info("Bind this account and gold instrument in Automation center before manual execution.")
    if config.get("enabled"):
        st.info("Stop automatic entries in Automation center before using a manual trade button.")
    st.caption(f"A click refreshes the chart, news, and quote. Backend validation, daily budget, {config.get('max_entries', 5)}-attempt limit, and duplicate protection are checked again before submission.")
    if st.button(f"Submit {side} {lots:g} lot · {broker.name} {broker.mode(account).upper()}",
                 key="terminal_submit_order", type="primary",
                 disabled=not qualifies or not bound or config.get("enabled") or not live_confirmed):
        try:
            with st.spinner("Rechecking the setup and broker quote before submission…"):
                outcome = broker.auto.trade_row(identity, symbol, offset, side,
                                                confirm_live=broker.mode(account) == "real")
            st.session_state.terminal_trade_outcome = {"symbol": symbol, **outcome}
        except broker.bridge.DemoError as exc:
            st.session_state.terminal_trade_outcome = {"symbol": symbol, "state": "blocked", "message": str(exc)}
    outcome = st.session_state.get("terminal_trade_outcome")
    if outcome and outcome.get("symbol") == symbol:
        message = f"{symbol} · {outcome.get('state', 'unknown')}: {outcome.get('message', '')}"
        (st.success if outcome.get("state") == "filled" else st.warning)(message)
    components.section("Recent execution events")
    events = [item for item in services.events(broker, limit=30)
              if any(word in str(item.get("kind", "")).lower()
                     for word in ("entry", "exit", "order", "fill", "trade"))][:5]
    if events:
        st.dataframe([{"Time": components.utc(item.get("time")),
                       "Event": item.get("kind"), "Detail": item.get("message")}
                      for item in events], hide_index=True, width="stretch")
    else:
        st.caption("No recent execution events in the local broker journal.")
