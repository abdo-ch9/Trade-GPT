import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scalp_lab.gold_storage import write_json
from scalp_lab.gold_worker import healthy
from scalp_lab.gold_exits import EXIT_POLICY
from scalp_lab import auto_demo


class StorageAndHealthTests(unittest.TestCase):
    def test_windows_sharing_lock_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            path.write_text('{"old":true}')
            original=Path.replace
            calls=[]
            def locked(source,target):
                calls.append(source)
                if len(calls)<3:
                    raise PermissionError('sharing lock')
                return original(source,target)
            with patch.object(Path,'replace',locked),patch('scalp_lab.gold_storage.time.sleep'):
                write_json(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'new':True})
            self.assertEqual(len(calls),3)
            self.assertEqual(len(list(Path(folder).glob('*.tmp'))),0)

    def test_failed_update_preserves_existing_state_and_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            path.write_text('{"enabled":false}')
            with patch.object(Path,'replace',side_effect=PermissionError('locked')),patch('scalp_lab.gold_storage.time.sleep'):
                with self.assertRaises(PermissionError):
                    write_json(path,{'enabled':True})
            self.assertFalse(json.loads(path.read_text())['enabled'])
            self.assertEqual(len(list(Path(folder).glob('*.tmp'))),0)

    def test_permissions_read_external_stop_immediately(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            path.write_text('{"enabled":true}')
            with patch.object(auto_demo,'CONFIG',path),patch.object(auto_demo,'_settings_cache',(0,{})):
                self.assertTrue(auto_demo.settings()['enabled'])
                path.write_text('{"enabled":false}')
                self.assertFalse(auto_demo.settings()['enabled'])

    def test_heartbeat_without_successful_exit_check_is_not_healthy(self):
        base={'heartbeat':100,'last_exit_check':100,'exit_policy':EXIT_POLICY,'exit_error':None}
        self.assertTrue(healthy(base,101))
        for changes in [{'last_exit_check':0},{'exit_error':'wrong account'},
                        {'heartbeat':120},{'exit_policy':'old'},{'heartbeat':80}]:
            self.assertFalse(healthy({**base,**changes},101))
