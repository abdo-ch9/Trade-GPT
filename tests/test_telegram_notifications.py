import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from scalp_lab import telegram_notifications as telegram
from scalp_lab.gold_events import record


class TelegramTests(unittest.TestCase):
    def test_future_decisions_only_dedupe_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            db, state = Path(folder)/'events.sqlite3', Path(folder)/'state.json'
            record('decision', 'XAUUSD: old', db_path=db)
            config = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '123'}
            with patch.object(telegram, 'configuration', return_value=config), patch.object(telegram, 'send_message', return_value=True) as send:
                telegram.poll_once(db, state)
                send.assert_not_called()
                detail = {'symbol': 'XAUUSD', 'action': 'BLOCKED', 'direction': 'SELL', 'setup': 'Trend pullback', 'reasons': ['News conflict']}
                record('decision', 'XAUUSD: blocked', detail, db_path=db)
                telegram.poll_once(db, state)
                self.assertEqual(send.call_count, 1)
                self.assertIn('News conflict', send.call_args.args[1])
                record('decision', 'XAUUSD: blocked', detail, db_path=db)
                telegram.poll_once(db, state)
                self.assertEqual(send.call_count, 1)
                detail['action'] = 'SELL setup'
                record('decision', 'XAUUSD: sell', detail, db_path=db)
                telegram.poll_once(db, state)
                self.assertEqual(send.call_count, 2)

    def test_failure_keeps_event_for_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            db, state = Path(folder)/'events.sqlite3', Path(folder)/'state.json'
            record('worker', 'start', db_path=db)
            with patch.object(telegram, 'configuration', return_value={'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '123'}), patch.object(telegram, 'send_message', return_value=False):
                telegram.poll_once(db, state)
                cursor = json.loads(state.read_text())['cursor']
                record('decision', 'XAUUSD: sell', {'action': 'SELL setup'}, db_path=db)
                telegram.poll_once(db, state)
                self.assertEqual(json.loads(state.read_text())['cursor'], cursor)
                self.assertNotIn('secret', state.read_text())

    def test_missing_configuration_never_sends(self):
        with patch.object(telegram, 'configuration', return_value={'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': ''}), patch.object(telegram, 'send_message') as send:
            telegram.poll_once()
            send.assert_not_called()

    def test_http_failure_is_contained(self):
        import requests
        with patch.object(telegram.requests, 'post', side_effect=requests.Timeout('secret URL')):
            self.assertFalse(telegram.send_message({'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_CHAT_ID': '123'}, 'test'))
