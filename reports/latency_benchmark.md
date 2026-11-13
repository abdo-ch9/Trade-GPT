# Latency benchmark

Windows project virtual environment, Python 3.14. Historical Exness archive.
Percentiles in milliseconds. Original used 35 repeated calls against a 180-bar
tail, with a separate 3,000-bar measurement for the primary chart engine.
Improved used 250 sequential candle updates with an in-memory provider replay.
The new inference measurement covers all four horizons.

| Stage | Original p50 / p95 | Improved p50 / p95 |
|---|---:|---:|
| Local feature stage | 19.93 / 23.22 | 11.09 / 13.14 |
| Model inference | 54.58 / 58.48 | 5.95 / 7.25 |
| Local warm data-to-output | 76.61 / 98.39 | 17.34 / 20.36 |
| In-memory provider adapter | Not separately measured | 0.062 / 0.092 |
| Primary chart feature calculation | 101.30 / 118.76 | Separate existing path |
| Live network / completed candle to UI | Unmeasured | Unmeasured |

Original cold fitting took 8.12 seconds locally, excluding provider operations.
The upgraded application loads a cached artifact before inference. The in-memory
provider benchmark cannot measure MT5 publication delay, terminal IPC, Streamlit
rendering or wall-clock polling wait. The paper workspace polls at two-second
intervals while active, versus ten seconds for the broker dashboard. That
interval can consume the entire two-second target by itself. A broker-connected
session timed across actual candle boundaries is required to establish the
provider-to-output p95. No independent memory benchmark was taken.
