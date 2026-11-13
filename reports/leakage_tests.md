# Leakage and reliability tests

- Each feature uses at most 61 consecutive completed M1 bars. Future price
  mutation leaves the historical feature prefix identical. The latest row from
  a full replay matches a bounded inference window.
- Target timestamps are checked against the exact horizon and labels across
  gaps are dropped. Fit and calibration slices purge labels ending at or
  after the next partition boundary. Scalers live inside training-only model
  pipelines. Three expanding folds select by mean Brier before the final split
  is scored. No macroeconomic revisions or news timestamps are used.
- Tests cover incomplete, identical and conflicting candles, malformed prices,
  UTC normalization, data downtime, gap warm-up, corrupt and missing artifacts,
  identical repeat forecasts, bounded incremental reads, a coarse local timing
  budget and deterministic walk-forward/replay output.
- Tests use synthetic bars for invariants and use the real archive separately
  for model evaluation. Test classes are discoverable by pytest and unittest.
  The local package index did not supply pytest, so the suite was run with
  unittest in this environment.
