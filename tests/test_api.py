"""Form/API/database regression tests. No benchmarks or training runs."""
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import APP_VERSION, create_app, seed_demo
from contextual_prioritisation_model import classify_priority


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database=str(Path(self.temp.name)/'reports.sqlite3')
        self.app=create_app({'TESTING':True,'DATABASE':self.database})
        self.client=self.app.test_client()
        self.cases=json.loads((ROOT/'tests'/'cases'/'submission_cases.json').read_text())
        self.payload=self.cases['valid'][0]['payload']
        # Keep connections alive until cleanup so implicit garbage collection
        # cannot hide leaks on Linux that leave locked files on Windows.
        self.connections=[]
        real_connect=sqlite3.connect
        class TrackedConnection(sqlite3.Connection):
            is_closed=False
            def close(inner):
                super(TrackedConnection,inner).close()
                inner.is_closed=True
        def tracked_connect(*args,**kwargs):
            kwargs['factory']=TrackedConnection
            connection=real_connect(*args,**kwargs)
            self.connections.append(connection)
            return connection
        patcher=patch('sqlite3.connect',side_effect=tracked_connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.check_connections_closed)

    def check_connections_closed(self):
        unclosed=[connection for connection in self.connections if not connection.is_closed]
        # Always release handles, including when the regression assertion fails.
        for connection in unclosed:
            connection.close()
        self.assertEqual(len(unclosed),0,'SQLite connections must be explicitly closed before temporary database cleanup')

    def test_form_context_and_script_routes(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'id="household_number"',response.data)
        self.assertNotIn(b'navigator.geolocation',response.data)
        self.assertIn(b'name="vulnerability_count"',response.data)
        self.assertIn(b'name="high_risk_vulnerabilities"',response.data)
        self.assertIn(b'id="medical"',response.data)
        response.close()
        response=self.client.get('/form.js')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'vulnerability_count: data.get',response.data)
        self.assertIn(b'primary_needs: needs',response.data)
        response.close()
        self.assertEqual(self.client.get('/api/health').json,{'status':'ok'})
        self.assertEqual(self.client.get('/api/version').json['version'],APP_VERSION)
        context=self.client.get('/api/context').json
        self.assertEqual(len(context['regions']),6)
        self.assertEqual(context['clock_mode'],'fixed_demo_snapshot')

    def test_all_four_report_priorities(self):
        for case in self.cases['valid']:
            with self.subTest(case=case['name']):
                response=self.client.post('/api/reports',json=case['payload'])
                self.assertEqual(response.status_code,201,response.json)
                self.assertEqual(response.json['priority']['priority'],case['priority'])
                self.assertEqual(response.json['priority']['score'],case['score'])

    def test_all_invalid_submission_cases_are_not_saved(self):
        for case in self.cases['invalid']:
            with self.subTest(case=case['name']):
                response=self.client.post('/api/reports',json=case['payload'])
                self.assertEqual(response.status_code,case['status'],response.json)
        self.assertEqual(self.client.get('/api/reports').json['count'],0)

    def test_commit_and_model_results_are_persisted(self):
        response=self.client.post('/api/reports',json=self.payload)
        self.assertEqual(response.status_code,201)
        details=self.client.get('/api/reports/'+response.json['report_id']).json
        self.assertEqual(details['original_report'],self.payload)
        self.assertEqual(details['priority'],response.json['priority'])
        self.assertEqual(details['regional_assessment'],response.json['regional_assessment'])
        self.assertEqual(details['context']['source'],'fictional_backend_datasets')
        self.assertNotEqual(details['submitted_at'],details['created_at'])
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM riverford_reports').fetchone()[0],1)
        restarted=create_app({'TESTING':True,'DATABASE':self.database}).test_client()
        self.assertEqual(restarted.get('/api/reports').json['count'],1)

    def test_demo_seed_is_idempotent_and_matches_cases(self):
        seed_demo(self.app);seed_demo(self.app)
        self.assertEqual(self.client.get('/api/reports').json['count'],65)
        expected=json.loads((ROOT/'tests'/'cases'/'regional_expected.json').read_text())['regions']
        snapshot=self.client.get('/api/regions').json
        self.assertEqual(snapshot['alert_count'],1)
        for row in snapshot['area_information_gaps']:
            with self.subTest(region=row['region_id']):
                self.assertEqual(row['report_count'],expected[row['region_id']]['count'])
                self.assertEqual(row['classification'],expected[row['region_id']]['classification'])
        self.assertTrue(all(row['priority'] is not None for row in self.client.get('/api/reports').json['reports']))

    def test_submissions_change_regional_counts(self):
        seed_demo(self.app)
        response=self.client.post('/api/reports',json=self.payload)
        self.assertEqual(response.json['regional_assessment']['report_count'],37)
        rows=self.client.get('/api/regions').json['area_information_gaps']
        self.assertEqual(next(row for row in rows if row['region_id']=='central')['report_count'],37)

    def test_updates_count_each_household_once(self):
        one=self.client.post('/api/reports',json=self.payload)
        two=self.client.post('/api/reports',json=self.payload|{'self_reported_urgency':9})
        self.assertNotEqual(one.json['report_id'],two.json['report_id'])
        self.assertEqual(two.json['regional_assessment']['report_count'],1)
        self.assertEqual(two.json['regional_assessment']['submission_count'],2)
        self.assertNotEqual(one.json['priority']['score'],two.json['priority']['score'])

    def test_seeded_household_and_form_update_share_identifier(self):
        seed_demo(self.app)
        response=self.client.post('/api/reports',json=self.payload|{'household_number':1})
        self.assertEqual(response.json['regional_assessment']['report_count'],36)

    def test_five_westbridge_reports_still_trigger_investigation(self):
        payload=self.cases['valid'][3]['payload']
        for number in range(1,6):
            response=self.client.post('/api/reports',json=payload|{'household_number':number})
            self.assertEqual(response.status_code,201)
        self.assertTrue(response.json['regional_assessment']['alert'])

    def test_html_form_aliases_and_repeated_needs(self):
        form=MultiDict({key:value for key,value in self.payload.items() if key not in ('primary_needs','high_risk_vulnerabilities')})
        form.add('needs','food');form.add('needs','rescue_evacuation')
        response=self.client.post('/api/reports',data=form)
        self.assertEqual(response.status_code,201,response.json)
        record=self.client.get('/api/reports/'+response.json['report_id']).json
        self.assertEqual(record['model_report']['needs'],['food','rescue/evacuation'])
        self.assertEqual(record['priority']['normalised_factors']['N'],10)

    def test_duplicate_scalar_form_fields_are_rejected(self):
        form=MultiDict(self.payload|{'primary_needs':'food'})
        form.add('region_id','westbridge')
        self.assertEqual(self.client.post('/api/reports',data=form).status_code,422)

    def test_request_errors(self):
        self.assertEqual(self.client.post('/api/reports',json=[]).status_code,400)
        self.assertEqual(self.client.post('/api/reports',data='{',content_type='application/json').status_code,400)
        self.assertEqual(self.client.post('/api/reports',data='x',content_type='text/plain').status_code,415)
        self.assertEqual(self.client.post('/api/reports',data=' '*70000,content_type='application/json').status_code,413)
        self.assertEqual(self.client.post('/api/reports',data={'photo':(io.BytesIO(b'data'),'photo.png')}).status_code,422)
        self.assertEqual(self.client.post('/api/reports',json=self.payload|{'household_number':float('nan')}).status_code,422)
        self.assertEqual(self.client.get('/api/reports/nonexistent').status_code,404)

    def test_storage_failure_cannot_return_success(self):
        with patch('app._save_report',side_effect=sqlite3.OperationalError('disk full')):
            response=self.client.post('/api/reports',json=self.payload)
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.client.get('/api/reports').json['count'],0)

    def test_assessment_failure_rolls_back_submission(self):
        with patch('app.assess',side_effect=ValueError('Bad input')):
            response=self.client.post('/api/reports',json=self.payload)
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.client.get('/api/reports').json['count'],0)

    def test_unavailable_database_is_not_treated_as_zero_reports(self):
        with patch('app._connection',side_effect=OSError('Unavailable')):
            response=self.client.get('/api/regions')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('area_information_gaps',response.json)

    def test_incomplete_collection_feed_is_explicit(self):
        from dataclasses import replace
        contexts=self.app.extensions['riverford_scenario']['contexts']
        contexts['westbridge']=replace(contexts['westbridge'],report_feed_complete=False)
        snapshot=self.client.get('/api/regions').json
        west=next(row for row in snapshot['area_information_gaps'] if row['region_id']=='westbridge')
        self.assertEqual(west['classification'],'Insufficient data')
        self.assertNotIn('expected_reports',west)

    def test_old_database_table_is_preserved(self):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE reports (report_id TEXT PRIMARY KEY, record_json TEXT)')
            connection.execute('INSERT INTO reports VALUES (?,?)',('old','{"legacy":true}'))
        self.assertEqual(self.client.post('/api/reports',json=self.payload).status_code,201)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute('SELECT record_json FROM reports').fetchone()[0],'{"legacy":true}')

    def test_other_events_are_not_used(self):
        self.client.get('/api/reports')
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('INSERT INTO riverford_reports VALUES (?,?,?,?,?,?,?)',
                               ('other','other-event','central','x','x','x','not even JSON'))
        self.assertEqual(self.client.get('/api/reports').json['count'],0)
        self.assertEqual(self.client.get('/api/regions').status_code,200)

    def test_priority_threshold_boundaries(self):
        for value,expected in [(2.999,'Low'),(3,'Moderate'),(6.999,'Moderate'),(7,'High'),(8.999,'High'),(9,'Critical')]:
            self.assertEqual(classify_priority(value),expected)

    def test_failed_database_initialisation_closes_connection(self):
        from app import _connection
        from unittest.mock import Mock
        connection=Mock()
        connection.execute.side_effect=sqlite3.OperationalError('Initialisation failed')
        with patch('app.sqlite3.connect',return_value=connection):
            with self.assertRaises(sqlite3.OperationalError):
                _connection(self.database)
        connection.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
