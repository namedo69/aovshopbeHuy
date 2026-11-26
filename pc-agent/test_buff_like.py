import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
import urllib.error
from buff_like import ApiError, run_console, receive_loop
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
            restarted.process_job(restarted.state['jobs']['order'])
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
        self.bridge.process_job(self.bridge.state['active'])
        self.assertEqual(self.bridge.request.call_args.args[1]['state'], 'needs_review')
        self.assertTrue(self.bridge.state['active']['needsReview'])

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
        self.assertNotIn('order', restarted.state['jobs'])

    def test_completion_keeps_other_job(self):
        self.bridge.state.pop('active')
        self.bridge.state['jobs'] = {'one': {'order_id': 'one'}, 'two': {'order_id': 'two'}}
        self.bridge.state['pendingReport'] = {'orderId': 'one', 'state': 'completed'}
        self.bridge.request = Mock(return_value={'ok': True})
        self.bridge.flush_report()
        self.assertEqual(list(self.bridge.state['jobs']), ['two'])

    def test_two_jobs_polled_independently(self):
        self.bridge.state.pop('active')
        self.bridge.max_jobs = 2
        self.bridge.state['jobs'] = {str(i): {'order_id': str(i)} for i in range(2)}
        self.bridge.process_job = Mock(side_effect=[RuntimeError('Ambiguous'), None])
        self.bridge.tick()
        self.assertEqual(self.bridge.process_job.call_count, 2)

    def test_closed_order_clears_pending_and_only_its_job(self):
        self.bridge.state.pop('active')
        self.bridge.state['jobs'] = {'one': {}, 'two': {}}
        self.bridge.state['pendingReport'] = {'orderId': 'one', 'state': 'running'}
        self.bridge.request = Mock(return_value={'ok': True, 'closed': True, 'orderStatus': 'refunded'})
        self.bridge.flush_report()
        self.assertNotIn('pendingReport', self.bridge.state)
        self.assertEqual(list(self.bridge.state['jobs']), ['two'])

    def test_web_deploy_retries_report_without_losing_payload(self):
        self.bridge.state.pop('active')
        payload = {'orderId': 'one', 'state': 'running'}
        self.bridge.state['pendingReport'] = payload
        self.bridge.save()
        self.bridge.request = Mock(side_effect=[ApiError('502', status=502, transient=True), {'ok': True}])
        self.bridge.tick = self.bridge.flush_report
        self.bridge.login = Mock()
        with patch('buff_like.time.sleep', side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                receive_loop(self.bridge, 'email', 'password')
        self.assertEqual(self.bridge.request.call_count, 2)
        self.assertEqual(self.bridge.request.call_args_list[0], self.bridge.request.call_args_list[1])
        self.assertNotIn('pendingReport', self.bridge.state)

    def test_expired_session_logs_in_again(self):
        bridge = Mock()
        bridge.tick.side_effect = [ApiError('expired', status=401), KeyboardInterrupt]
        with patch('buff_like.time.sleep'):
            with self.assertRaises(KeyboardInterrupt):
                receive_loop(bridge, 'email', 'password')
        self.assertEqual(bridge.login.call_count, 2)

    def test_wrong_password_does_not_retry_forever(self):
        bridge = Mock()
        bridge.login.side_effect = ApiError('wrong password', status=401)
        with patch('buff_like.time.sleep') as wait:
            with self.assertRaises(ApiError):
                receive_loop(bridge, 'email', 'password')
        wait.assert_not_called()

    def test_engine_submission_remains_uncertain_after_network_failure(self):
        active = self.bridge.state['active']
        active.pop('submissionIntent')
        self.bridge.validate_engine = Mock()
        self.bridge.request = Mock(side_effect=ApiError('engine reset', engine=True, transient=True))
        with self.assertRaises(ApiError):
            self.bridge.process_job(active)
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
            self.bridge.process_job(active)
        self.assertEqual(self.bridge.request.call_count, 1)

    def test_uncertain_web_claim_reuses_saved_token(self):
        self.bridge.state.pop('active')
        self.bridge.validate_engine = Mock()
        self.bridge.request = Mock(side_effect=ApiError('deploy', status=503, transient=True))
        with self.assertRaises(ApiError):
            self.bridge.tick()
        first_payload = self.bridge.request.call_args.args[1]
        restarted = Bridge('https://example.com', 18801, self.path)
        restarted.validate_engine = Mock()
        restarted.request = Mock(return_value={'job': None})
        restarted.tick()
        self.assertEqual(first_payload, restarted.request.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
