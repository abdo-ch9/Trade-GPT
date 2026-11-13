# Exness gold research

The Exness dashboard supports GOLD, XAUUSD, and the `m`, `c`, `r`, and `z` XAUUSD
suffixes when MT5 reports USD as the instrument's profit currency. Decisions use
completed M1, M5, and M15 candles, fixed chart setups, sourced news, and broker
risk checks. Exness account identity is checked before orders are submitted.

## Historical results

The first evaluation used 59,999 completed bars and 521 holdout trades. Its
expectancy was -0.119R, profit factor 0.52, and all four holdout blocks failed.
A later diagnostic 15-minute simulation reported 375 holdout trades, -0.140R
mean, and profit factor 0.657. These already inspected results do not validate
automatic entries.

The historical simulation uses a 15-minute maximum hold and approximate spread,
slippage, and commission costs. New bot positions instead use attached broker
stop-loss and take-profit orders with no timed close. Previously journaled timed
positions still follow their stored deadline. A timed-exit backtest does not
validate this broker-managed exit policy, so normal real-account entry validation
remains blocked until matching evidence and forward paper validation exist.
The explicit demo research override is advisory and does not establish profit.

## Limits

The system has no point-in-time DXY or yield feed, verified economic calendar
blackout, COMEX order book or consolidated exchange volume, or calibrated win
probability. Exness tick volume is not COMEX futures volume. Current headlines
cannot be attached retroactively to historical trades.

Exness DEMO records, evaluation files, order journals, and worker status live in the
ignored `lib/exness/` folder. Exness LIVE has its own `lib/live/exness/` records.
IC Markets has separate DEMO and LIVE records and validation.
The Exness code is in `src/main/code/scalp_lab_exness/`, shared by the isolated
`scalp_lab_exness_live/` runtime. The active dashboard is `src/main/code/dashboard.py`.
