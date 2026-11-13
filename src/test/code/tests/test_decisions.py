import unittest
from scalp_lab.signals import decision_summary


class DecisionTests(unittest.TestCase):
    now="2026-11-04T15:00:30Z"

    def signal(self, **changes):
        item={"decision_time":"2026-11-04T15:00:00Z", "signal":"PAPER_LONG",
              "threshold":0.6, "long_probability_uncalibrated":0.7,
              "short_probability_uncalibrated":0.3}
        item.update(changes)
        return item

    def test_buy_and_short_qualified_signals(self):
        self.assertEqual(decision_summary(self.signal(),self.now)["action"],"BUY / LONG")
        short=self.signal(signal="PAPER_SHORT",long_probability_uncalibrated=0.2,short_probability_uncalibrated=0.8)
        self.assertEqual(decision_summary(short,self.now)["action"],"SELL / SHORT")

    def test_disabled_threshold_is_never_a_buy(self):
        result=decision_summary(self.signal(threshold=1.01),self.now)
        self.assertEqual(result["action"],"NO TRADE")
        self.assertIn("Waiting for new prices alone",result["reason"])

    def test_stale_bias_is_not_current_action(self):
        result=decision_summary(self.signal(decision_time="2026-11-03T21:00:00Z"),self.now)
        self.assertEqual(result["action"],"NO TRADE")
        self.assertEqual(result["lean"],"LONG")
        self.assertFalse(result["fresh"])

    def test_no_signal_does_not_become_buy_from_higher_score(self):
        self.assertEqual(decision_summary(self.signal(signal="NO_SIGNAL"),self.now)["action"],"NO TRADE")
        self.assertEqual(decision_summary({},self.now)["action"],"NO TRADE")
