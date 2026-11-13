# ScalpLab

ScalpLab is a local Python research and trading app for Exness GOLD/XAUUSD. The active interface is `dashboard.py`. It reads broker candles and quotes through Windows MetaTrader 5, evaluates a fixed gold strategy, checks sourced AI news, and supports manual and automatic trading on Exness demo and real accounts. `dashboard_legacy.py` and the `python -m scalp_lab` CLI retain the older, separate Alpaca stock research workflow.

The initial gold strategy failed its historical cost test. Real-account entries require both a passing evaluation and forward paper validation. The dashboard backtest alone does not certify forward validation. The demo research override remains available on demo accounts. See [GOLD_RESEARCH.md](GOLD_RESEARCH.md) for the rules and results.

## Software to install

- **Windows 10/11 and Python 3.11 or newer.** Install Python from [python.org](https://www.python.org/downloads/windows/) with the Python launcher (`py`) enabled. Git is needed only if you are cloning the repository.
- **Exness MetaTrader 5 desktop terminal and an Exness demo or real account** for the active gold dashboard. Install MT5 from Exness, sign in locally, and keep the terminal open. You can run unit tests and the legacy synthetic-data demo without MT5.
- **One news provider** for gold decisions: [Ollama](https://ollama.com/download/windows) on the same computer, or an OpenAI API key. Ollama avoids a cloud key but requires the configured model to be installed. A missing news provider blocks news-gated entries.

## Install and run (PowerShell)

Open PowerShell in the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-mt5.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` for your news provider. For local Ollama, set `EXNESS_NEWS_PROVIDER=ollama`, run `ollama pull qwen2.5:7b-instruct`, and start Ollama. For cloud news, set `EXNESS_NEWS_PROVIDER=openai` and provide your own `OPENAI_API_KEY`. Existing `IC_MARKETS_` and `XM_` news settings still work as fallbacks. If MT5 auto-discovery opens another installation, set `EXNESS_MT5_PATH` to the full path to the Exness `terminal64.exe`. The dashboard and worker both read this setting. Do not commit `.env` or paste credentials into issues or logs.

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

When switching brokers, stop the previous dashboard and background worker before launching this version. Log in to the Exness MT5 desktop terminal with the account number, trading password, and server listed in your Exness Personal Area. Enter the trading credentials in MT5. [Exness MT5 login guide](https://get.exness.help/hc/en-us/articles/360011514572-MT5-Trading-guide-Desktop)

Click **Connect Exness MT5** and choose the gold instrument listed on your account, for example `XAUUSDm` on Standard. The dashboard uses UTC for Exness quotes and candles. Run **Fetch gold history and evaluate** to create a fresh Exness evaluation for the exact instrument. Previous broker reports are historical research only. [Exness symbol suffixes](https://get.exness.help/hc/en-us/articles/360014560220-Account-type-suffixes) · [Exness MT5 time zone](https://get.exness.help/hc/en-us/articles/360014390760-What-is-the-default-timezone-set-for-MetaTrader)

If automation still shows a previous account, stop it and select **Use connected real account and gold instrument** or its demo equivalent. Real-account entries require a passing historical evaluation. The historical validation override and Tesla stop-risk exception apply only to demo accounts. The existing news, sizing, and risk checks apply to gold entries. Keep the dashboard and MT5 open for timed exit management.

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

For historical Alpaca stock data, fill `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`, then use `python -m scalp_lab fetch --help`. Alpaca data is not the gold broker feed and does not authorize Exness orders.

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


## Forward execution review

The dashboard's forward-performance panel reads the current account's bot journal.
It reports reconciled closed-trade net P&L (including recorded commission, swap and
fees), stop-risk-normalized returns, submission latency and unresolved outcomes.
Its drawdown uses closed results in entry order, not marked-to-market equity.
Open trades and signals are not counted as completed trades. Download the JSON
report to retain the evidence from each test period. This report provides execution
diagnostics. Entry authorization uses the strategy validation gate. Worker startup
retries transient MT5 initialization failures three times.
