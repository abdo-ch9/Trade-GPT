# Gold research desk

The active dashboard is now gold-only. The old multi-asset dashboard is archived as
`dashboard_legacy.py`; its models are not part of gold decisions. Old currency
automation was stopped. No existing MT5 order or position was changed.

## Implemented

- Exact IC Markets GOLD/XAUUSD instrument allowlist; excludes mining stocks and GOLD24-7.
- Completed M1, M5 and M15 data; indicators reset across missing minutes.
- Three fixed hypotheses: trend pullback, breakout/retest, range sweep.
- EMA 9/20, ATR14, RSI, prior structure, previous-day extremes, tick-relative
  volume and an explicitly labeled tick-volume VWAP proxy.
- Stops based on M5 volatility and structure, target 1.8R, broker risk valuation
  at 0.01 lot. No fabricated or calibrated probability is displayed.
- Ollama interprets sourced gold/macro headlines; news remains required for entries.
- Chronological 60/40 split; four holdout time blocks; daily block bootstrap;
  cost stress test; CSV research trade log and JSON evaluation report.
- Existing demo-only broker checks, daily risk budget, five entry attempts,
  duplicate-candle journal and ambiguous-order protection retained for gold.

## What the backtest means

Rules were fixed before the initial gold evaluation. Entries use the next bar;
only previously closed higher-timeframe bars inform the signal. Simulated trades
do not overlap. Missing minutes invalidate a trade window. A stop wins if stop
and target both appear within the same candle. Gaps beyond a stop worsen its fill.

Costs use historical bar spread, assumed adverse slippage of the greater of one
tick or 5% of M1 ATR on each fill, and $0.10 per ounce assumed round-trip commission.
These are approximations, not measured execution costs. Stress doubles these costs
and applies the same spread filter, so stress may take fewer trades.

The maximum exit is 15 minutes, three 5-minute bars. That matches the live timed
close for new bot positions. Broker SL/TP can still close a trade earlier. The
previous 5-minute cap made the 1.8R target unreachable: almost every trade expired
on the clock. Stops and the 1.8R target are unchanged. This history was already
inspected, so the 15-minute rerun is diagnostic and cannot authorize entries.
A later, unseen period has to pass the same cost tests before entries are allowed.

This is a chart-only historical evaluation. Today's news is never retroactively
attached to historical bars. Combined chart/news profitability has not been tested.
Repeated changes after viewing results contaminate holdout; further research must
reserve a new unseen period. Bootstrap uncertainty is not a profit guarantee.

## Explicitly missing

- Point-in-time DXY, Treasury yields and real-rate feeds.
- Verified economic calendar / scheduled CPI, NFP, PCE and FOMC blackout windows.
- COMEX GC/MGC real volume, order book, market delta and open interest.
- Exchange volume profile, institutional-order identification, calibrated ML
  probabilities, model drift monitoring, and a validated profitable model.
- A fresh unseen period evaluated with the 15-minute exit before claiming validation.
  The user's explicit demo-research override can allow entries without that claim.

## Execution and monitoring improvements

- A separate local worker scans while the browser is closed. It must remain running,
  with MT5 connected, for timed exits to occur. This is not an OS-reboot service.
- Simulation and new bot entries share the 15-minute signal-close deadline. The
  watchdog only manages journaled bot-owned gold positions; it does not close Tesla,
  legacy positions without an exit policy, or positions modified by another entry.
- Final risk checks use newly fetched equity; configuration permission reads are
  uncached by default. Stop/revocation changes are checked before submission.
- A recent successful exit check, matching exit-policy version and current heartbeat
  are required before new entries. Scanner liveness is displayed separately.
- Atomic JSON writes retry Windows sharing-lock failures. A persistent write failure
  preserves the previous file and raises an error rather than silently truncating it.
- Dashboard toasts and persistent SQLite events record entries, blocked decisions,
  errors and exits. These are local notifications, not email or phone notifications.
- Entry requests, estimated risk, spread, fill slippage, latency and available realized
  deal commissions/fees are recorded for future execution-cost calibration.
- All retained user preferences remain explicit: 0.01 lot, demo only, advisory
  historical validation, Tesla stop-risk exclusion, and the shared daily loss limit.

The implementation review passed 60 focused tests and a read-only dashboard test
with order submission disabled. The saved diagnostic rerun is
`gold_improvement_review.json`: 375 holdout trades, -0.140R mean, profit factor 0.657.
This already-viewed sample cannot prove profitability or select a winner without
further unseen evaluation. No new macro or exchange data feed was connected.

IC Markets CFDs and COMEX futures are different instruments. IC Markets tick volume
is not consolidated exchange volume. News headlines do not replace a complete calendar.

The saved evaluation predates the broker change and does not identify IC Markets.
It is retained as historical research only and cannot authorize entries. Fresh IC
Markets candles, spreads, contract details and a new evaluation are required; the
dashboard blocks reports without IC Markets broker metadata.

## Research output

`gold_history.csv`: broker M1 history used in the latest evaluation.
`gold_research_trades.csv`: simulated trades, setup, entry/exit times, net R.
`gold_validation.json`: sample dates, holdout metrics, cost stress and uncertainty.

The first evaluation used 59,999 completed bars and 521 holdout trades:
expectancy -0.119R, profit factor 0.52. It failed all four holdout time blocks.
This result is evidence against deploying these initial rules, not a reason to
relax validation or force trades.

References: https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py
and https://www.cmegroup.com/markets/metals/precious/gold-futures.html
