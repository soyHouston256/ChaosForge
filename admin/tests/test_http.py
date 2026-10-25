import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend import Demo
from controller import Controller
from server import make_handler


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(self.temp.name + '/db', Demo())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.controller))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        with urllib.request.urlopen(self.url + '/api/state') as r:
            self.state = json.load(r)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.controller.db.close()
        self.temp.cleanup()

    def post(self, body, headers):
        req = urllib.request.Request(self.url + '/api/start', data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_csrf_origin_and_host(self):
        body = {'service':'cartservice','duration':30}
        self.assertEqual(self.post(body, {}), 403)
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Origin':'https://evil.example'}
        self.assertEqual(self.post(body, h), 403)
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Host':'evil.example'}
        self.assertEqual(self.post(body, h), 403)
        self.assertIsNone(self.controller.active())

    def test_strict_fields_and_working_route(self):
        h = {'X-ChaosForge-Token':self.state['csrf'], 'Origin':self.url}
        self.assertEqual(self.post({'service':'cartservice','duration':30,'command':'echo nope'},h),409)
        self.assertEqual(self.post({'service':'cartservice','duration':30},h),200)
        self.assertEqual(self.post({'service':'paymentservice','duration':30},h),409)
        self.assertIn('simulados', self.state['mode'])
        self.controller.restore()
        self.controller.tick()
        self.assertIsNone(self.controller.active())


if __name__ == '__main__':
    unittest.main()
