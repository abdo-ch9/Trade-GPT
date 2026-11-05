# ScalpLab — gold research desk

The active `dashboard.py` now focuses on XM **GOLD / XAUUSD**. See
[GOLD_RESEARCH.md](GOLD_RESEARCH.md) for implemented rules, actual historical
results, cost assumptions and remaining requirements. Start with
`python -m streamlit run dashboard.py`, then connect the XM demo terminal.
The first gold strategy failed its historical cost tests; automatic entries
remain blocked. Existing broker positions and orders were left unchanged.

The following sections document the archived multi-asset version, available in
`dashboard_legacy.py`; they do not describe the active gold strategy.

**Educational research software with optional manual XM MT5 demo orders. Real-money accounts are blocked. No verified profitable model.**

This is a meaningful step up from a random directional predictor, but **it is not a production-quality or independently verified 80%-win-rate model**. An honest model can and often should output **NO SIGNAL** for long periods. Full run requires a data-provider account and historical bars/news data; no provider credentials are bundled.

## What's actually implemented

- Read-only historical 1-minute US stock bars and stock-related news from documented Alpaca data endpoints, with pagination.
- Read-only real-time US stock WebSocket minute bars and quotes, plus the separate real-time news WebSocket. Save timestamped local recordings and output experimental **paper** signals.
- 19 chronological model features: returns, volatility, bar range, price/volume, turnover, session VWAP deviation, intraday time, quote features when present, 15-minute news features.
- News features never use headlines unavailable at the simulated decision timestamp. For historical publisher timestamps, add a latency buffer (default 60 seconds); this is only a rough proxy, not a substitute for recorded receipt times.
- Optionally classify headlines using `ProsusAI/finbert` (additional dependencies and model-weight license review needed). Default sentiment fallback is a small **lexicon baseline**, not advanced AI.
- Pessimistic intrabar paper outcome assumptions: detect target/stop in the subsequent five 1-minute bars, assume stop first if both touch in the same minute, fill hypothetically at the **next bar's open**, deduct assumed round-trip costs; no trading over sessions or missing 1-minute intervals.
- Separate chronological 60% training, 20% threshold-selection validation and untouched 20% out-of-sample test **by whole market session**. Two gradient-boosting classifiers research long and short outcomes (a research direction label, not a borrowable or executable short position).
- Threshold chosen only using validation **net paper expectancy**, not test win rate; no signals when there aren't enough validation observations.
- Report trade count, after-cost net bps, win rate, 95% Wilson confidence lower bound, Brier score, AUC, max drawdown, test session dates.
- Streamlit research dashboard with automatic watchlist data updates.
- Automatic abstention when the model cannot establish a minimally supported threshold; no trades on synthetic data is a legitimate result.

## Install (Windows PowerShell)

Python 3.11+ recommended. Open PowerShell in this folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### 1. Test the pipeline with FAKE data (no API key)

```powershell
.\.venv\Scripts\python.exe -m scalp_lab demo --dir demo_data
.\.venv\Scripts\python.exe -m scalp_lab backtest --bars demo_data/DEMO_bars.csv --news demo_data/DEMO_news.csv --out results_demo
```

The fake data is **synthetic and intentionally not proven predictable**. It is useful only to verify end-to-end correctness. You may see 0 test trades, meaning the validation threshold could not be supported.

### 2. Connect a READ-ONLY data feed

Copy `.env.example` to `.env`, enter your market-data credentials (keep private and do not share). The Alpaca integration is read-only. The separate optional XM MT5 panel supports user-clicked demo orders only.

```powershell
Copy-Item .env.example .env
# Edit .env locally
.\.venv\Scripts\python.exe -m scalp_lab fetch --ticker SPY --start 2026-01-01 --end 2026-10-31 --feed iex --dir data
```

If your provider plan permits consolidated SIP coverage, specify `--feed sip`. IEX is only one exchange, not the full US tape. Market data, subscriptions, rates and permissions depend on your data plan.

### 3. Train and hold out truly unseen trading sessions

```powershell
.\.venv\Scripts\python.exe -m scalp_lab backtest --symbol SPY --bars data/SPY_bars.csv --news data/SPY_news.csv --out results --horizon 5 --take-profit-bps 18 --stop-bps 12 --roundtrip-cost-bps 6
```

The 18 bps take-profit, 12 bps stop and 6 bps total assumed cost are **examples, not market estimates**. Actual bid/ask spreads, slippage, liquidity, fees and adverse selection vary dramatically; measure them before trusting paper results. If there are no quotes in your historical CSV, spread and quote imbalance cannot be backtested and zero-filled fields are *not evidence* of free execution.

