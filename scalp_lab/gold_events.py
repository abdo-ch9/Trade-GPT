"""Persistent local audit trail and dashboard notifications; no external messaging."""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DB=Path(__file__).resolve().parents[1]/'gold_events.sqlite3'


def _connect(db_path,timeout=10):
    for attempt in range(6):
        try:
            return sqlite3.connect(db_path,timeout=timeout)
        except PermissionError:
            if attempt==5:
                raise
            time.sleep(.05*(attempt+1))


def record(kind,message,details=None,key=None,db_path=DB):
    with closing(_connect(db_path)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time REAL, kind TEXT, message TEXT, details TEXT, dedupe TEXT UNIQUE)')
        db.execute('INSERT OR IGNORE INTO events(time,kind,message,details,dedupe) VALUES (?,?,?,?,?)',
                   (time.time(),kind,message,json.dumps(details or {},default=str),key))
        db.commit()


def recent(limit=50,db_path=DB):
    if not Path(db_path).exists():
        return []
    try:
        with closing(_connect(db_path)) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(limit,))]
    except PermissionError:
        return []
