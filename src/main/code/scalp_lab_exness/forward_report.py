"""Account-scoped forward execution diagnostics."""
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path


def summarize(identity, db_path):
    report = {'attempts': 0, 'filled_entries': 0, 'closed_trades': 0,
              'unresolved_entries': 0, 'unresolved_exits': 0, 'net_pnl': 0.0,
              'commission': 0.0, 'swap': 0.0, 'fee': 0.0,
              'win_rate': None, 'profit_factor': None, 'mean_r': None,
              'max_closed_drawdown': 0.0, 'mean_latency_seconds': None,
              'states': {}, 'trades': [], 'live_ready': False,
              'note': 'Forward execution diagnostics. Closed-trade metrics exclude open-position losses.'}
    if not Path(db_path).exists():
        return report
    with closing(sqlite3.connect(db_path, timeout=2)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'entries' not in tables:
            return report
        rows = db.execute('SELECT token,time,state,detail FROM entries WHERE account=? ORDER BY time,token',
                          (json.dumps(list(identity)),)).fetchall()
        exits = dict(db.execute('SELECT token,state FROM exits')) if 'exits' in tables else {}
        details = dict(db.execute('SELECT token,detail FROM exits')) if 'exits' in tables else {}
    latency, multiples, profits = [], [], []
    equity = peak = 0.0
    for token, stamp, state, raw in rows:
        entry = json.loads(raw)
        context = entry.get('execution_context', {})
        report['attempts'] += 1
        report['states'][state] = report['states'].get(state, 0)+1
        report['filled_entries'] += state == 'filled'
        report['unresolved_entries'] += state in ('sending', 'unknown', 'partial', 'accepted')
        report['unresolved_exits'] += token in exits and exits[token] != 'closed'
        elapsed = entry.get('latency_seconds')
        if isinstance(elapsed, (int, float)) and math.isfinite(elapsed) and elapsed >= 0:
            latency.append(elapsed)
        if exits.get(token) != 'closed':
            continue
        closed = json.loads(details[token])
        pnl = closed.get('net_pnl')
        if not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            continue
        report['closed_trades'] += 1
        profits.append(pnl)
        equity += pnl
        peak = max(peak, equity)
        report['max_closed_drawdown'] = max(report['max_closed_drawdown'], peak-equity)
        for field in ('commission', 'swap', 'fee'):
            report[field] += float(closed.get(field, 0))
        risk = context.get('estimated_loss')
        multiple = pnl/abs(risk) if isinstance(risk, (int, float)) and math.isfinite(risk) and risk < 0 else None
        if multiple is not None:
            multiples.append(multiple)
        report['trades'].append({'entry_time': stamp, 'symbol': context.get('symbol'),
                                'setup': context.get('setup'), 'net_pnl': pnl, 'net_r': multiple,
                                'latency_seconds': elapsed, 'close_reason': closed.get('close_reason')})
    report['net_pnl'] = sum(profits)
    if profits:
        report['win_rate'] = sum(p > 0 for p in profits)/len(profits)
        losses = -sum(p for p in profits if p < 0)
        report['profit_factor'] = sum(p for p in profits if p > 0)/losses if losses else None
    report['mean_r'] = sum(multiples)/len(multiples) if multiples else None
    report['mean_latency_seconds'] = sum(latency)/len(latency) if latency else None
    return report
