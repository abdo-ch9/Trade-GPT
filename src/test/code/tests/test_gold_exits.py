import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from scalp_lab import gold_exits as exits
from scalp_lab import auto_demo as auto
from scalp_lab.mt5_demo import DemoError


class TimedExitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'journal.db'
        self.identity=[123,'ICMarketsSC-Demo']
        self.now=time.time()
        self.context={'exit_policy':exits.EXIT_POLICY,'symbol':'GOLD','type':0,'volume':.01,
                      'magic':auto.MAGIC,'offset':2,'filling':0,'deadline_utc':self.now-1}
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE entries(token TEXT,account TEXT,state TEXT,detail TEXT)')
            db.execute('INSERT INTO entries VALUES (?,?,?,?)',('signal',json.dumps(self.identity),'filled',
                       json.dumps({'order':12,'execution_context':self.context})))
            db.commit()
        self.p=NS(symbol='GOLD',volume=.01,sl=1990,type=0,magic=auto.MAGIC,ticket=99,identifier=100)
        self.deal=NS(position_id=100,symbol='GOLD',magic=auto.MAGIC,entry=0,order=12)
        self.mt5=Mock(ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,TRADE_ACTION_DEAL=1,
                      ORDER_TIME_GTC=0,TRADE_RETCODE_DONE=10009,DEAL_ENTRY_IN=0,
                      DEAL_ENTRY_OUT=1,DEAL_ENTRY_INOUT=2,DEAL_ENTRY_OUT_BY=3)
        self.mt5.positions_get.return_value=[self.p]
        self.mt5.history_deals_get.return_value=[self.deal]
        self.mt5.order_check.return_value=NS(retcode=0,comment='OK')
        self.mt5.order_send.return_value=NS(retcode=10009,comment='Done',price=2000)
        for obj,name,value in [(exits.bridge,'api',self.mt5),(exits.bridge,'checked_account',NS()),
                               (exits.bridge,'quote',NS(bid=2000,ask=2001)),(auto,'stop',None),(exits,'record',None)]:
            p=patch.object(obj,name,return_value=value)
            mock=p.start();self.addCleanup(p.stop)
            if name=='record':self.events=mock

    def test_deadline_matches_fifteenth_future_candle_close(self):
        self.assertEqual(exits.HOLD_BARS,15)
        self.assertEqual(exits.deadline(1800000000,2),1800000000+960-7200)

    def test_due_position_closes_exact_ticket_once(self):
        exits.manage(self.identity,self.db,self.now)
        exits.manage(self.identity,self.db,self.now+1)
        self.mt5.order_send.assert_called_once()
        r=self.mt5.order_send.call_args.args[0]
        self.assertEqual(r['position'],99)
        self.assertEqual(r['type'],1)
        self.assertEqual(r['volume'],.01)

    def test_early_position_is_not_closed(self):
        exits.manage(self.identity,self.db,self.now-10)
        self.mt5.order_send.assert_not_called()

    def test_unknown_send_is_not_retried(self):
        self.mt5.order_send.return_value=None
        exits.manage(self.identity,self.db,self.now)
        exits.manage(self.identity,self.db,self.now+10)
        self.mt5.order_send.assert_called_once()

    def test_old_entries_are_never_closed(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE entries SET detail=?',(json.dumps({'order':12}),))
            db.commit()
        exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()

    def test_tesla_and_modified_positions_are_not_closed(self):
        for field,value in [('symbol','Tesla'),('volume',.02),('magic',1)]:
            p=NS(**vars(self.p));setattr(p,field,value)
            self.mt5.positions_get.return_value=[p]
            exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()

    def test_real_or_changed_account_blocks_exit(self):
        with patch.object(exits.bridge,'checked_account',side_effect=DemoError('wrong account')):
            with self.assertRaises(DemoError):exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()

    def test_stale_quote_retries_preflight_without_sending(self):
        with patch.object(exits.bridge,'quote',side_effect=DemoError('stale')):
            exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()
        exits.manage(self.identity,self.db,self.now+1)
        self.mt5.order_send.assert_called_once()

    def test_other_entry_in_netting_position_is_not_closed(self):
        other=NS(**vars(self.deal));other.order=55
        self.mt5.history_deals_get.side_effect=lambda **kw:[self.deal] if 'ticket' in kw else [self.deal,other]
        exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()

    def test_broker_closed_position_records_costs_without_send(self):
        self.mt5.positions_get.return_value=[]
        closed=NS(entry=1,profit=5,commission=-.1,swap=0,fee=0)
        self.mt5.history_deals_get.side_effect=lambda **kw:[self.deal] if 'ticket' in kw else [closed]
        exits.manage(self.identity,self.db,self.now)
        self.mt5.order_send.assert_not_called()
        with closing(sqlite3.connect(self.db)) as db:
            state,detail=db.execute('SELECT state,detail FROM exits').fetchone()
        self.assertEqual(state,'closed')
        self.assertAlmostEqual(json.loads(detail)['net_pnl'],4.9)


if __name__=='__main__':unittest.main()
