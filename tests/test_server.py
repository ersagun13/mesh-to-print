import base64
import json
from pathlib import Path
import tempfile
import unittest
try:
    from meshprint.server import Policy, JobManager, validate_submission, cleanup_workspace, make_handler
    from meshprint.formats import MeshError, write_stl
    from test_engine import cube
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

class ServerTests(unittest.TestCase):

    def setUp(self):
        self.assertTrue(AVAILABLE, 'bounded local server is not implemented')

    def test_host_origin_and_token(self):
        p = Policy(12345, 'secret')
        p.check('GET', {'Host': '127.0.0.1:12345'})
        p.check(
            'POST',
            {'Host': '127.0.0.1:12345', 'Origin': 'http://127.0.0.1:12345', 'X-Local-Token': 'secret'}
        )
        for method, headers in [
            ('GET', {'Host': 'evil.example'}),
            ('GET', {'Host': '127.0.0.1:12345', 'Origin': 'https://evil.example'}),
            ('POST', {'Host': '127.0.0.1:12345', 'X-Local-Token': 'secret'}),
            (
                'POST',
                {'Host': '127.0.0.1:12345', 'Origin': 'http://127.0.0.1:12345', 'X-Local-Token': 'wrong'}
            )
        ]:
            with self.assertRaises(MeshError):
                p.check(method, headers)

    def test_submission_rejects_traversal_size_and_unknown_keys(self):
        good = {
            'filename': 'cube.stl',
            'content_base64': base64.b64encode(write_stl(cube())).decode(),
            'options': {}
        }
        filename, data, opt = validate_submission(good)
        self.assertEqual(filename, 'cube.stl')
        for change in [
            {'filename': '../../secret.stl'},
            {'filename': 'C:\\secret.stl'},
            {'content_base64': '@@@'},
            {'options': {'samples': -1}},
            {'command': 'anything'}
        ]:
            with self.assertRaises(MeshError):
                validate_submission({**good, **change})

    def test_request_path_policy_and_clean_worker_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = JobManager(Path(temp) / 'jobs', start_worker=False)
            handler = object.__new__(make_handler(manager, Policy(1234, 'secret')))
            for path in [
                '/api/jobs/%2e%2e/files/secret',
                '/../secret',
                '/a\\b',
                'https://evil.example/api/config',
                '/api/config?evil=1'
            ]:
                handler.path = path
                with self.assertRaises(MeshError):
                    handler.safe_path()
            bad = manager.submit('bad.stl', b'not a valid STL', {})
            manager.run_next()
            result = manager.get(bad['job_id'])
            self.assertEqual(result['status'], 'failed')
            self.assertIn('STL', result['error'])
            self.assertEqual(result['artifacts'], [])
            manager.close()

    def test_job_worker_and_registered_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = JobManager(Path(temp) / 'jobs', start_worker=False)
            job = manager.submit('cube.stl', write_stl(cube()), {'samples': 8})
            self.assertEqual(job['status'], 'queued')
            manager.run_next()
            status = manager.get(job['job_id'])
            self.assertEqual(status['status'], 'completed', status['error'])
            self.assertEqual(status['progress'], 1)
            self.assertEqual(status['report']['volume']['volume_mm3'], 8000)
            self.assertTrue(manager.artifact_path(job['job_id'], 'report.json').is_file())
            for name in ['../report.json', '%2e%2e', 'source.stl', 'missing']:
                with self.assertRaises(MeshError):
                    manager.artifact_path(job['job_id'], name)
            with self.assertRaises(MeshError):
                manager.get('../')
            manager.close()
            self.assertEqual(cleanup_workspace(Path(temp) / 'jobs'), 1)
            with self.assertRaises(MeshError):
                cleanup_workspace(Path(temp))
if __name__ == '__main__':
    unittest.main()
