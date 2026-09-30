"""Small functional checks; no performance benchmarks or training loops."""
import json
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from regional_model import RegionalReportModel
from demo_regions import load_regions
from contextual_prioritisation_model import (
    AreaContext, CommunityReport, evaluate_city_snapshot, prioritise_report,
    normalise_urgency, PRIORITY_WEIGHTS,
)


class RegionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=RegionalReportModel.load(ROOT/'models'/'regional_model.json')
        cls.rows=load_regions(ROOT/'datasets'/'riverford')
        cls.west=next(row for row in cls.rows if row['region_id']=='westbridge')

    def test_damaged_silent_region_is_flagged(self):
        results={row['region_id']:row for row in self.model.classify_regions(self.rows)}
        self.assertTrue(results['westbridge']['alert'])
        self.assertGreater(results['westbridge']['expected_reports'],50)
        self.assertFalse(results['industrial']['alert'])

    def test_five_reports_do_not_erase_large_gap(self):
        result=self.model.classify_region(self.west|{'reports_received':5})
        self.assertTrue(result['alert'])

    def test_larger_exposure_means_more_expected_reports(self):
        row=self.west|{'occupied_households':1000}
        self.assertAlmostEqual(self.model.expected_reports(row|{'occupied_households':2000}),
                               2*self.model.expected_reports(row))

    def test_outage_does_not_lower_baseline(self):
        a=self.model.classify_region(self.west)
        b=self.model.classify_region(self.west|{'communications_available':True})
        self.assertEqual(a['expected_reports'],b['expected_reports'])
        self.assertEqual(a['lower_tail_probability'],b['lower_tail_probability'])

    def test_missing_feed_is_unknown_not_zero(self):
        result=self.model.classify_region(self.west|{'report_feed_complete':False})
        self.assertEqual(result['classification'],'Insufficient data')
        self.assertNotIn('expected_reports',result)

    def test_early_and_outside_range_cases_require_review(self):
        self.assertEqual(self.model.classify_region(self.west|{'hours_since_earthquake':.1})['classification'],'Monitor')
        self.assertEqual(self.model.classify_region(self.west|{'hours_since_earthquake':30})['classification'],'Outside training range')

    def test_invalid_counts_are_rejected(self):
        result=self.model.classify_region(self.west|{'reports_received':-1})
        self.assertEqual(result['classification'],'Insufficient data')

    def test_held_out_earthquakes_have_no_overlap(self):
        metrics=json.loads((ROOT/'models'/'validation_metrics.json').read_text())
        self.assertEqual(metrics['event_split_overlap'],0)
        self.assertLess(metrics['model_poisson_deviance'],metrics['constant_rate_poisson_deviance'])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,1,5,tzinfo=timezone.utc)
        self.context=AreaContext('Westbridge',4200,1680,'Severe',8.3,.85,'Severe','Outage',.8,
                                 self.now-timedelta(hours=2),self.now)
        self.report=CommunityReport('W-001','Westbridge','fictional-westbridge-001',
                                    self.now-timedelta(minutes=15),2,False,4,['water'],'unsure','no')
        self.model=RegionalReportModel.load(ROOT/'models'/'regional_model.json')

    def test_distinct_households_and_event_window(self):
        repeat=replace(self.report,report_id='W-002')
        earlier=replace(self.report,report_id='PRE',household_id='fictional-pre',submitted_at=self.now-timedelta(days=1))
        future=replace(self.report,report_id='FUTURE',household_id='fictional-future',submitted_at=self.now+timedelta(hours=1))
        snapshot=evaluate_city_snapshot([self.context],[self.report,repeat,earlier,future],self.now,self.model)
        result=snapshot['area_information_gaps'][0]
        self.assertEqual(result['report_count'],1)
        self.assertEqual(result['submission_count'],2)
        self.assertEqual(len(snapshot['report_priorities']),2)
        self.assertTrue(result['alert'])

    def test_no_report_regions_are_assessed(self):
        snapshot=evaluate_city_snapshot([self.context],[],self.now,self.model)
        self.assertTrue(snapshot['area_information_gaps'][0]['alert'])

    def test_non_sensitive_report_priority(self):
        result=prioritise_report(self.report,self.context)
        self.assertNotIn('V',result['normalised_factors'])
        self.assertAlmostEqual(sum(PRIORITY_WEIGHTS.values()),1)
        self.assertEqual(normalise_urgency(10),10)
        with self.assertRaises(ValueError):
            prioritise_report(replace(self.report,needs=['medical']),self.context)

    def test_naive_datetimes_and_duplicate_districts_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_city_snapshot([self.context],[],self.now.replace(tzinfo=None),self.model)
        with self.assertRaises(ValueError):
            evaluate_city_snapshot([self.context,self.context],[],self.now,self.model)


if __name__=='__main__':
    unittest.main()
