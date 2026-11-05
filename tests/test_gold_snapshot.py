import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from scalp_lab import gold_snapshot as snapshots, xm_news as news
from scalp_lab.xm_chart import news_gate


class SharedSnapshotTests(unittest.TestCase):
    def test_round_trip_context_and_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'snapshot.json'
            result = {'frame': pd.DataFrame({'time': [100.0], 'close': [2000.0]}),
                      'action': 'BLOCKED', 'checks': [{'Check': 'News', 'Passed': False}],
                      'news': {'status': 'unavailable'}, 'reasons': ['News required']}
            with patch.object(snapshots.time, 'time', return_value=160):
                snapshots.publish([1, 'demo'], 'XAUUSD', 0, result, path)
            loaded = snapshots.read([1, 'demo'], 'XAUUSD', 0, path, now=165)
            self.assertEqual(loaded['action'], 'BLOCKED')
            self.assertEqual(loaded['candle_age_seconds'], 5)
            self.assertEqual(loaded['checks'], result['checks'])
            self.assertIsNone(snapshots.read([2, 'demo'], 'XAUUSD', 0, path, now=165))
            self.assertIsNone(snapshots.read([1, 'demo'], 'GOLD', 0, path, now=165))
            self.assertIsNone(snapshots.read([1, 'demo'], 'XAUUSD', 2, path, now=165))
            self.assertIsNone(snapshots.read([1, 'demo'], 'XAUUSD', 0, path, now=181))

    def test_background_news_does_not_wait_and_deduplicates(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(3)
            done.set()
            return {'status': 'unavailable', 'checked_at': time.time()}
        config = {'provider': 'ollama', 'url': 'http://localhost', 'model': 'test', 'key': ''}
        with patch.object(news, 'configuration', return_value=config), patch.object(news, 'get_news', side_effect=slow) as fetch:
            news.BACKGROUND.clear()
            first = news.get_news_background('TEST')
            self.assertEqual(first['status'], 'refreshing')
            self.assertTrue(entered.wait(1))
            news.get_news_background('TEST')
            self.assertEqual(fetch.call_count, 1)
            self.assertIsNotNone(news_gate(first, 'BUY', time.time())[0])
            release.set()
            self.assertTrue(done.wait(1))

    def test_expired_background_news_still_blocks_entry(self):
        stale = {'status': 'ready', 'direction': 'BUY', 'relevant': True, 'high_risk': False,
                 'checked_at': time.time()-400, 'expires_at': time.time()-100}
        self.assertEqual(news_gate(stale, 'BUY', time.time())[0], 'NEWS UNAVAILABLE')

class RiskSummaryTests(unittest.TestCase):
    def test_remaining_budget_deducts_loss_and_reserved_risk(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from scalp_lab import auto_demo as auto
        import sqlite3
        import json
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder)/'journal.sqlite3'
            identity = [1, 'demo']
            with sqlite3.connect(journal) as db:
                db.execute('CREATE TABLE days (account TEXT, day TEXT, equity REAL)')
                db.execute('INSERT INTO days VALUES (?, ?, ?)', (json.dumps(identity), datetime.now(timezone.utc).strftime('%Y-%m-%d'), 200))
                db.execute('CREATE TABLE entries (account TEXT, day TEXT)')
            db.close()
            mt5 = Mock()
            mt5.positions_get.return_value = []
            with patch.object(auto, 'JOURNAL', journal), patch.object(auto.bridge, 'api', return_value=mt5), patch.object(auto.bridge, 'checked_account', return_value=SimpleNamespace(equity=195, currency='USD')), patch.object(auto, 'daily_budget', return_value=56), patch.object(auto, 'portfolio_stop_risk', return_value=10):
                result = snapshots.risk_summary(identity, {'offset': 2})
                self.assertEqual(result['remaining'], 41)
                self.assertEqual(result['attempts'], 0)
                mt5.order_send.assert_not_called()
