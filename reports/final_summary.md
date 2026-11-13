# Trade-GPT forecast upgrade

The new read-only paper workspace uses offline fitting, chronological
calibration, a bounded candle cache and one inference per completed candle.
The existing chart and order paths remain separate.

| Metric | Original | Improved |
|---|---|---|
| Prediction MAE | Unavailable. Original gold ML emits three event probabilities. | 2.580 / 4.537 / 5.896 / 10.269 bps at 1 / 3 / 5 / 15 min |
| Directional accuracy | 41.29% on the original 5m cost-hurdle three-class task | 50.42 / 50.71 / 51.68 / 52.39% on non-flat binary direction |
| p95 inference latency | 58.48 ms for one 5m forecast | 7.25 ms across four horizons |
| p95 end-to-end latency | 98.39 ms warm local replay. Provider-to-output unmeasured. | 20.36 ms local replay. Provider-to-output unmeasured. |
| Walk-forward performance | Single native chronological holdout. No comparable expanding-fold scores. | Three expanding validation folds. Final Brier .250143 / .250271 / .250282 / .249724. Zero final paper trades. |
| Test failures | 0 of 227 | 0 of 233 |

No selected model beat the zero-return baseline on final Brier score. The archive
supports faster local inference and reproducible abstention. It does not establish
better forecast accuracy or profitable trading. Boosting candidates, fresh
forward data and broker-connected latency still need measurement.

See [initial audit](initial_audit.md), [model comparison](model_comparison.md),
[latency benchmark](latency_benchmark.md) and [leakage tests](leakage_tests.md).
