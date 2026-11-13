"""Small, reusable presentation helpers with no trade execution."""
from datetime import datetime, timezone
import time
import streamlit as st


def heading(kicker, title, subtitle=""):
    st.markdown(f'<div class="terminal-eyebrow">{kicker}</div>', unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="terminal-subtitle">{subtitle}</p>', unsafe_allow_html=True)


def section(label):
    st.markdown(f'<div class="terminal-section">{label}</div>', unsafe_allow_html=True)


def empty(title, detail):
    with st.container(border=True):
        st.subheader(title)
        st.caption(detail)


def number(value, digits=2, unit=""):
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:,.{digits}f}{(' ' + unit) if unit else ''}"


def age(stamp):
    if not isinstance(stamp, (int, float)) or stamp <= 0:
        return "Waiting"
    seconds = max(0, time.time() - stamp)
    return f"{seconds:.0f}s ago" if seconds < 120 else f"{seconds / 60:.0f}m ago"


def utc(stamp):
    if not isinstance(stamp, (int, float)):
        return "—"
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%d %b %Y · %H:%M UTC")


def metrics(items):
    for start in range(0, len(items), 4):
        group = items[start:start + 4]
        columns = st.columns(len(group), gap="small")
        for column, (label, value) in zip(columns, group):
            column.metric(label, value)


def value_table(rows):
    """Render read-only label/value rows with an Arrow-compatible Value column."""
    display_rows = [
        {**row, "Value": "—" if row["Value"] is None else str(row["Value"])}
        for row in rows
    ]
    st.dataframe(display_rows, hide_index=True, width="stretch")


def status_bar(broker, account, mode, worker):
    connected = account is not None
    fresh = 0 <= time.time() - worker.get("heartbeat", 0) < 15
    account_label = (f"{mode.upper()} · {account.login}" if connected else "Disconnected")
    worker_label = "Online" if fresh and worker.get("scanner_alive") else "Unavailable"
    worker_class = "good" if fresh and worker.get("scanner_alive") else "warn"
    st.markdown(
        f'<div class="terminal-status is-{mode}">'
        f'<span>Broker <strong>{broker.name}</strong></span>'
        f'<span>Environment <strong class="environment-label">{mode.upper()}</strong></span>'
        f'<span>Account <strong>{account_label}</strong></span>'
        f'<span>Worker <strong class="{worker_class}">{worker_label}</strong></span>'
        '</div>', unsafe_allow_html=True)
