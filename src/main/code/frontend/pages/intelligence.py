"""Separate sourced news, model interpretation, and chart evidence."""
import time
import streamlit as st

from frontend import components, services
from .common import page_state


def render():
    components.heading("Analysis / evidence", "AI market intelligence",
                       "Current chart conditions and cited news. No invented confidence score.")
    state = page_state()
    if state is None:
        return
    broker, identity, account, instruments, instrument, offset = state
    try:
        result, pending = services.analysis(broker, identity, instrument.name, offset)
    except (broker.bridge.DemoError, ValueError) as exc:
        st.error(str(exc))
        return
    if pending:
        st.warning(pending)
        return
    news = result.get("news") or {}
    components.metrics([
        ("Decision", result.get("action", "—")),
        ("Regime", result.get("regime", "—")),
        ("Setup", result.get("setup", "—")),
        ("News status", news.get("status", "Unavailable")),
    ])
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        components.section("Technical assessment")
        reasons = result.get("reasons") or ["No qualifying entry pattern on the current completed candle."]
        st.write("**Primary reason:** " + reasons[0])
        for reason in reasons[1:]:
            st.caption(reason)
        st.caption("Completed candle age: " + components.number(result.get("candle_age_seconds"), 0, "s"))
        with st.expander("All chart and execution checks"):
            st.dataframe(result.get("checks", []), hide_index=True, width="stretch")
    with right:
        components.section("Model interpretation")
        st.write(news.get("reason") or "No current AI interpretation is available.")
        if news.get("status") == "ready":
            st.caption("Model direction: " + str(news.get("direction") or "NEUTRAL"))
            st.caption("High-risk news: " + ("Yes" if news.get("high_risk") else "No"))
        else:
            st.warning("News evidence is not ready. Entry checks remain blocked.")
        checked = news.get("checked_at")
        st.caption("Reviewed: " + components.utc(checked))
        if checked and time.time() > news.get("expires_at", 0):
            st.warning("News review is stale.")
    components.section("Cited source headlines")
    articles = news.get("articles") or []
    if articles:
        cited = set(news.get("evidence_ids") or [])
        for article in articles:
            label = article.get("title") or "Untitled source"
            published = components.utc(article.get("published_at"))
            st.markdown(f"**{label}**")
            st.caption(("Cited by model · " if article.get("id") in cited else "Source · ") + published)
            if article.get("url"):
                st.link_button("Open source", article["url"])
    else:
        components.empty("No sourced headlines", "The news service has no current, timestamped articles to show.")
    with st.expander("Data coverage and limitations"):
        st.dataframe([
            {"Input": "MT5 M1/M5/M15 price and spread", "Status": "Broker data"},
            {"Input": "VWAP and relative volume", "Status": "Tick-volume proxies"},
            {"Input": "Public gold and macro headlines", "Status": "Timestamped sources when available"},
            {"Input": "DXY, yields, economic calendar", "Status": "Not connected"},
            {"Input": "COMEX depth, volume, open interest", "Status": "Not connected"},
            {"Input": "Calibrated win probability", "Status": "Not available"},
        ], hide_index=True, width="stretch")
