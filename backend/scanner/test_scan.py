import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from scan import scan


class ScanTests(unittest.TestCase):
    def run_scan(self, feeds):
        session = MagicMock()
        session.__enter__.return_value = session
        session.resolve_player_profile_1205.return_value = SimpleNamespace(target_uid=123, world_id=1)
        session.query_user_feeds_12956.return_value = SimpleNamespace(items=feeds)
        with patch('scan.LobbySession', return_value=session):
            return scan('Tên', [{'username': 'test', 'password': 'test'}])

    def test_empty_page_blocks(self):
        self.assertEqual(self.run_scan([])['status'], 'no_posts')

    def test_matching_post_allows(self):
        self.assertEqual(self.run_scan([SimpleNamespace(owner_uid=123, world_id=1)])['status'], 'found')

    def test_other_character_post_never_allows(self):
        self.assertEqual(self.run_scan([SimpleNamespace(owner_uid=456, world_id=1)])['status'], 'unavailable')

    def test_login_failure_is_not_no_posts(self):
        with patch('scan.LobbySession', side_effect=RuntimeError('login failed')) as factory:
            result = scan('Tên', [{'username': 'one', 'password': 'test'}, {'username': 'two', 'password': 'test'}])
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(factory.call_count, 2)


if __name__ == '__main__':
    unittest.main()