Optional richer sentiment:

```powershell
.\.venv\Scripts\python.exe -m pip install transformers torch
.\.venv\Scripts\python.exe -m scalp_lab backtest --symbol SPY --bars data/SPY_bars.csv --news data/SPY_news.csv --out results_finbert --finbert
```

This downloads a third-party model. Review the FinBERT **model weights license** (Hugging Face presently lists CC BY-NC-SA 4.0) before use. FinBERT predicts *news sentiment*, not future stock returns.

### 4. Live monitor — paper observations only

```powershell
.\.venv\Scripts\python.exe -m scalp_lab monitor --ticker SPY --models results --out live --feed iex
```

The monitor records local `bars.jsonl`, `minute_quotes.jsonl`, `news.jsonl`, `paper_signals.jsonl`. It shows only experimental directional labels. The websocket integration was written against Alpaca docs but **cannot be verified end-to-end without your own market-data credentials**. It has no live trade execution. Stop with Ctrl+C. It will abstain without sufficient warmup bars, stale data, or a qualifying threshold.

### 5. Optional dashboard

The dashboard opens a trained asset when available. All six built-in real assets
(SPY, QQQ, AAPL, MSFT, NVDA, TSLA) update independently of the selected ticker.
Selecting a custom ticker adds it to the persistent watchlist. DEMO stays synthetic.

- The screen refreshes every 5 seconds using Streamlit fragments.
- A shared background process polls Alpaca snapshots every 15 seconds.
- Completed minute bars and news refresh roughly every minute, subject to API latency.
- Prices include their original market timestamps. No recent trade is not presented as a fresh price.
- Network failures retry automatically; one invalid ticker does not block the others.
- The updater starts with the dashboard, continues after the browser tab closes, and
  restarts when the dashboard detects it has exited. The computer must stay awake and
  connected. After a computer restart, reopen the dashboard; no Windows startup task is installed.

Live caches are stored in `auto_live/TICKER`; the worker heartbeat and connection
status are in `auto_live/status.json`. The OS lock prevents duplicate updater processes.
The standalone websocket monitor remains available separately, but is not required
for dashboard updates. To start the shared updater without the dashboard:
`python -m scalp_lab.auto_update`.

Each asset needs its own report in `results_TICKER`, trained with
`backtest --symbol TICKER`, before paper signals can be calculated. The updater
picks up new reports automatically; it does not retrain models or modify historical
training CSVs. The dashboard distinguishes MODEL NOT READY, MODEL DISABLED, WAITING FOR FRESH
DATA, MODEL WARMING UP, and an evaluated NO TRADE decision. Only fresh, qualified
signals show BUY / LONG or SELL / SHORT.

To prepare missing watchlist models without replacing existing models, run
`python -m scalp_lab.prepare_watchlist`. To explain abstention using validation data
without changing thresholds, run `python -m scalp_lab.audit_models`. Audit counts
appear in the dashboard when `auto_live/model_diagnostics.json` exists.
Paper signals use fresh completed regular-session bars; the latest observed price
may include extended hours and is displayed separately from signal entry references.

The planner defaults to dynamic distances, recomputed from the latest 31 contiguous,
completed regular-session minute bars: 14-bar mean true range, 30-return volatility,
five-minute velocity, relative volume, holding horizon, and cost/spread floors when
available. Stops widen with volatility; targets also include a capped velocity allowance.
Missing bars require warmup; old bars are explicitly labeled as a historical preview.
News and order-book depth do not enter this heuristic. It is not an optimized or
backtested exit strategy. The existing classifier probabilities and live signal levels
still correspond to the fixed distances used during training.

Manual distance overrides and a manual entry price remain available. Automatic entry
tracking follows the latest observed price. Planner changes do not retrain the model.
Relative data folders resolve from the project folder.

The integrated chart supports 1-, 5-, and 15-minute completed regular-session
candles, zoom/pan, volume, EMA 9/21, a recorded-session VWAP estimate, Wilder RSI 14,
and prior 20-candle range levels. Candle aggregation rejects missing constituent
minutes. Indicators warm up again after gaps; historical readings are labeled stale.
Its bullish/bearish/mixed description is a transparent price-action heuristic, not a
validated trading signal. Optional long/short overlays use dynamic scenario distances
at the last displayed close. They do not change the model or claim an executed entry.

The next strategy research step is to backtest dynamic exits and explicit chart-based
entry rules against the fixed-exit baseline using rolling chronological validation,
measured cost scenarios, and fresh untouched holdouts. Chart indicators alone do not
establish positive expectancy, and repeatedly tuning against previously viewed test
results would invalidate their holdout status.

