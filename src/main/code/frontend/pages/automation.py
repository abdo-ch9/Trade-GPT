"""Explicit automation controls with worker and watchdog diagnostics."""
import time
import streamlit as st

from frontend import components, services
from .common import page_state


def _can_override_holdout(broker, mode, validated, reason, news_ready,
                          context_matches, symbols, enabled):
    """Expose the backend's live override only for its exact holdout failure."""
    return (broker.is_exness and mode == "real" and not validated
            and reason == broker.gold.HOLDOUT_FAILURE and news_ready
            and context_matches and len(symbols) == 1 and not enabled)


def render():
    components.heading("Control / bot", "Automation center",
                       "Manage entry scanning while preserving monitoring of existing positions.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    auto = broker.auto
    config = auto.settings()
    worker_module = broker.module("gold_worker")
    worker_module.ensure_running()
    worker = worker_module.status()
    mode = broker.mode(account)
    symbols = auto.eligible(instruments)
    context_matches = (tuple(config.get("identity", ())) == tuple(identity)
                       and config.get("symbols") == symbols and config.get("offset") == offset)
    components.metrics([
        ("Entry scanner", "Running" if config.get("enabled") else "Stopped"),
        ("Worker", "Online" if 0 <= time.time()-worker.get("heartbeat", 0) < 15 else "Unavailable"),
        ("Exit watchdog", "Healthy" if worker_module.healthy(worker) else "Not ready"),
        ("Last scan", components.age(worker.get("last_scan"))),
    ])
    if worker.get("exit_error"):
        st.error("Exit watchdog: " + worker["exit_error"])
    st.caption("Scanner: " + worker.get("scanner", "Not started"))
    if config.get("stop_reason"):
        st.info("Last stop reason: " + config["stop_reason"])
    executions = [item for item in services.events(broker, limit=50)
                  if any(word in str(item.get("kind", "")).lower()
                         for word in ("entry", "exit", "order", "fill", "trade"))]
    st.caption("Last execution event: " + (components.utc(executions[0].get("time"))
                                         if executions else "None recorded"))

    components.section("Connection and entry gates")
    if not context_matches and not config.get("enabled"):
        st.warning("Automation is not bound to this account, instrument, and server time setting.")
        if st.button("Use this account and gold instrument", disabled=len(symbols) != 1):
            try:
                auto.bind_stopped_session(identity, symbols, offset)
                st.rerun()
            except broker.bridge.DemoError as exc:
                st.error(str(exc))
    from_news = broker.module("xm_news")
    news_ready, news_reason = from_news.connection_status()
    (st.success if news_ready else st.warning)("News service: " + news_reason)
    if broker.is_exness:
        validated, validation_reason = broker.gold.execution_validation(
            instrument.name, config, demo=mode == "demo", identity=identity)
    else:
        validated, validation_reason = broker.gold.execution_validation(instrument.name, config)
    (st.success if validated else st.warning)("Strategy gate: " + validation_reason)
    if len(symbols) != 1:
        st.warning("Exactly one eligible 0.01-lot gold instrument is required.")

    components.section("Execution permission")
    confirmation = st.checkbox(
        f"I understand Start can submit {mode.upper()} market orders on {broker.name} after all backend checks pass.",
        key="confirm_auto_start")
    if mode == "real":
        st.error("REAL account: automatic orders use real funds. Review the strategy gate before starting.")
    start_disabled = (config.get("enabled") or not context_matches or not news_ready
                      or not validated or len(symbols) != 1 or not confirmation)
    start_col, stop_col = st.columns(2)
    if start_col.button(f"Start automatic {mode.upper()} trading", disabled=start_disabled,
                        type="primary", use_container_width=True):
        try:
            auto.arm(identity, symbols, offset)
            st.rerun()
        except broker.bridge.DemoError as exc:
            st.error(str(exc))
    can_override_holdout = _can_override_holdout(
        broker, mode, validated, validation_reason, news_ready,
        context_matches, symbols, config.get("enabled"))
    if can_override_holdout:
        st.warning("The historical holdout failed. The broker backend permits an explicit, session-only override for this exact gate.")
        override_confirmed = st.checkbox(
            "I understand this REAL session can trade despite the failed historical holdout.",
            key="confirm_real_holdout_override")
        if st.button("Start REAL trading despite failed holdout",
                     disabled=not (confirmation and override_confirmed),
                     key="start_real_holdout_override"):
            try:
                auto.arm(identity, symbols, offset, override_live_validation=True)
                st.rerun()
            except broker.bridge.DemoError as exc:
                st.error(str(exc))
    if stop_col.button("Stop new entries", disabled=not config.get("enabled"),
                       use_container_width=True):
        auto.stop()
        st.rerun()
    st.caption("Stopping entries leaves the worker's exit checks and attached broker stops in place.")

    components.section("Recent automation activity")
    recent_events = services.events(broker, limit=30)
    if recent_events:
        st.dataframe([{"Time (UTC)": components.utc(item.get("time")),
                       "Type": item.get("kind"), "Message": item.get("message")}
                      for item in recent_events], hide_index=True, width="stretch")
    else:
        components.empty("No automation events", "Connection, scans, and execution events will appear here.")
    telegram = broker.module("telegram_notifications")
    configured = all(telegram.configuration().values())
    st.caption("Telegram decision notifications: " + ("Configured" if configured else "Not configured"))
