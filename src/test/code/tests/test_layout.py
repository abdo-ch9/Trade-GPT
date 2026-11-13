import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scalp_lab.paths import ENV_FILE, LIB_DIR, PROJECT_ROOT


class LayoutTests(unittest.TestCase):
    def test_runtime_paths_are_outside_source_tree(self):
        self.assertEqual(LIB_DIR, PROJECT_ROOT / 'lib')
        self.assertEqual(ENV_FILE, PROJECT_ROOT / '.env')
        self.assertTrue((PROJECT_ROOT / 'src/main/code/scalp_lab').is_dir())

    def test_legacy_event_merge_preserves_both_histories(self):
        schema = '''CREATE TABLE events
                    (id INTEGER PRIMARY KEY, time REAL, kind TEXT,
                     message TEXT, details TEXT, dedupe TEXT UNIQUE)'''
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'target.sqlite3'
            source = Path(folder) / 'source.sqlite3'
            for path in (target, source):
                with closing(sqlite3.connect(path)) as db:
                    db.execute(schema)
            with closing(sqlite3.connect(target)) as db:
                db.execute('INSERT INTO events(time,kind,message,details,dedupe) VALUES (1,?,?,?,?)',
                           ('decision', 'old', '{}', None))
                db.commit()
            with closing(sqlite3.connect(source)) as db:
                db.execute('INSERT INTO events(time,kind,message,details,dedupe) VALUES (2,?,?,?,?)',
                           ('trade', 'new', '{}', 'new-trade'))
                db.commit()
            script = PROJECT_ROOT / 'src/main/code/merge_legacy_events.py'
            for _ in range(2):
                subprocess.run([sys.executable, str(script), str(target), str(source)],
                               check=True, capture_output=True)
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute('SELECT message FROM events ORDER BY time').fetchall(),
                                 [('old',), ('new',)])
