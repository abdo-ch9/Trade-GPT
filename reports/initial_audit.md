# Initial audit

## Architecture and scope

`dashboard.py` selects the IC Markets or Exness Streamlit workspace. Each uses a 10-second fragment, MT5 M1 OHLC/spread/tick volume, and broker-specific workers and journals. Exness shares broker-neutral modules from `scalp_lab`. The separate legacy stock dashboard and CLI use Alpaca REST/WebSocket and a HistGradientBoosting model for paper signals. Gold news uses Google News RSS and Ollama or OpenAI. Telegram delivers notifications. Synthetic inputs exercise plumbing only.

The default gold path uses completed M1, M5 and M15 bars, three deterministic setups, an ATR/structure stop and a 1.8R target. It checks spread, drift, news, account and risk before an order. Its simulation forces a 15-minute exit while current Exness orders use attached stops and targets. The saved 405-trade Exness holdout reports −0.082R per trade and 0.779 profit factor. These are strategy results, not forecast MAE.

The separate `xm_analysis.py` uses Random Forest and Extra Trees to estimate a three-class cost-hurdle outcome, normally at five minutes. It fits and calibrates chronologically with a label purge. Streamlit caches training for an hour, but a cache miss downloads 50,000 bars and fits on the requesting thread. Warm requests still fetch 180 bars, build training labels along with inference features and request quotes twice. No neural-network model was found.

## Risks and priorities

1. Reuse immutable historical snapshots and move fitting offline. Serve artifacts from a bounded, candle-deduplicated, read-only inference path with no news or order calls.
2. Report chronological model selection, training-only transforms, separate probability calibration, a purged final test and dataset provenance. No macro/news features enter the model without point-in-time data.
3. Compare return and directional forecasts at 1, 3, 5 and 15 minutes, then run a separate non-overlapping paper replay with costs and explicit bar-resolution fill assumptions.
4. Benchmark cold fitting, warm inference and feature processing separately. The default fragment introduces up to roughly 10 seconds of polling wait before rendering. The chart path also downloads the 3,000-bar window twice around the news lookup and recalculates features per scan. Exact provider-to-output latency requires a connected terminal and an observed candle boundary.

Baseline CPU measurements and test results are recorded in the latency and final reports. The local historical export has already been used for chart research, so a sealed split within that export is a retrospective comparison. Future, unobserved candles are needed for independent confirmation.
