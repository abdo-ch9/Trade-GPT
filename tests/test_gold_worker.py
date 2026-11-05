import unittest
from unittest.mock import Mock, patch
from scalp_lab import gold_worker as worker
from scalp_lab.mt5_demo import DemoError


class WorkerReconnectTests(unittest.TestCase):
    def test_disconnected_worker_reinitializes_and_checks_expected_account(self):
        mt5 = Mock()
        mt5.terminal_info.return_value.connected = False
        with patch.object(worker.bridge, 'api', return_value=mt5), patch.object(worker.bridge, 'checked_account') as check:
            worker.reconnect((123, 'demo'))
            mt5.initialize.assert_called_once_with(timeout=10000)
            check.assert_called_once_with(mt5, (123, 'demo'))
            mt5.order_send.assert_not_called()

    def test_healthy_connection_is_not_reinitialized(self):
        mt5 = Mock()
        with patch.object(worker.bridge, 'api', return_value=mt5), patch.object(worker.bridge, 'checked_account') as check:
            worker.reconnect((123, 'demo'))
            mt5.initialize.assert_not_called()
            check.assert_called_once()

    def test_failed_reconnection_blocks(self):
        mt5 = Mock()
        mt5.terminal_info.return_value = None
        mt5.initialize.return_value = False
        with patch.object(worker.bridge, 'api', return_value=mt5), patch.object(worker.bridge, 'checked_account') as check:
            with self.assertRaisesRegex(DemoError, 'cannot reconnect'):
                worker.reconnect((123, 'demo'))
            check.assert_not_called()

    def test_account_change_remains_blocked_after_reconnect(self):
        mt5 = Mock()
        mt5.terminal_info.return_value = None
        with patch.object(worker.bridge, 'api', return_value=mt5), patch.object(worker.bridge, 'checked_account', side_effect=DemoError('account changed')):
            with self.assertRaisesRegex(DemoError, 'account changed'):
                worker.reconnect((123, 'demo'))
