"""One short HTTP flow through a real local server on an ephemeral port."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from werkzeug.serving import make_server

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app, seed_demo


class HTTPTests(unittest.TestCase):
    def test_form_submission_and_regional_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app({'TESTING':True,'DATABASE':str(Path(directory)/'reports.sqlite3')})
            seed_demo(app)
            server=make_server('127.0.0.1',0,app)
            worker=threading.Thread(target=lambda:server.serve_forever(poll_interval=.05),daemon=True)
            worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base+'/',timeout=2) as response:
                    self.assertIn(b'/form.js',response.read())
                with urlopen(base+'/form.js',timeout=2) as response:
                    self.assertIn(b'/api/context',response.read())
                payload=json.loads((ROOT/'tests'/'cases'/'submission_cases.json').read_text())['valid'][0]['payload']
                request=Request(base+'/api/reports',data=json.dumps(payload).encode(),
                                headers={'Content-Type':'application/json'},method='POST')
                with urlopen(request,timeout=2) as response:
                    self.assertEqual(response.status,201)
                    posted=json.loads(response.read())
                    self.assertEqual(posted['regional_assessment']['report_count'],37)
                with urlopen(base+'/api/reports/'+posted['report_id'],timeout=2) as response:
                    self.assertEqual(json.loads(response.read())['priority'],posted['priority'])
                with urlopen(base+'/api/regions',timeout=2) as response:
                    snapshot=json.loads(response.read())
                    west=next(row for row in snapshot['area_information_gaps'] if row['region_id']=='westbridge')
                    self.assertTrue(west['alert'])
            finally:
                server.shutdown();server.server_close();worker.join(timeout=1)


if __name__=='__main__':
    unittest.main()
