import tempfile
import unittest
from pathlib import Path
import pandas as pd
from scalp_lab.gold_decisions import save,recent


class DecisionHistoryTests(unittest.TestCase):
    def test_broker_result_is_separate_and_survives_later_duplicate_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'decisions.db'
            r={'engine':'test','chart_signal':'BUY','action':'BUY setup','observed_at':1800000065,
               'frame':pd.DataFrame({'time':[1800000000]}),
               'scenarios':{'BUY':{'entry':2000.,'sl':1995.,'tp':2009.}},'reasons':[]}
            save([1,'Demo'],'GOLD',r,db,outcome={'state':'blocked','message':'Daily budget exceeded'})
            self.assertEqual(recent([1,'Demo'],['GOLD'],db_path=db)[0]['Execution status'],'Not submitted: blocked')
            save([1,'Demo'],'GOLD',r,db,outcome={'state':'filled','order':123,'price':2000.1})
            save([1,'Demo'],'GOLD',r,db,outcome={'state':'waiting','message':'Duplicate'})
            row=recent([1,'Demo'],['GOLD'],db_path=db)[0]
            self.assertEqual(row['Decision'],'BUY setup')
            self.assertEqual(row['Execution status'],'Broker: filled')
            self.assertEqual(row['Broker order'],123)
            self.assertEqual(row['Indicative entry'],2000.)

    def test_levels_survive_no_setup_and_duplicate_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'decisions.db'
            identity=[123,'Demo']
            result={'engine':'test','chart_signal':'BUY','action':'BUY setup',
                    'observed_at':1800000065,'frame':pd.DataFrame({'time':[1800000000]}),
                    'scenarios':{'BUY':{'entry':2000.,'sl':1995.,'tp':2009.,'lots':.01,'risk_pct':.5}},
                    'reasons':['Confirmed']}
            save(identity,'GOLD',result,db)
            result['scenarios']['BUY']['entry']=2001.
            save(identity,'GOLD',result,db)
            save(identity,'GOLD',{'chart_signal':'NONE','scenarios':{}},db)
            rows=recent(identity,['GOLD'],db_path=db)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['Indicative entry'],2000.)
            self.assertEqual(rows[0]['Risk (% equity)'],.5)
            self.assertEqual(recent([456,'Demo'],['GOLD'],db_path=db),[])
            self.assertEqual(recent(identity,['OTHER'],db_path=db),[])
            result['frame']=pd.DataFrame({'time':[1800000060]})
            result['observed_at']+=60
            save(identity,'GOLD',result,db)
            self.assertEqual(len(recent(identity,['GOLD'],db_path=db)),2)

    def test_blocked_setup_saved_and_later_qualification_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'decisions.db'
            r={'engine':'test','chart_signal':'SELL','action':'BLOCKED','observed_at':1800000065,
               'frame':pd.DataFrame({'time':[1800000000]}),
               'scenarios':{'SELL':{'entry':2000.,'sl':2005.,'tp':1991.}},'reasons':['Budget']}
            save([1,'Demo'],'GOLD',r,db)
            r['action']='SELL setup'
            save([1,'Demo'],'GOLD',r,db)
            self.assertEqual({x['Decision'] for x in recent([1,'Demo'],['GOLD'],db_path=db)},
                             {'BLOCKED','SELL setup'})
