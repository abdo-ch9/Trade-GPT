# ScalpLab

ScalpLab is a local Python research app for XM demo GOLD/XAUUSD. The active interface is `dashboard.py`; it reads broker candles and quotes through the Windows MetaTrader 5 terminal, evaluates a fixed gold strategy, checks sourced AI news, and supports reviewed demo orders. `dashboard_legacy.py` and the `python -m scalp_lab` CLI retain the older, separate Alpaca stock research workflow. **The broker integration is still XM/MT5; changing brokers requires code and fresh validation.**

The initial gold strategy failed its historical cost test, so normal validation blocks automatic entries. An explicit demo research override exists, but it does not establish profitability. Do not interpret a signal or a demo fill as evidence of profitability. See [GOLD_RESEARCH.md](GOLD_RESEARCH.md) for the rules, results, and limitations. The app is for local research and demo accounts only.

## Software to install

- **Windows 10/11 and Python 3.11 or newer.** Install Python from [python.org](https://www.python.org/downloads/windows/) with the Python launcher (`py`) enabled. Git is needed only if you are cloning the repository.
- **XM MetaTrader 5 desktop terminal and an XM demo account** for the active gold dashboard. Install MT5 from your broker, sign in locally, and keep the terminal open. The Python connector does not accept a live account. You can run unit tests and the legacy synthetic-data demo without MT5.
- **One news provider** for gold decisions: [Ollama](https://ollama.com/download/windows) on the same computer, or an OpenAI API key. Ollama avoids a cloud key but requires the configured model to be installed. A missing news provider blocks news-gated entries.

## Install and run (PowerShell)

Open PowerShell in the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-mt5.txt
Copy-Item .env.example .env
```

Edit `.env` for your news provider. For local Ollama, keep `XM_NEWS_PROVIDER=ollama`, run `ollama pull qwen2.5:7b-instruct`, and start Ollama. For cloud news, set `XM_NEWS_PROVIDER=openai` and provide your own `OPENAI_API_KEY`. Do not commit `.env` or paste credentials into issues or logs.

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

In the browser, select the MT5 timestamp convention, connect the XM **demo** terminal, and choose the exact USD gold instrument. Run the historical evaluation before interpreting signals. Manual demo orders require an explicit review and click. Automatic demo trading has additional risk and validation gates and should remain off until its behavior has been checked in the connected demo account. The dashboard and its worker run locally; keep the app and MT5 open for timed exit management.

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

For historical Alpaca stock data, fill `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`, then use `python -m scalp_lab fetch --help`. Alpaca data is not the gold broker feed and does not authorize XM orders.

## Repository and local files

`scalp_lab/` holds the engines and integrations; `tests/` holds `unittest` cases. `GOLD_RESEARCH.md` documents the gold study. Market data, model output, evaluation reports, SQLite journals, worker status, logs, and credentials are local runtime files ignored by Git. Do not delete order journals or automation settings during an active demo session. A fresh checkout starts without historical evaluation or saved broker state; the dashboard creates new reports when you run an evaluation.
