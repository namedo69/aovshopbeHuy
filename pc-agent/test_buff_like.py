import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
import urllib.error
from buff_like import ApiError, run_console
from buff_like import Bridge


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.bridge = Bridge('https://example.com', 18801, self.path)
        self.bridge.state['active'] = {
            'order_id': 'order', 'target_name': 'Hero', 'requested': 100,
            'claimToken': 'token', 'submissionIntent': True,
        }
        self.bridge.save()

    def test_restart_after_uncertain_post_does_not_submit_again(self):
        restarted = Bridge('https://example.com', 18801, self.path)
        restarted.request = Mock()
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
            restarted.tick()
        restarted.request.assert_not_called()

    def test_login_error_identifies_web_without_response_secrets(self):
        self.bridge.remote.open = Mock(side_effect=urllib.error.HTTPError(
            'https://example.com/api/v1/auth/login', 401, 'secret body', {}, None))
        with self.assertRaisesRegex(ApiError, 'WEB backend.*HTTP 401') as error:
            self.bridge.login('admin@example.com', 'do-not-log-password')
        self.assertNotIn('do-not-log-password', str(error.exception))
        self.assertNotIn('secret body', str(error.exception))

    def test_packaged_console_waits_after_failure(self):
        with patch('buff_like.main', side_effect=ApiError('ENGINE unavailable')), \
             patch('buff_like.sys.frozen', True, create=True), \
             patch('buff_like.sys.argv', ['ChaySKBuffLike.exe']), \
             patch.dict('os.environ', {'LOCALAPPDATA': self.tmp.name}), \
             patch('builtins.input', return_value='') as prompt:
            run_console()
        prompt.assert_called_once()
        self.assertIn('ENGINE unavailable', (Path(self.tmp.name) / 'ChaySKBuffLike' / 'diagnostics.log').read_text())

    def test_done_below_quota_is_review_not_completion(self):
        self.bridge.state['active']['engineId'] = 'engine'
        self.bridge.request = Mock(side_effect=[{'order_id': 'engine', 'status': 'DONE', 'added_likes': 99}, {'ok': True}])
        with self.assertRaisesRegex(RuntimeError, 'review required'):
            self.bridge.tick()
        self.assertEqual(self.bridge.request.call_args.args[1]['state'], 'needs_review')
        self.assertIn('active', self.bridge.state)

    def test_report_failure_retains_exact_payload_for_restart(self):
        self.bridge.state['active']['engineId'] = 'engine'
        self.bridge.request = Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            self.bridge.report(self.bridge.state['active'], 'completed', 100, True)
        restarted = Bridge('https://example.com', 18801, self.path)
        payload = restarted.state['pendingReport'].copy()
        restarted.request = Mock(return_value={'ok': True})
        restarted.flush_report()
        restarted.request.assert_called_once_with('/api/v1/admin/buff-like/report', payload)
        self.assertNotIn('active', restarted.state)


if __name__ == '__main__':
    unittest.main()
