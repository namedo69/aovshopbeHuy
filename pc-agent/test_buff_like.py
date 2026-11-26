import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
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
