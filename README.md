# ScalpLab

ScalpLab is a local Python research app for IC Markets demo GOLD/XAUUSD. The active interface is `dashboard.py`; it reads broker candles and quotes through the Windows MetaTrader 5 terminal, evaluates a fixed gold strategy, checks sourced AI news, and supports reviewed demo orders. `dashboard_legacy.py` and the `python -m scalp_lab` CLI retain the older, separate Alpaca stock research workflow. The MT5 integration accepts IC Markets demo accounts only; real-money accounts are always blocked.

The initial gold strategy failed its historical cost test, so normal validation blocks automatic entries. An explicit demo research override exists, but it does not establish profitability. Do not interpret a signal or a demo fill as evidence of profitability. See [GOLD_RESEARCH.md](GOLD_RESEARCH.md) for the rules, results, and limitations. The app is for local research and demo accounts only.

## Software to install

- **Windows 10/11 and 64-bit Python 3.11–3.14.** Python 3.15 does not currently have a compatible MetaTrader5 package. Install Python from [python.org](https://www.python.org/downloads/windows/) with the Python launcher (`py`) enabled. Git is needed only if you are cloning the repository.
- **IC Markets MetaTrader 5 desktop terminal and an IC Markets demo account** for the active gold dashboard. Install MT5 from IC Markets, sign in locally, and keep the terminal open. The Python connector does not accept a live account. You can run unit tests and the legacy synthetic-data demo without MT5.
- **One news provider** for gold decisions: [Ollama](https://ollama.com/download/windows) on the same computer, or an OpenAI API key. Ollama avoids a cloud key but requires the configured model to be installed. A missing news provider blocks news-gated entries.

## Install and run (PowerShell)

Open PowerShell in the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-mt5.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` for your news provider. For local Ollama, set `IC_MARKETS_NEWS_PROVIDER=ollama`, run `ollama pull qwen2.5:7b-instruct`, and start Ollama. For cloud news, set `IC_MARKETS_NEWS_PROVIDER=openai` and provide your own `OPENAI_API_KEY`. Existing `XM_`-prefixed news settings remain supported as backward-compatible aliases. Do not commit `.env` or paste credentials into issues or logs.

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

In the browser, select the timestamp offset shown by the IC Markets MT5 server, connect the IC Markets **demo** terminal, and choose the exact USD gold instrument. Run a fresh historical evaluation using IC Markets data before interpreting signals: previous XM evaluations do not authorize entries on the new broker, and spreads, contract details and costs may differ. Manual demo orders require an explicit review and click. Automatic demo trading has additional risk and validation gates and should remain off until its behavior has been checked in the connected demo account. The dashboard and its worker run locally; keep the app and MT5 open for timed exit management.

## Tests and optional legacy workflow

Run all tests without broker credentials or a terminal:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The older stock pipeline can be checked with synthetic data:

```powershell
.\.venv\Scripts\python.exe -m scalp_lab demo --dir demo_data
.\.venv\Scripts\python.exe -m scalp_lab backtest --bars demo_data/DEMO_bars.csv --news demo_data/DEMO_news.csv --out results_demo
```

For historical Alpaca stock data, fill `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`, then use `python -m scalp_lab fetch --help`. Alpaca data is not the gold broker feed and does not authorize IC Markets orders.

## Repository and local files

`scalp_lab/` holds the engines and integrations; `tests/` holds `unittest` cases. `GOLD_RESEARCH.md` documents the gold study. Market data, model output, evaluation reports, SQLite journals, worker status, logs, and credentials are local runtime files ignored by Git. Do not delete order journals or automation settings during an active demo session. A fresh checkout starts without historical evaluation or saved broker state; the dashboard creates new reports when you run an evaluation.

## Shared dashboard and background news

While automatic demo trading is enabled, the dashboard displays the worker's
account-, instrument- and timestamp-offset-specific snapshot. Display snapshots
expire after 20 seconds and never authorize execution. Quotes, news freshness,
account identity and risk checks remain independently verified before submission.
The snapshot file `gold_dashboard_snapshot.json` is local and ignored by Git.

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
Delivery failures are isolated from trading; local `telegram_notifications.json`
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
