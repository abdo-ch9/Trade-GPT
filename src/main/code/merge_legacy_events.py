"""Merge events written while the old worker was active during layout preparation."""

import sqlite3
import sys
from contextlib import closing

destination, source = sys.argv[1:3]
with closing(sqlite3.connect(destination)) as db:
    db.execute('ATTACH DATABASE ? AS legacy', (source,))
    db.execute('''INSERT OR IGNORE INTO events(time, kind, message, details, dedupe)
                  SELECT e.time, e.kind, e.message, e.details, e.dedupe
                  FROM legacy.events AS e
                  WHERE NOT EXISTS (
                    SELECT 1 FROM main.events AS current
                    WHERE current.time = e.time
                      AND current.kind = e.kind
                      AND current.message = e.message
                      AND current.details IS e.details
                      AND current.dedupe IS e.dedupe
                  )''')
    db.commit()
    db.execute('DETACH DATABASE legacy')
