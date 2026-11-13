# Model comparison

Source: 59,999 archived Exness XAUUSDm M1 candles. SHA-256
`d7e07794c1f8c00694cf00775ba761b492ede5c61e3f9fda5b5149e178ebb1e7`.
Point size 0.001 and UTC offset zero. Previously inspected archive. The final
20% is held out within this run, with earlier expanding folds used for selection.
This does not establish independent forward performance.

Mean validation Brier score across three expanding folds. Lower is better.

| Model / feature group | 1m | 3m | 5m | 15m |
|---|---:|---:|---:|---:|
| Zero return / base rate | .249931 | .249848 | .249788 | .249410 |
| Last return | .249832 | .249931 | .249805 | .249444 |
| Logistic / price | .249324 | .249736 | .249765 | .249524 |
| Logistic / all | .249423 | .249751 | .249786 | .249694 |
| Ridge / price | .249822 | .249852 | .249943 | .250094 |
| Ridge / all | .249858 | .249894 | .249996 | .250347 |

Price includes returns, range, volatility, ATR, RSI, candle geometry and a
finite-window trend. The context ablation adds spread, tick-volume activity and
UTC time-of-day. Context did not improve the winning validation score at any
horizon in this experiment. MACD and EMA variants were not evaluated.

| Horizon | Selected | Final MAE (bps) | Zero MAE (bps) | Direction accuracy | Balanced accuracy | Final Brier | Zero Brier |
|---|---|---:|---:|---:|---:|---:|---:|
| 1m | Logistic price | 2.580 | 2.580 | 50.42% | 50.29% | .250143 | .250132 |
| 3m | Logistic price | 4.537 | 4.537 | 50.71% | 50.04% | .250271 | .250126 |
| 5m | Logistic price | 5.896 | 5.897 | 51.68% | 49.99% | .250282 | .249692 |
| 15m | Zero / base rate | 10.269 | 10.269 | 52.39% | 50.00% | .249724 | .249724 |

Accuracy excludes flat realized returns. The Brier event is a strictly positive
return. The down and flat split uses calibration-period conditional frequencies.
The absolute-residual interval used a 90th percentile calibration threshold and
covered 86.5–87.3% of final observations. The interval is descriptive, with coverage
short of 90% in this sample. No final horizon produced a paper trade. Win rate,
profit factor, average trade return and drawdown are undefined for zero fills.
The replay models observed bar spreads, 1 bp round-trip commission, 0.5 bp
slippage per fill and a two-second decision delay. Fills use M1 opens, so a
two-second delay generally advances the entry to the next minute. It is an
approximation and excludes broker tick fills, swaps, and historical news.

The archived Random Forest/Extra Trees pipeline was trained and measured under
its original three-class, cost-adjusted event definition. Its native 5m test
accuracy was 41.29% and balanced accuracy 40.09% across 3,420 evaluated rows.
It produces class probabilities rather than a continuous return. This is not
a like-for-like comparison with the binary event above. There is no existing
neural model. LightGBM and XGBoost are wired in as optional candidates, but the
local package index did not supply the dependencies for this run.
