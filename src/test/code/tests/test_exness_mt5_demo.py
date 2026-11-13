import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from scalp_lab_exness.mt5_demo import DemoError,checked_account,initialize,preview,submit,quote
from scalp_lab_exness_live import mt5_demo as live_bridge


def terminal():
    mt5=NS(ACCOUNT_TRADE_MODE_DEMO=0,ACCOUNT_TRADE_MODE_REAL=2,SYMBOL_TRADE_MODE_FULL=4,SYMBOL_TRADE_MODE_LONGONLY=1,
           SYMBOL_TRADE_MODE_SHORTONLY=2,SYMBOL_TRADE_EXECUTION_MARKET=2,
           SYMBOL_TRADE_EXECUTION_REQUEST=0,SYMBOL_TRADE_EXECUTION_INSTANT=1,
           ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,ORDER_FILLING_RETURN=2,
           TRADE_ACTION_DEAL=1,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,ORDER_TIME_GTC=0,
           TRADE_RETCODE_DONE=10009,TRADE_RETCODE_DONE_PARTIAL=10010,TRADE_RETCODE_PLACED=10008)
    mt5.account_info=Mock(return_value=NS(login=123,server="Exness-MT5Trial",company="Exness Technologies Ltd",trade_mode=0,trade_allowed=True,trade_expert=True,currency="USD"))
    mt5.terminal_info=Mock(return_value=NS(connected=True,trade_allowed=True,tradeapi_disabled=False))
    mt5.symbol_select=Mock(return_value=True)
    mt5.symbol_info=Mock(return_value=NS(trade_mode=4,volume_min=0.01,volume_max=10.0,volume_step=0.01,
                                        trade_tick_size=0.01,point=0.01,digits=2,trade_stops_level=1,order_mode=49,filling_mode=1,trade_exemode=2))
    mt5.symbol_info_tick=Mock(return_value=NS(bid=100.0,ask=100.02,time_msc=int(time.time()*1000),time=int(time.time())))
    mt5.positions_get=Mock(return_value=())
    mt5.orders_get=Mock(return_value=())
    mt5.order_check=Mock(return_value=NS(retcode=0,comment="Done"))
    mt5.order_calc_margin=Mock(return_value=10)
    mt5.order_calc_profit=Mock(return_value=1)
    mt5.order_send=Mock(return_value=NS(retcode=10009,order=1,deal=2,volume=0.01,price=100.02,comment="Done"))
    return mt5


