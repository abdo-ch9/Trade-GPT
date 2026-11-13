# ScalpLab

ScalpLab is a local Python research app for IC Markets demo GOLD/XAUUSD. The active interface is `src/main/code/dashboard.py`; it reads broker candles and quotes through the Windows MetaTrader 5 terminal, evaluates a fixed gold strategy, checks sourced AI news, and supports reviewed demo orders. `src/main/code/dashboard_legacy.py` and the `python -m scalp_lab` CLI retain the older, separate Alpaca stock research workflow. The MT5 integration accepts IC Markets demo accounts only; real-money accounts are always blocked.

The initial gold strategy failed its historical cost test, so normal validation blocks automatic entries. An explicit demo research override exists, but it does not establish profitability. Do not interpret a signal or a demo fill as evidence of profitability. See [GOLD_RESEARCH.md](GOLD_RESEARCH.md) for the rules, results, and limitations. The app is for local research and demo accounts only.

## Software to install

- **Windows 10/11 and 64-bit Python 3.11–3.14.** Python 3.15 does not currently have a compatible MetaTrader5 package. Install Python from [python.org](https://www.python.org/downloads/windows/) with the Python launcher (`py`) enabled. Git is needed only if you are cloning the repository.
- **IC Markets MetaTrader 5 desktop terminal and an IC Markets demo account** for the active gold dashboard. Install MT5 from IC Markets, sign in locally, and keep the terminal open. The Python connector does not accept a live account. You can run unit tests and the legacy synthetic-data demo without MT5.
- **One news provider** for gold decisions: [Ollama](https://ollama.com/download/windows) on the same computer, or an OpenAI API key. Ollama avoids a cloud key but requires the configured model to be installed. A missing news provider blocks news-gated entries.

## Install and run on Windows

Open PowerShell in the repository folder and run:

```powershell
.\install.cmd
.\run.cmd
```

You can also double-click `install.cmd` and `run.cmd`. The `.cmd` launchers handle Windows PowerShell script restrictions for this process. `run.cmd` installs missing Python packages when needed. The PowerShell entry points are `install.ps1` and `run.ps1`; `run.cmd -Check` checks prerequisites without launching the dashboard. If you only need the older research CLI and tests, use `install.cmd -ResearchOnly` to skip the MT5 connector.

The installer selects an installed 64-bit Python 3.11–3.14, creates `.venv` in the project root, installs dependencies, registers the source package in that environment, and copies `.env.example` to root `.env` only when `.env` is absent. An incompatible environment is moved to an ignored folder under `lib`. The upgrade waits for any open MT5 positions to close before migrating an active worker. If no compatible Python is installed, the script explains what to install. It preserves existing credentials and local research records.

Edit `.env` for your news provider. For local Ollama, set `IC_MARKETS_NEWS_PROVIDER=ollama` and install `qwen2.5:7b-instruct` with `ollama pull qwen2.5:7b-instruct`; `run.cmd` starts the installed Ollama service if needed. For cloud news, set `IC_MARKETS_NEWS_PROVIDER=openai` and provide your own `OPENAI_API_KEY`. Existing `XM_`-prefixed news settings remain supported as backward-compatible aliases. Do not commit `.env` or paste credentials into issues or logs.

In the browser, select the timestamp offset shown by the IC Markets MT5 server, connect the IC Markets **demo** terminal, and choose the exact USD gold instrument. Run a fresh historical evaluation using IC Markets data before interpreting signals: previous XM evaluations do not authorize entries on the new broker, and spreads, contract details and costs may differ. Manual demo orders require an explicit review and click. Automatic demo trading has additional risk and validation gates and should remain off until its behavior has been checked in the connected demo account. The dashboard and its worker run locally; keep the app and MT5 open for timed exit management.

## Tests and optional legacy workflow

Run all tests without broker credentials or a terminal:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s src/test/code/tests -v
```

The older stock pipeline can be checked with synthetic data:

```powershell
.\.venv\Scripts\python.exe -m scalp_lab demo
.\.venv\Scripts\python.exe -m scalp_lab backtest --bars lib/demo_data/DEMO_bars.csv --news lib/demo_data/DEMO_news.csv --out lib/results_demo
```

For historical Alpaca stock data, fill `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`, then use `python -m scalp_lab fetch --help`. Alpaca data is not the gold broker feed and does not authorize IC Markets orders.

## Repository and local files

`src/main/code/dashboard.py` is the active Streamlit entry point. In `src/main/code/scalp_lab/`, `gold.py` evaluates chart rules, `mt5_demo.py` handles broker checks, `auto_demo.py` owns automation and order execution, `auto_demo_ui.py` renders its controls, and `gold_worker.py` runs the scanner and exit watchdog. The older Alpaca workflow remains in the other modules and `src/main/code/dashboard_legacy.py`. `src/test/code/tests/` holds `unittest` cases. `GOLD_RESEARCH.md` documents the gold study. Root `.venv` and `.env` hold the ignored local environment and credentials. `lib/` holds ignored market data, model output, evaluation reports, SQLite journals, worker status, logs, and history. Do not delete order journals or automation settings during an active demo session. A fresh checkout starts without historical evaluation or saved broker state; the dashboard creates new reports when you run an evaluation.

## Shared dashboard and background news

While automatic demo trading is enabled, the dashboard displays the worker's
account-, instrument- and timestamp-offset-specific snapshot. Display snapshots
expire after 20 seconds and never authorize execution. Quotes, news freshness,
account identity and risk checks remain independently verified before submission.
The snapshot file `lib/gold_dashboard_snapshot.json` is local and ignored by Git.

News refresh runs in a background thread. The scanner continues calculating chart
conditions while news loads; missing or expired evidence still blocks entries.
The status panel shows watchdog health, scan/news ages, daily budget headroom and
entry attempts. Risk headroom is indicative and is rechecked before submission.


## Telegram decision notifications

Create a bot with Telegram's @BotFather, open your bot and send `/start`.
Add these values to your local, ignored `.env` file (never commit the token):

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_private_chat_id
```

Obtain your chat ID from the `message.chat.id` field returned by the Telegram
Bot API `getUpdates` after messaging your bot. Keep token-bearing URLs private.
The running gold worker reads these settings automatically. On first activation,
it skips old events and starts with future decisions. Only decisions with BUY or SELL chart direction are sent, including blocked
directional setups. No-setup and directionless decisions are skipped; repeated identical decisions are
suppressed across worker restarts. Messages show indicative levels and reasons,
and do not confirm broker fills. Notifications require the local worker to run.
Delivery failures are isolated from trading; local `lib/telegram_notifications.json`
records delivery status. Failed requests are retried; an ambiguous timeout may
produce a duplicate message. Events older than five minutes are not delivered.
Remove either setting to disable notifications.


## Forward demo review

The dashboard's forward-performance panel reads the current account's bot journal.
It reports reconciled closed-trade net P&L (including recorded commission, swap and
fees), stop-risk-normalized returns, submission latency and unresolved outcomes.
Its drawdown uses closed results in entry order, not marked-to-market equity.
Open trades and signals are not counted as completed trades. Download the JSON
report to retain the evidence from each test period. These diagnostics do not
validate profitability or authorize live trading; the demo-only broker block stays
in place. Worker startup retries transient MT5 initialization failures three times.
