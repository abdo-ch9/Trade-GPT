"""A restrained dark data-terminal visual system using Streamlit-native controls."""
import streamlit as st


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root { color-scheme: dark; --terminal-chrome-height: 3.75rem; --surface: #15212a; --line: #2a3a43; --muted: #a8bac2; }
html { scroll-behavior: smooth; }
body, [data-testid="stApp"] { background: #0d1219; color: #e8edf1; font-family: 'Geist', 'Segoe UI', sans-serif; }
[data-testid="stAppViewContainer"] { background: radial-gradient(ellipse at 75% -20%, #1c343a 0%, #111a21 40%, #0d1219 78%); }
[data-testid="stHeader"] { background: transparent; height: var(--terminal-chrome-height); }
[data-testid="stSidebar"] { background: #111a22; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] * { font-size: .93rem; }
main[data-testid="stMain"] .block-container { max-width: 1540px; padding-top: calc(var(--terminal-chrome-height) + .35rem); padding-bottom: 3rem; }
h1, h2, h3 { font-family: 'Geist', 'Segoe UI', sans-serif; letter-spacing: -.04em; }
h1 { font-size: clamp(1.8rem, 2.8vw, 2.8rem) !important; font-weight: 700 !important; max-width: 72rem; line-height: 1.12 !important; }
h2, h3 { font-weight: 700 !important; }
p, label { line-height: 1.5; }
[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 1rem 1.1rem; min-width: 0; }
[data-testid="stMetricLabel"] { color: var(--muted); font-size: .78rem; letter-spacing: .01em; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], .terminal-number { font-family: 'IBM Plex Mono', Consolas, monospace; font-variant-numeric: tabular-nums; }
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: var(--line) !important; }
button { transition: background-color .2s ease, transform .15s ease, border-color .2s ease; }
button:active { transform: translateY(1px); }
button:focus-visible, a:focus-visible { outline: 2px solid #85b4b0 !important; outline-offset: 2px; }
.stButton button[kind="primary"] { font-weight: 700; color: #07181a; background: #a2d6c4; border-color: #a2d6c4; }
.stButton button[kind="primary"]:hover { background: #b9e6d4; border-color: #b9e6d4; color: #07181a; }
.terminal-eyebrow { color: #88a9aa; text-transform: uppercase; letter-spacing: .13em; font: 600 .69rem 'IBM Plex Mono', monospace; margin: 0 0 .4rem; }
.terminal-subtitle { color: var(--muted); max-width: 72ch; margin-top: -.2rem; }
.terminal-status { display: flex; gap: .6rem 1.4rem; align-items: center; flex-wrap: wrap; padding: .8rem 1rem; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; margin-bottom: 1.35rem; font-size: .82rem; }
.terminal-status span { min-width: 0; overflow-wrap: anywhere; }
.terminal-status strong { color: #e8edf1; font-weight: 600; }
.terminal-status .good { color: #8dbba3; } .terminal-status .warn { color: #e2bb83; } .terminal-status .bad { color: #dd9296; }
.terminal-status.is-real { background: #251a20; border-color: #975062; box-shadow: inset 3px 0 #e7899b; }
.terminal-status.is-real .environment-label { color: #ffadb8; }
.terminal-status.is-demo .environment-label { color: #9fdac3; }
.terminal-section { color: #a7c0c5; text-transform: uppercase; letter-spacing: .1em; font: 600 .73rem 'IBM Plex Mono', monospace; margin: 1.9rem 0 .8rem; }
@media (max-width: 900px) { main[data-testid="stMain"] .block-container { padding-right: .8rem; padding-left: .8rem; padding-bottom: 2rem; } [data-testid="stMetric"] { padding: .7rem; } }
@media (max-width: 600px) { .terminal-status { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .4rem .75rem; } .terminal-status span:last-child { grid-column: 1 / -1; } h1 { font-size: 1.8rem !important; } }
</style>
"""


def apply():
    # Streamlit places style-only st.html content outside the main flow.
    st.html(CSS)
