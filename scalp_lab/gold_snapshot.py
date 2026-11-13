"""Display-only worker snapshots. Never used to authorize execution."""
import json
import time
from pathlib import Path

import pandas as pd

from .gold_storage import write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'gold_dashboard_snapshot.json'


def publish(identity, symbol, offset, result, path=PATH):
    payload = {k: v for k, v in result.items() if k != 'frame'}
    # Pandas normalizes numpy scalars and NaNs to portable JSON values.
    clean = json.loads(pd.Series(payload, dtype=object).to_json())
    clean['frame'] = json.loads(result['frame'].tail(240).to_json(orient='records'))
    write_json(path, {'identity': list(identity), 'symbol': symbol, 'offset': offset,
                      'published_at': time.time(), 'result': clean})


def read(identity, symbol, offset, path=PATH, now=None):
    now = time.time() if now is None else now
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if (data['identity'] != list(identity) or data['symbol'] != symbol
                or data['offset'] != offset or not 0 <= now-data['published_at'] < 20):
            return None
        result = data['result']
        result['frame'] = pd.DataFrame(result['frame'])
        if result['frame'].empty:
            return None
        result['snapshot_age_seconds'] = now-data['published_at']
        result['candle_age_seconds'] = now+offset*3600-float(result['frame'].iloc[-1].time)-60
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return None


def risk_summary(identity, config):
    """Read current risk headroom without creating journal rows or sending requests."""
    import sqlite3
    from contextlib import closing
    from datetime import datetime, timezone
    from . import auto_demo as auto, mt5_demo as bridge
    with bridge.LOCK:
        mt5 = bridge.api()
        account = bridge.checked_account(mt5, identity)
        baseline = account.equity
        attempts = 0
        if auto.JOURNAL.exists():
            with closing(sqlite3.connect(auto.JOURNAL, timeout=2)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                key = json.dumps(list(identity))
                day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                if 'days' in tables:
                    row = db.execute('SELECT equity FROM days WHERE account=? AND day=?', (key, day)).fetchone()
                    if row:
                        baseline = row[0]
                if 'entries' in tables:
                    attempts = db.execute('SELECT COUNT(*) FROM entries WHERE account=? AND day=?', (key, day)).fetchone()[0]
        positions = mt5.positions_get()
        if positions is None:
            raise bridge.DemoError('Current portfolio risk is unavailable.')
        budget = auto.daily_budget(config, baseline, account.currency)
        loss = max(0, baseline-account.equity)
        demo = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        reserved = auto.portfolio_stop_risk(mt5, positions, config.get('offset', bridge.UTC_OFFSET_HOURS), demo and config.get('exclude_tesla_stop_risk') is True)
        return {'budget': budget, 'remaining': max(0, budget-loss-reserved),
                'currency': account.currency, 'attempts': attempts}