class DemoTradeTests(unittest.TestCase):
    identity=(123,"Exness-MT5Trial")

    def test_only_exness_demo_accounts_are_accepted(self):
        m=terminal()
        self.assertIsNotNone(checked_account(m,self.identity))
        for company,server in (("IC Markets Global","ICMarketsSC-Demo"),
                               ("Exness Technologies Ltd","Other-Demo"),
                               ("Other Broker","Exness-MT5Trial")):
            m.account_info.return_value.company=company
            m.account_info.return_value.server=server
            with self.assertRaisesRegex(DemoError,"not identified as Exness"):
                checked_account(m)

    def test_configured_terminal_path(self):
        m = Mock()
        path = r"C:\Program Files\Exness MT5\terminal64.exe"
        with patch.dict("scalp_lab_exness.mt5_demo.os.environ", {"EXNESS_MT5_PATH": path}):
            initialize(m)
        m.initialize.assert_called_once_with(path, timeout=10000)

    def test_instant_execution_supports_fok_without_symbol_flags(self):
        m = terminal()
        m.symbol_info.return_value.trade_exemode = m.SYMBOL_TRADE_EXECUTION_INSTANT
        m.symbol_info.return_value.filling_mode = 0
        ticket = self.make(m)
        self.assertEqual(ticket["request"]["type_filling"], m.ORDER_FILLING_FOK)

    def test_server_time_conversion_and_staleness(self):
        m=terminal()
        with patch("scalp_lab_exness.mt5_demo.time.time",return_value=1800000000):
            for offset in (0,2,3):
                tick=m.symbol_info_tick.return_value
                tick.time_msc=(1800000000+offset*3600-5)*1000
                self.assertIs(quote(m,"TEST",offset),tick)
                tick.time_msc-=30000
                with self.assertRaises(DemoError):
                    quote(m,"TEST",offset)
                tick.time_msc=(1800000000+offset*3600+10)*1000
                with self.assertRaises(DemoError):
                    quote(m,"TEST",offset)
        m.order_send.assert_not_called()

    def make(self,m,side="BUY",lots=0.01):
        with patch("scalp_lab_exness.mt5_demo.api",return_value=m):
            return preview(self.identity,"TEST",side,lots,18,12)

    def send(self,m,ticket,path):
        with patch("scalp_lab_exness.mt5_demo.api",return_value=m), \
             patch("scalp_lab_exness.auto_demo.settings",return_value={'enabled':False}):
            return submit(ticket,path)

    def test_real_account_can_preview_and_submit_with_mocked_mt5(self):
        m=terminal()
        m.account_info.return_value.trade_mode=m.ACCOUNT_TRADE_MODE_REAL
        m.account_info.return_value.server="Exness-MT5Real"
        with patch.object(live_bridge, "api", return_value=m), \
             patch("scalp_lab_exness_live.auto_demo.settings",return_value={'enabled':False}):
            ticket=live_bridge.preview((123,"Exness-MT5Real"),"XAUUSDm","BUY",0.01,18,12)
            outcome=live_bridge.submit(ticket,":memory:")
        self.assertEqual(outcome["state"],"filled")
        m.order_send.assert_called_once()

    def test_real_exness_account_can_be_read_without_trading_permissions(self):
        m = terminal()
        account = m.account_info.return_value
        account.trade_mode = m.ACCOUNT_TRADE_MODE_REAL
        account.server = 'Exness-MT5Real'
        m.terminal_info.return_value.tradeapi_disabled = True
        identity = (account.login, account.server)
        with self.assertRaisesRegex(DemoError, 'not DEMO'):
            checked_account(m, identity, read_only=True)
        self.assertIs(live_bridge.checked_account(m, identity, read_only=True), account)
        with self.assertRaisesRegex(live_bridge.DemoError, 'account changed'):
            live_bridge.checked_account(m, (999, account.server), read_only=True)
        with self.assertRaisesRegex(live_bridge.DemoError, 'Trading through Python is disabled'):
            live_bridge.checked_account(m, identity)
        account.company = 'Other Broker'
        with self.assertRaisesRegex(live_bridge.DemoError, 'not identified as Exness'):
            live_bridge.checked_account(m, identity, read_only=True)
        m.order_send.assert_not_called()

    def test_account_switch_during_final_check_blocks_send(self):
        m=terminal()
        ticket=self.make(m)
        def switch(request):
            m.account_info.return_value.login=999
            return NS(retcode=0)
        m.order_check.side_effect=switch
        with self.assertRaises(DemoError):
            self.send(m,ticket,":memory:")
        m.order_send.assert_not_called()

    def test_expired_ticket_and_stale_quote(self):
        m=terminal()
        ticket=self.make(m)
        ticket["created"]-=31
        with self.assertRaises(DemoError):
            self.send(m,ticket,":memory:")
        m.symbol_info_tick.return_value.time_msc-=60000
        with self.assertRaises(DemoError):
            self.make(m)
        m.order_send.assert_not_called()

    def test_volume_step_existing_position_and_missing_permissions(self):
        m=terminal()
        with self.assertRaises(DemoError):
            self.make(m,lots=0.015)
        m.positions_get.return_value=(NS(),)
        with self.assertRaises(DemoError):
            self.make(m)
        m.positions_get.return_value=()
        m.terminal_info.return_value.tradeapi_disabled=True
        with self.assertRaises(DemoError):
            self.make(m)

    def test_quote_movement_and_rejection_do_not_send(self):
        m=terminal()
        ticket=self.make(m)
        m.symbol_info_tick.return_value.ask=101
        with self.assertRaisesRegex(DemoError, "Price moved beyond the ticket tolerance"):
            self.send(m,ticket,":memory:")
        m.symbol_info_tick.return_value.ask=100.02
        m.order_check.return_value=NS(retcode=10016,comment="Invalid stops")
        with self.assertRaises(DemoError):
            self.send(m,ticket,":memory:")
        m.order_send.assert_not_called()

    def test_duplicate_and_unknown_outcome_never_retry(self):
        for result in (NS(retcode=10009,order=1,deal=2,volume=0.01,price=100.02,comment="Done"),None):
            m=terminal()
            ticket=self.make(m)
            m.order_send.return_value=result
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/"orders.sqlite3"
                outcome=self.send(m,ticket,path)
                self.assertEqual(outcome["state"],"filled" if result else "unknown")
                with self.assertRaises(DemoError):
                    self.send(m,ticket,path)
            m.order_send.assert_called_once()

    def test_buy_and_sell_use_correct_quote_and_attached_exits(self):
        m=terminal()
        buy=self.make(m)["request"]
        sell=self.make(m,"SELL")["request"]
        self.assertEqual(buy["price"],100.02)
        self.assertEqual(sell["price"],100.0)
        self.assertLess(buy["sl"],buy["price"])
        self.assertGreater(buy["tp"],buy["price"])
        self.assertGreater(sell["sl"],sell["price"])
        self.assertLess(sell["tp"],sell["price"])
        self.assertEqual(buy["type_filling"],0)
        m.order_send.assert_not_called()
