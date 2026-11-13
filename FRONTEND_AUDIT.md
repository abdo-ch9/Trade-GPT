# Frontend audit and feature map

The active entry point is `src/main/code/dashboard.py`. Previously it selected one of two broker-specific, single-screen dashboards (`dashboard_ic.py` and `dashboard_exness.py`). Both rendered account connection, live research, worker status, risk, execution controls, news, historical evaluation, and forward reports in one long page. The broker backends remain separate: `scalp_lab/` for IC Markets and `scalp_lab_exness/` for Exness. Both use MetaTrader 5, broker-specific validation, separate journals under ignored `lib/`, and background workers. The old stock workflow remains in `dashboard_legacy.py`.

The redesign places presentation in `frontend/`. `context.py` owns broker selection and session identity; `services.py` adapts read-only broker data and starts historical research; `components.py` and `styles.py` provide shared visual elements. Page modules never implement signal, risk, stop/target, or order rules. Only the existing broker modules submit orders, and only after the user clicks their controls or explicitly starts automation.

| Existing capability | New location |
| --- | --- |
| Account connection, equity, margin, daily P&L, exposure, health | Dashboard; broker selector in sidebar |
| M1 research chart, indicators, quote, proposed levels, manual execution | Trading terminal |
| AI news, evidence, citations, rejection checks | AI market intelligence |
| Historical evaluation, validation, research CSV and report | Strategy & backtesting |
| Budget, attempts, reserved stop risk, broker constraints | Risk management |
| Worker, scanner, exit watchdog, entry start/stop, Telegram status | Automation center |
| MT5 positions/orders, bot journal, saved decisions, events, downloads | Trade history & analytics |
| Non-secret configuration and diagnostics | Settings |

The former broker-specific dashboard files are retained for reference while the new pages are verified with both broker terminals. They are no longer imported by the entry point. The backend packages and their trading parameters were not changed. Live data still requires a signed-in Windows MT5 terminal; missing news or failed strategy validation continues to block automatic entries.