```powershell
.\.venv\Scripts\python.exe -m pip install "streamlit>=1.49" plotly
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

## Optional XM MT5 demo trade button

1. Install the XM Windows MT5 desktop terminal from your broker's official site:
   https://www.xm.com/mena/mt5. Sign in to your XM **demo** account locally.
2. Install the connector into the same Python used for Streamlit:
   `python -m pip install -r requirements-mt5.txt`.
3. Open **XM demo trade** on the dashboard and choose **Connect to MT5 demo**.
   An optional `terminal64.exe` path selects a specific terminal installation.
   Trading must be permitted by both the terminal and account. Review those
   permissions in MT5 yourself; this application does not change them.
4. Select the exact XM instrument, BUY or SELL, lots, target and stop distances.
   Inspect the ticket's XM bid/ask-based entry, attached exits and estimates.
   Press **Place DEMO ...** once to send that ticket. This is a manual decision,
   independent of a disabled research model.

No password is collected or stored by the dashboard. XM symbols and contract sizes
are not assumed to match Alpaca symbols or share quantities. Target and stop distances
in this execution panel are explicit inputs; cross-feed dynamic planner levels are not
transferred automatically. Quotes expire after 30 seconds. Broker market fills can
still differ from quotes; the pre-send deviation check is not a guaranteed fill limit.

The connector checks demo mode, broker identity, bound account/server, trading
permissions, symbol mode, lot increments, stop distances, current quotes and broker
order validation. Existing positions or pending orders on the selected symbol block
new entries here; position management remains in MT5. A local SQLite attempt ledger
prevents resending a ticket on reruns or duplicate clicks. Ambiguous sends are marked
unknown and never automatically retried; inspect MT5 Trade/History before creating
another ticket. The UI distinguishes full fills, partial fills, accepted orders,
rejections and unknown results.

Keep Streamlit local to your computer; the panel has no remote-user authentication.
Automated tests use a simulated terminal only. Broker execution requires a connected
XM demo terminal and has not been verified by these tests.

## What 80% win rate would actually mean

Define the metric **before** training:

`win rate = number of net-profitable simulated positions / number of completed simulated positions`

- An 80% result over 10 historical positions is too uncertain to trust.
- Require a sufficiently large *untouched* holdout over multiple months and market regimes; this prototype labels `statistically_supported_80pct=true` only with 100+ test trades, positive average P&L and the **95% Wilson lower bound** at 80% or higher. This is a stringent minimum indicator, **not** proof the future will match.
- Also require positive net expectancy, profit factor, drawdown and robustness under higher costs, delays, different assets and changing regimes.
- Never tune model, threshold or stop sizes repeatedly on the untouched test set. Once inspected repeatedly, it is no longer untouched.
- Optional no-signal behavior is essential. It is better to reject low-information conditions than force predictions on every bar.

Example: 8 wins and 2 losses with average win +2 bps and average loss -20 bps yields **80% wins but -2.4 bps/trade** before additional unmodeled costs.

## Major limitations & serious V3 research priorities

1. **Realistic fill simulation**: next-bar open is illustrative, not guaranteed execution. Incorporate bid/ask at decision, latency, order type, book depth, partial fills and impact using historical quote/trade data. Do not use hindsight-filled limit orders.
2. **Reliable historical feeds**: use point-in-time, exchange-complete SIP data for full-market scalping research. Historical news needs *actual first observed timestamp*, plus corrections/republication and duplicate detection.
3. **Scheduled-event flags**: explicit Fed/FOMC, BLS CPI/jobs, Treasury auctions, company earnings, dividends, halts, split/filing times, and circuit breakers; build a pre-announcement calendar and avoid look-ahead. FRED alone is not a live economic calendar.
4. **Market regime models**: separate regular and after-hours, high-volatility and low-volatility sessions, market-open spikes, index/sector relative strength, and cross-market moves (SPY/QQQ/TLT). Start with ablation experiments to prove features add value.
5. **Robust ML**: gradient boosting baseline vs simple momentum/no-model baselines, purged walk-forward retraining, probability calibration on separate folds, grouped/correlated events, honest ablation and drift tests.
6. **News impact model**: FinBERT sentiment is only one feature. Entity mapping, novelty, surprise relative to consensus, source credibility, delivery latency, and whether news was already priced in matter more than raw positive/negative polarity.
7. **Production hardening**: use an exchange calendar for early closes and holidays; formal replays; stream reconnect/dedupe and schema validation; monitor missing bars, clock drift, IEX/SIP feed mismatches, permission changes and stale quotes.
8. **Time horizon**: this system is minute-bar research, not true sub-second/high-frequency trading. Python over typical retail internet cannot compete fairly on ultralow-latency market-making strategies.

## Sources and API docs

- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py
- https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants

- https://plotly.com/python/candlestick-charts/
- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI

- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr

- https://docs.alpaca.markets/us/reference/stocksnapshots-1
- https://docs.streamlit.io/develop/concepts/architecture/fragments

- https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data
- https://docs.alpaca.markets/us/docs/streaming-real-time-news
- https://docs.alpaca.markets/us/reference/stockbarsingle-1
- https://docs.alpaca.markets/us/v1.1/reference/news-3
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://huggingface.co/ProsusAI/finbert

**Research ethics and security:** do not put API secrets in code or share the `.env` file. Loading `paper_models.joblib` is only safe if the model was created locally by your own code (pickle format). The optional MT5 order API enforces demo accounts and explicit user clicks; Alpaca remains read-only. If a service requires an age or account-eligibility check, follow its terms rather than trying to bypass it.
# XM chart and AI news decisions

The active XM panel and automatic scanner now use `scalp_lab/xm_chart.py`. The older local machine-learning code is retained for research/tests but is no longer called by XM chart analysis or automatic execution. Existing Alpaca stock research remains separate.

After connecting the XM demo terminal, select an **Exact XM instrument**. The panel shows **Chart direction**, **Order decision**, and **AI news** separately. It reads up to 361 M1 candles directly from MT5, discards incomplete candles, and constructs complete M5 candles. Indicators reset after gaps. At least 21 full M5 candles from a continuous session are needed.

Chart agreement uses M1 EMA9/EMA21 trend (2 points), M5 EMA9/EMA21 trend (2), RSI momentum (1), price relative to recent support/resistance midpoint (1), and last-candle direction (1). BUY needs at least +4 and SELL at most -4, out of 7 signed points. These are heuristic agreement points, **not a win probability or backtested profitability claim**. The spread must not exceed the M5 average true range. Quotes must be current, and the last completed M1 candle must be no older than 90 seconds. Stops combine M5 ATR, recent support/resistance and broker minimum distances; targets use twice the stop distance.

**AI news is required for every automatic entry**, as selected by the user. The configured provider is now local Ollama, using an already installed model. Keep Ollama running. The model receives retrieved headlines; it does not have built-in live news access. No OpenAI key or cloud inference is needed for this provider. Add these values to `.env` locally:

```dotenv
XM_NEWS_PROVIDER=ollama
XM_OLLAMA_URL=http://127.0.0.1:11434
XM_OLLAMA_MODEL=qwen2.5:7b-instruct
```

The app checks `/api/tags` for the exact model and uses `/api/chat` with a strict JSON schema. Only loopback URLs are accepted for Ollama, redirects are disabled, and no model downloads occur automatically. The first assessment can take longer while the model loads. HTTP requests happen outside the MT5 lock; fresh candles and quotes are fetched after inference. Malformed, truncated, uncited, conflicting or expired assessments still block automatic entries. Public news retrieval still requires Internet access. To use the optional OpenAI provider instead, explicitly select it:

```dotenv
XM_NEWS_PROVIDER=openai
OPENAI_API_KEY=your_own_key_here
XM_NEWS_MODEL=gpt-4.1-mini
```

The app retrieves timestamped public Google News RSS headlines about the instrument and sends up to eight recent headlines to the configured AI provider for structured interpretation. Only public instrument/headline data is sent, not MT5 account information or credentials. The OpenAI alternative incurs provider API charges; Ollama runs inference locally. Successful results are cached for five minutes per instrument, failures for 30 seconds; the panel and scanner share the assessment. The public feed has no availability guarantee. Coverage is headline-only and is not a full economic calendar. Undated, future-dated and older-than-24-hour items are excluded. The AI must cite supplied headline IDs and explain the base/quote currency direction. A relevant neutral assessment can permit a chart setup; opposing direction, flagged major risk, absent evidence, stale results or service errors block orders. Configuring a provider does not itself start a new automation session; use the existing Start button after connecting it.

Without the configured AI service (Ollama running with the selected model, or an OpenAI key for the cloud provider), chart readings and public headlines remain available, but new automation sessions cannot start. An active session also blocks entries whenever news is unavailable. The screen shows `AI NEWS NOT CONNECTED` rather than `MODEL NOT VALIDATED`. Previous local-model status rows remain on disk for reference but are excluded from the current scanner table. No chart scenario bypasses the automatic news, account, size, exposure or daily-loss checks. Manual order controls remain a separate explicit user action.

The previous learned-model design below is archived documentation, not the active XM strategy.

## Archived XM machine-learning analysis

After connecting the local XM demo terminal, choose an **Exact XM instrument** in the demo panel. **XM AI analysis** loads up to 50,000 completed M1 candles for that exact contract, displays its own broker-time candlestick chart, and trains local calibrated tree models. No external AI account or API key is needed. This is a learned statistical model, not an LLM or news analyst.

Choose a 5-, 15-, 30-, or 60-minute forecast horizon. Outcomes have three classes (up, neutral, down); the neutral band includes recorded spread plus an assumed 2 bp cost allowance. Features cover short/medium returns, EMA trend, ATR and its regime, breakouts, RSI, return volatility, tick activity and spread. Missing minutes reset indicators and future labels. An event model estimates whether price clears the cost band, while a direction model estimates up versus down conditional on such a move. Both probabilities are calibrated on a separate chronological segment. The app compares random forest and extra trees, selects a cost-aware probability cutoff on the calibration segment, then evaluates that frozen choice on the newest untouched segment using non-overlapping simulated entries with dynamic ATR stops, a 2R target, spread, and assumed costs. A policy is enabled only with at least 50 later trades and a positive 90% lower bound on mean net return. This is still historical evidence, not proof of future profitability; compare horizons only as exploration and seek fresh forward evidence.

The panel reports BUY setup / SELL setup / WAIT, or MODEL NOT VALIDATED when no policy passes the later holdout. A setup also requires the current joint probability of a cost-clearing move in its direction to meet the learned cutoff, a fresh candle and quote, and spread within the historical calibration range. Model bias remains visible even when the trade gate fails. Candles refresh every minute; each pair's capped tree models retrain hourly and are shared by the analysis panel and auto scanner. MT5 must have sufficient M1 history loaded; no bars are fabricated.

Dynamic XM distances are enabled by default for manual demo tickets when analysis is available. Stops use ATR, recent support/resistance and broker spread/minimum-distance floors; targets use twice the stop distance. Final order prices are rounded and checked by the existing demo-only connector. In manual mode, the user chooses BUY or SELL and clicks the order button. Automatic demo mode, described below, may submit qualifying setups without per-trade clicks. Turn off dynamic distances to enter a manual scenario. Existing Alpaca models and results are independent of this XM model.

XM server-time conversion is explicit in the connection panel: GMT+2 winter, GMT+3 summer, or UTC for terminals returning UTC timestamps. Match the actual terminal convention when seasons change; the app never derives an offset from an old quote to make it look fresh. Chart history is displayed in broker server time.



## Automatic XM demo trading

The automatic panel scans all available instruments in XM's Forex category that support exactly **0.01 lot**. It evaluates one instrument per dashboard refresh using the chart + required AI news engine described above. It does not train local models. After a news lookup, it fetches current MT5 candles and quotes before assessment. The chart strategy is experimental and has no validated win-rate claim.

**Start automatic DEMO trading** authorizes an eight-hour session bound to the current demo account/server and timestamp convention. **Stop automatic trading** blocks new entries but leaves existing broker-side stop/target orders in place. Runs only while the dashboard remains open and refreshing; there is no unattended daemon or Windows startup task. A page refresh preserves the bounded authorization; reconnecting a different account or changing the timestamp convention stops it. After expiry, starting another session is explicit.

Every entry is exactly 0.01 lot with dynamic broker-checked SL/TP. One automatic position per instrument is allowed; a pending order blocks entries until resolved. Before each entry, the scanner estimates the combined loss from current quotes to every open position's stop, subtracts account drawdown, and reserves 20% above the new trade's estimated stop loss. A missing stop or unavailable risk estimate blocks new entries. The total must remain under the 1% daily equity budget. Manual order controls in this dashboard are blocked during automation. Five attempts per UTC day and the loss budget are persisted in `xm_auto_demo.sqlite3`; the daily baseline is recorded on the first start/scan of the UTC day and is not reset by restarting. These controls block new entries, not guarantee loss caps: gaps, fees and fills can exceed estimates. Do not reset or deposit demo funds while evaluating a session, since that changes equity independently of trading.

The journal reserves a unique account/symbol/candle intent before submission. Repeated refreshes cannot resend that candle, and attempts with ambiguous, partial or accepted-but-unconfirmed results stop automation and require review in MT5. No automatic retries occur. A process lock serializes automation across tabs/processes. Settings and expiration are stored in `xm_auto_demo.json`. No password is saved. Actual fills and exits can be reviewed in MT5 Trade/History; the dashboard shows scan outcomes and order responses.
