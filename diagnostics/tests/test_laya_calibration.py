"""Calibration changes confidence without fabricating labels or reversing rank."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'app'))
from laya_adapter import calibrate_probabilities


class CalibrationTests(unittest.TestCase):
    def test_temperature_one_preserves_distribution(self):
        values=[.96,.02,.01,.01]
        for actual,expected in zip(calibrate_probabilities(values),values):
            self.assertAlmostEqual(actual,expected)

    def test_softening_preserves_choice_and_normalization(self):
        values=calibrate_probabilities([.96,.02,.01,.01],1.2)
        self.assertEqual(max(range(4),key=values.__getitem__),0)
        self.assertLess(values[0],.96)
        self.assertAlmostEqual(sum(values),1)

    def test_rejects_invalid_temperature(self):
        for temperature in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                calibrate_probabilities([.9,.1],temperature)


if __name__=='__main__':unittest.main()
