"""Block layout migration while the demo terminal has any open positions."""

import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print('MetaTrader5 is unavailable; cannot verify open positions.')
    raise SystemExit(2)

if not mt5.initialize(timeout=5000):
    print('Could not connect to MT5; leave the worker running and retry later.')
    raise SystemExit(2)
try:
    positions = mt5.positions_get()
    if positions is None:
        print('Could not read open positions; leave the worker running and retry later.')
        raise SystemExit(2)
    if positions:
        summary = ', '.join(f'{position.symbol} ticket {position.ticket}' for position in positions)
        print(f'{len(positions)} open MT5 position(s) ({summary}); layout migration will wait until the account is flat.')
        raise SystemExit(2)
    print('No open MT5 positions.')
finally:
    mt5.shutdown()
