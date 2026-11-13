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


def render():
    components.heading("Execution / XAUUSD", "Trading terminal",
                       "Live broker chart and reviewed order controls.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    symbol = instrument.name
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
                ("Entry", components.number(scenario.get("entry"), 3)),
                ("Stop loss", components.number(scenario.get("sl"), 3)),
                ("Take profit", components.number(scenario.get("tp"), 3)),
                ("Reward / risk", components.number(reward_ratio, 2)),
            ])
            st.caption("Proposed levels only. Orders and fills appear in the history page.")
        with st.expander("Detailed validation checks"):
            st.dataframe(result.get("checks", []), hide_index=True, width="stretch")
    with right:
        components.section("Open positions and pending orders")
        try:
            positions, orders = services.current_orders(broker, identity)
            st.metric("Open positions", len(positions))
            st.metric("Pending orders", len(orders))
            if positions:
                st.dataframe([{key: row.get(key) for key in
                               ("ticket", "symbol", "volume", "price_open", "sl", "tp", "profit")}
                              for row in positions], hide_index=True, width="stretch")
            else:
                st.caption("No open positions on this account.")
        except broker.bridge.DemoError as exc:
            st.warning(str(exc))
    components.section("Reviewed manual execution")
    if broker.is_exness and broker.mode(account) == "real":
        if not st.checkbox("Show real-money order controls", key="confirm_real_manual"):
            st.warning("Real account connected. Manual controls are hidden until you acknowledge real-money execution.")
            return
    config = broker.auto.settings()
    side = result.get("chart_signal")
    qualifies = side in ("BUY", "SELL") and result.get("action") == f"{side} setup"
    bound = (tuple(config.get("identity") or ()) == tuple(identity)
             and symbol in (config.get("symbols") or []) and config.get("offset") == offset)
    if not bound:
        st.info("Bind this account and gold instrument in Automation center before manual execution.")
    if config.get("enabled"):
        st.info("Stop automatic entries in Automation center before using a manual trade button.")
    st.caption("A click refreshes the chart, news, and quote. Backend validation, daily budget, five-attempt limit, and duplicate protection are checked again before submission.")
    if st.button(f"Submit {side} 0.01 lot · {broker.name} {broker.mode(account).upper()}",
                 key="terminal_submit_order", type="primary", disabled=not qualifies or not bound or config.get("enabled")):
        try:
            with st.spinner("Rechecking the setup and broker quote before submission…"):
                outcome = broker.auto.trade_row(identity, symbol, offset, side)
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
