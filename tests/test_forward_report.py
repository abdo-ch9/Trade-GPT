import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scalp_lab.forward_report import summarize


class ForwardReportTests(unittest.TestCase):
    def test_account_scope_costs_and_unknown_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'journal.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE entries (token TEXT, account TEXT, time REAL, state TEXT, detail TEXT)')
            db.execute('CREATE TABLE exits (token TEXT, state TEXT, detail TEXT)')
            for token, account, state, pnl in [('a', [1,'demo'], 'filled', 18), ('b', [1,'demo'], 'filled', -10), ('c', [2,'demo'], 'filled', 999), ('d', [1,'demo'], 'unknown', None)]:
                db.execute('INSERT INTO entries VALUES (?,?,?,?,?)', (token, json.dumps(account), ord(token), state, json.dumps({'execution_context': {'estimated_loss': -10, 'symbol': 'XAUUSD', 'setup': 'Trend pullback'}, 'latency_seconds': .2})))
                if pnl is not None:
                    db.execute('INSERT INTO exits VALUES (?,?,?)', (token, 'closed', json.dumps({'net_pnl': pnl, 'commission': -1})))
            db.commit()
            db.close()
            report = summarize([1,'demo'], path)
            self.assertEqual(report['attempts'], 3)
            self.assertEqual(report['closed_trades'], 2)
            self.assertEqual(report['unresolved_entries'], 1)
            self.assertEqual(report['net_pnl'], 8)
            self.assertEqual(report['commission'], -2)
            self.assertAlmostEqual(report['profit_factor'], 1.8)
            self.assertAlmostEqual(report['mean_r'], .4)
            self.assertEqual(report['max_closed_drawdown'], 10)
            self.assertFalse(report['live_ready'])

    def test_no_trades_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as folder:
            report = summarize([1,'demo'], Path(folder)/'missing.sqlite3')
            self.assertEqual(report['closed_trades'], 0)
            self.assertIsNone(report['profit_factor'])
            self.assertIsNone(report['win_rate'])
            self.assertFalse(report['live_ready'])
