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
    lots = config.get("lots", .01)
    symbols = auto.eligible(instruments, lots)
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
    components.section("Trade settings")
    editable = context_matches and not config.get("enabled")
    selected_lots = st.number_input(
        "Trade size (lots)", min_value=float(instrument.volume_min),
        max_value=float(instrument.volume_max),
        value=float(lots if auto.valid_lots(lots, instrument) else instrument.volume_min),
        step=float(instrument.volume_step), format="%.4f", disabled=not editable,
        key=f"automation_lots_{broker.name}_{lots}")
    if st.button("Save trade size", disabled=not editable or selected_lots == lots,
                 key="save_trade_size"):
        try:
            auto.set_lots(selected_lots)
            services.invalidate_analysis()
            st.rerun()
        except broker.bridge.DemoError as exc:
            st.error(str(exc))
    daily_percent = st.number_input(
        "Daily loss limit (% of starting equity)", min_value=.1, max_value=5.0,
        value=float(config.get("daily_loss_fraction", .01) * 100), step=.1,
        format="%.1f", disabled=not editable,
        key=f"automation_daily_limit_{broker.name}_{config.get('daily_loss_fraction', .01)}")
    attempts = st.number_input(
        "Entry attempts per UTC day", min_value=1, max_value=20,
        value=int(config.get("max_entries", 5)), step=1, disabled=not editable,
        key=f"automation_attempts_{broker.name}_{config.get('max_entries', 5)}")
    limits_changed = (abs(daily_percent - config.get("daily_loss_fraction", .01) * 100) > 1e-9
                      or attempts != config.get("max_entries", 5)
                      or config.get("daily_loss_usd") is not None
                      or config.get("daily_loss_eur") is not None)
    if st.button("Save entry limits", disabled=not editable or not limits_changed,
                 key="save_entry_limits"):
        try:
            auto.set_entry_limits(daily_percent, int(attempts))
            services.invalidate_analysis()
            st.rerun()
        except broker.bridge.DemoError as exc:
            st.error(str(exc))
    st.caption("Bind the account first; stop entries to edit. Saving settings never starts trading.")
    if config.get("daily_loss_usd") is not None or config.get("daily_loss_eur") is not None:
        st.caption("A fixed-currency budget is active. Saving the percentage switches to the percentage budget.")
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
        st.warning(f"Exactly one eligible {lots:g}-lot gold instrument is required.")

    if not broker.is_exness and mode == "demo" and not config.get("enabled"):
        if config.get("allow_unvalidated_demo") is True:
            st.warning("Demo research consent is active. Historical validation is advisory for this demo account; news, risk, and exit checks still apply.")
            if st.button("Revoke demo research consent", key="revoke_demo_research"):
                try:
                    auto.set_demo_research_consent(identity, symbols, offset, False)
                    st.rerun()
                except broker.bridge.DemoError as exc:
                    st.error(str(exc))
        elif not validated:
            st.warning("This strategy failed historical validation. Demo research can still lose the entire demo balance.")
            research_confirmed = st.checkbox(
                "I understand the historical strategy test failed and want to allow unvalidated DEMO research.",
                key="confirm_demo_research")
            if st.button("Allow unvalidated DEMO research",
                         disabled=not (research_confirmed and context_matches and len(symbols) == 1),
                         key="allow_demo_research"):
                try:
                    auto.set_demo_research_consent(identity, symbols, offset, True)
                    st.rerun()
                except broker.bridge.DemoError as exc:
                    st.error(str(exc))

    components.section("Execution permission")
    confirmation = st.checkbox(
        f"I understand Start can submit {mode.upper()} market orders on {broker.name} after all backend checks pass.",
        key="confirm_auto_start")
    live_account_confirmed = True
    if mode == "real":
        st.error(f"LIVE · REAL MONEY · {broker.name} account {account.login}. Automatic orders use real funds.")
        typed_account = st.text_input(
            f"Type account number {account.login} to authorize this LIVE automation session",
            key="confirm_live_account", autocomplete="off")
        live_account_confirmed = typed_account.strip() == str(account.login)
    start_disabled = (config.get("enabled") or not context_matches or not news_ready
                      or not validated or len(symbols) != 1 or not confirmation
                      or not live_account_confirmed)
    start_col, stop_col = st.columns(2)
    if start_col.button(f"Start automatic {mode.upper()} trading", disabled=start_disabled,
                        type="primary", use_container_width=True):
        try:
            auto.arm(identity, symbols, offset, confirm_live=mode == "real")
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
                     disabled=not (confirmation and override_confirmed and live_account_confirmed),
                     key="start_real_holdout_override"):
            try:
                auto.arm(identity, symbols, offset, override_live_validation=True,
                         confirm_live=True)
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
