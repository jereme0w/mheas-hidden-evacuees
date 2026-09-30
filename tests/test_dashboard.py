"""Short dashboard API and consistency checks, using temporary databases."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import APP_VERSION, create_app, seed_demo


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.database=str(Path(self.temp.name)/'reports.sqlite3')
        self.app=create_app({'TESTING':True,'DATABASE':self.database})
        self.client=self.app.test_client();seed_demo(self.app)

    def test_dashboard_and_asset_routes(self):
        for route,content in [('/dashboard',b'cityMap'),('/dashboard.js',b'/api/dashboard'),('/dashboard.css',b'primary-grid')]:
            with self.subTest(route=route):
                response=self.client.get(route)
                self.assertEqual(response.status_code,200)
                self.assertIn(content,response.data);response.close()

    def test_seeded_snapshot_is_consistent_and_has_context(self):
        data=self.client.get('/api/dashboard').json
        self.assertEqual(data['application_version'],APP_VERSION)
        self.assertEqual(data['alert_count'],1)
        self.assertEqual(data['submission_count'],65)
        self.assertEqual(data['fixture_submission_count'],0)
        self.assertEqual(sum(row['report_count'] for row in data['area_information_gaps']),65)
        self.assertEqual(sum(row['context']['occupied_households'] for row in data['area_information_gaps']),8000)
        west=next(row for row in data['area_information_gaps'] if row['region_id']=='westbridge')
        self.assertEqual(west['context']['communications'],'Outage')
        self.assertEqual(west['context']['shaking_intensity'],8.3)
        self.assertTrue(west['alert'])
        self.assertTrue(all(row['priority'] is not None for row in data['reports']))

    def test_demo_answers_use_form_scoring_and_cover_priorities(self):
        records=self.client.get('/api/reports').json['reports']
        self.assertEqual({r['priority']['priority'] for r in records}, {'Low','Moderate','High','Critical'})
        for record in records:
            response=self.client.post('/api/reports',json=record['original_report'])
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.json['priority']['score'],record['priority']['score'])
            self.assertEqual(response.json['priority']['priority'],record['priority']['priority'])

    def test_upgrade_legacy_fixtures_preserves_form_reports_and_is_idempotent(self):
        payload=json.loads((ROOT/'tests/cases/submission_cases.json').read_text())['valid'][0]['payload']
        posted=self.client.post('/api/reports',json=payload).json
        original=self.client.get('/api/reports/'+posted['report_id']).json
        records=self.client.get('/api/reports').json['reports']
        with closing(sqlite3.connect(self.database)) as connection,connection:
            for record in records:
                if record['source']=='synthetic_community_report':
                    record['source']='synthetic_count_fixture'
                    record['priority']=None
                    record.pop('original_report')
                    connection.execute("UPDATE riverford_reports SET record_json=? WHERE report_id=?",
                                       (json.dumps(record),record['report_id']))
        seed_demo(self.app)
        upgraded=self.client.get('/api/reports').json
        self.assertEqual(upgraded['count'],66)
        self.assertTrue(all(r['priority'] is not None for r in upgraded['reports']))
        self.assertEqual(self.client.get('/api/reports/'+posted['report_id']).json,original)
        seed_demo(self.app)
        self.assertEqual(self.client.get('/api/reports').json,upgraded)
        central=next(r for r in self.client.get('/api/regions').json['area_information_gaps'] if r['region_id']=='central')
        self.assertEqual(central['report_count'],37)

    def test_form_submission_appears_with_saved_priority(self):
        payload=json.loads((ROOT/'tests'/'cases'/'submission_cases.json').read_text())['valid'][3]['payload']
        posted=self.client.post('/api/reports',json=payload).json
        data=self.client.get('/api/dashboard').json
        record=next(row for row in data['reports'] if row['report_id']==posted['report_id'])
        self.assertEqual(record['priority']['priority'],'Critical')
        self.assertEqual(data['submission_count'],66)
        west=next(row for row in data['area_information_gaps'] if row['region_id']=='westbridge')
        self.assertEqual(west['report_count'],1)

    def test_database_failure_returns_unavailable_not_empty(self):
        with patch('app._connection',side_effect=OSError('Unavailable')):
            response=self.client.get('/api/dashboard')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('area_information_gaps',response.json)

    def test_incomplete_feed_is_marked_unknown(self):
        contexts=self.app.extensions['riverford_scenario']['contexts']
        contexts['westbridge']=replace(contexts['westbridge'],report_feed_complete=False)
        data=self.client.get('/api/dashboard').json
        west=next(row for row in data['area_information_gaps'] if row['region_id']=='westbridge')
        self.assertEqual(west['classification'],'Insufficient data')
        self.assertFalse(west['context']['report_feed_complete'])
        self.assertNotIn('expected_reports',west)

    def test_future_records_are_excluded_from_table_and_counts(self):
        from app import _insert
        from riverford_service import demo_records
        record=demo_records(self.app.extensions['riverford_scenario'])[0]
        record=record|{'report_id':'future','submitted_at':'2026-10-02T05:00:00+00:00'}
        with closing(sqlite3.connect(self.database)) as connection,connection:
            _insert(connection,record)
        data=self.client.get('/api/dashboard').json
        self.assertEqual(data['submission_count'],65)
        self.assertFalse(any(row['report_id']=='future' for row in data['reports']))


if __name__=='__main__':unittest.main()
