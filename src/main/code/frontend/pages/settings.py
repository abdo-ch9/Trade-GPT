"""Non-secret configuration and system diagnostics."""
import os
import streamlit as st

from frontend import components
from .common import page_state


def render():
    components.heading("System / local", "Settings",
                       "Connection and provider settings are stored locally in .env.")
    state = page_state(need_connection=False)
    broker, identity, account, instruments, instrument, offset = state
    components.section("Broker connection")
    env_name = "EXNESS_MT5_PATH" if broker.is_exness else "IC_MARKETS_MT5_PATH"
    path = os.getenv(env_name)
    if not path:
        from dotenv import dotenv_values
        path = dotenv_values(broker.module("paths").ENV_FILE).get(env_name)
    components.value_table([
        {"Setting": "Broker", "Value": broker.name},
        {"Setting": "Account mode", "Value": broker.mode(account).upper() if account else "Disconnected"},
        {"Setting": "MT5 terminal path", "Value": path or "Automatic discovery"},
        {"Setting": "Gold instrument", "Value": instrument.name if instrument else "Not selected"},
        {"Setting": "Server time offset", "Value": f"UTC + {offset}"},
    ])
    st.caption("Set each broker's terminal path in the root .env file when both MT5 installations are present. The dashboard and worker use the same setting.")

    components.section("AI news and notifications")
    news = broker.module("xm_news")
    config = news.configuration()
    available, reason = news.connection_status(config)
    components.value_table([
        {"Setting": "Provider", "Value": config["provider"]},
        {"Setting": "Model", "Value": config["model"]},
        {"Setting": "Service", "Value": "Ready" if available else reason},
        {"Setting": "Cloud key", "Value": "Configured" if config.get("key") else "Not configured"},
        {"Setting": "Telegram", "Value": "Configured" if all(broker.module("telegram_notifications").configuration().values()) else "Not configured"},
    ])
    st.caption("Credentials are never displayed. Edit .env locally and restart the app after changing provider settings.")

    components.section("Risk configuration · read only")
    automation_config = broker.auto.settings()
    budget_rule = (f"{automation_config['daily_loss_eur']:.2f} EUR fixed" if automation_config.get("daily_loss_eur") is not None
                   else f"{automation_config['daily_loss_usd']:.2f} USD fixed" if automation_config.get("daily_loss_usd") is not None
                   else f"{automation_config.get('daily_loss_fraction', .01) * 100:g}% of baseline equity")
    components.value_table([{"Setting": "Automatic entries", "Value": "Enabled" if automation_config.get("enabled") else "Stopped"},
                  {"Setting": "Trade size", "Value": f"{automation_config.get('lots', .01):g} lot"},
                  {"Setting": "Daily loss limit", "Value": budget_rule},
                  {"Setting": "Maximum entry attempts", "Value": automation_config.get("max_entries", 5)},
                  {"Setting": "Execution validation", "Value": "Enforced by broker backend"}])

    components.section("Display preferences")
    st.selectbox("Default chart timeframe", ("M1", "M5", "M15"), key="display_timeframe")
    components.section("Diagnostics")
    worker = broker.module("gold_worker").status()
    st.dataframe([
        {"Check": "Worker heartbeat", "Status": components.age(worker.get("heartbeat"))},
        {"Check": "Scanner", "Status": worker.get("scanner", "Not started")},
        {"Check": "Exit watchdog", "Status": worker.get("exit_error") or "No current error"},
        {"Check": "Automation", "Status": "Enabled" if broker.auto.settings().get("enabled") else "Stopped"},
    ], hide_index=True, width="stretch")
    st.caption("Edit fixed trade settings in Automation center. Broker modules enforce limits and order permissions.")
