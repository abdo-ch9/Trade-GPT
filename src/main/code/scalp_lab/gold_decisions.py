"""Immutable per-candle decision snapshots, separate from changing live status."""
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

from .paths import LIB_DIR
DB=LIB_DIR/'gold_decisions.sqlite3'


def save(identity,symbol,result,db_path=DB,outcome=None):
    side=result.get('chart_signal')
    scenario=result.get('scenarios',{}).get(side,{})
    frame=result.get('frame')
    if side not in ('BUY','SELL') or not scenario or frame is None or frame.empty:
        return
    if any(not isinstance(scenario.get(k),(int,float)) or not math.isfinite(scenario[k])
           for k in ('entry','sl','tp')):
        return
    account=json.dumps(list(identity))
    bar=float(frame.iloc[-1].time)
    observed=float(result['observed_at'])
    row={'Instrument':symbol,'Direction':side,'Decision':result.get('action'),
         'Execution status':'Not submitted — signal blocked' if result.get('action')=='BLOCKED' else 'No broker outcome recorded',
         'Saved at (UTC)':datetime.fromtimestamp(observed,timezone.utc).isoformat(),
         'Position (lots)':scenario.get('lots'),'Indicative entry':scenario['entry'],
         'Take profit':scenario['tp'],'Stop loss':scenario['sl'],'Risk (% equity)':scenario.get('risk_pct'),
         'Estimated loss at stop':scenario.get('risk_amount'),'Account currency':scenario.get('currency'),
         'Setup':result.get('setup'),'Reason':' '.join(result.get('reasons',[]))}
    # UI and worker may see the same decision repeatedly. Preserve its first quoted levels.
    key=json.dumps([account,result.get('engine'),symbol,bar,side,result.get('action')])
    with closing(sqlite3.connect(db_path,timeout=10)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, account TEXT, symbol TEXT, observed REAL, dedupe TEXT UNIQUE, detail TEXT)')
        db.execute('INSERT OR IGNORE INTO decisions(account,symbol,observed,dedupe,detail) VALUES (?,?,?,?,?)',
                   (account,symbol,observed,key,json.dumps(row,default=str)))
        if outcome is not None:
            saved=json.loads(db.execute('SELECT detail FROM decisions WHERE dedupe=?',(key,)).fetchone()[0])
            # A later waiting/duplicate scan must not erase a recorded broker outcome.
            if not saved.get('Broker outcome'):
                state=outcome.get('state','unknown')
                submitted=state in ('filled','partial','accepted','rejected','unknown')
                saved['Execution status']=('Broker: '+state if submitted else 'Not submitted: '+state)
                saved['Execution reason']=outcome.get('message','')
                if result.get('action')=='BLOCKED' and not submitted:
                    saved['Execution reason']=' '.join(result.get('reasons',[]))
                saved['Broker outcome']=state if submitted else None
                saved['Broker order']=outcome.get('order')
                saved['Broker fill price']=outcome.get('price')
                db.execute('UPDATE decisions SET detail=? WHERE dedupe=?',(json.dumps(saved,default=str),key))
        db.commit()


def recent(identity,symbols,limit=200,db_path=DB):
    if not Path(db_path).exists() or not symbols:
        return []
    with closing(sqlite3.connect(db_path,timeout=10)) as db:
        placeholders=','.join('?' for _ in symbols)
        rows=db.execute(f'SELECT detail FROM decisions WHERE account=? AND symbol IN ({placeholders}) ORDER BY observed DESC,id DESC LIMIT ?',
                        [json.dumps(list(identity)),*symbols,int(limit)]).fetchall()
        result=[json.loads(r[0]) for r in rows]
        for row in result:
            row.setdefault('Execution status','Not submitted — signal blocked' if row.get('Decision')=='BLOCKED' else 'No broker outcome recorded')
        return result
