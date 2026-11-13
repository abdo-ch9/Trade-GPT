"""A restrained dark data-terminal visual system using Streamlit-native controls."""
import streamlit as st


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { color-scheme: dark; --terminal-chrome-height: 3.75rem; }
html { scroll-behavior: smooth; }
body, [data-testid="stApp"] { background: #0d1219; color: #e8edf1; font-family: 'Manrope', 'Segoe UI', sans-serif; }
[data-testid="stAppViewContainer"] { background: radial-gradient(ellipse at 75% -20%, #172b35 0%, #0d1219 43%); }
[data-testid="stHeader"] { background: transparent; height: var(--terminal-chrome-height); }
[data-testid="stSidebar"] { background: #111a22; border-right: 1px solid #26333d; }
[data-testid="stSidebar"] * { font-size: .93rem; }
main[data-testid="stMain"] .block-container { max-width: 1540px; padding-top: var(--terminal-chrome-height); padding-bottom: 3rem; }
h1, h2, h3 { font-family: 'Manrope', 'Segoe UI', sans-serif; letter-spacing: -.045em; }
h1 { font-size: clamp(1.7rem, 2.6vw, 2.55rem) !important; font-weight: 800 !important; }
h2, h3 { font-weight: 700 !important; }
p, label { line-height: 1.5; }
[data-testid="stMetric"] { background: #15212a; border: 1px solid #263741; border-radius: 10px; padding: .85rem 1rem; }
[data-testid="stMetricLabel"] { color: #91a5ae; font-size: .75rem; letter-spacing: .025em; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], .terminal-number { font-family: 'IBM Plex Mono', Consolas, monospace; font-variant-numeric: tabular-nums; }
[data-testid="stDataFrame"] { border: 1px solid #263741; border-radius: 8px; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: #263741 !important; }
button { transition: background-color .2s ease, transform .15s ease, border-color .2s ease; }
button:active { transform: translateY(1px); }
button:focus-visible, a:focus-visible { outline: 2px solid #85b4b0 !important; outline-offset: 2px; }
.terminal-eyebrow { color: #88a9aa; text-transform: uppercase; letter-spacing: .13em; font: 600 .69rem 'IBM Plex Mono', monospace; margin: 0 0 .4rem; }
.terminal-subtitle { color: #91a5ae; max-width: 68ch; margin-top: -.35rem; }
.terminal-status { display: flex; gap: 1rem; flex-wrap: wrap; padding: .65rem .9rem; background: #15212a; border: 1px solid #263741; border-radius: 8px; margin-bottom: 1.2rem; font-size: .79rem; }
.terminal-status span { min-width: 0; overflow-wrap: anywhere; }
.terminal-status strong { color: #e8edf1; font-weight: 600; }
.terminal-status .good { color: #8dbba3; } .terminal-status .warn { color: #e2bb83; } .terminal-status .bad { color: #dd9296; }
.terminal-section { color: #8ea5ae; text-transform: uppercase; letter-spacing: .12em; font: 600 .72rem 'IBM Plex Mono', monospace; margin: 1.6rem 0 .65rem; }
@media (max-width: 900px) { main[data-testid="stMain"] .block-container { padding-right: .8rem; padding-left: .8rem; padding-bottom: 2rem; } [data-testid="stMetric"] { padding: .7rem; } }
@media (max-width: 600px) { .terminal-status { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .35rem .75rem; } .terminal-status span:last-child { grid-column: 1 / -1; } }
</style>
"""


def apply():
    # Streamlit places style-only st.html content outside the main flow.
    st.html(CSS)
