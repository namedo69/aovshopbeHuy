"""Read-only post lookup using the existing native project's lobby protocol."""
import json
import os
import sys

from backend_native.lobby_session import LobbySession


def scan(name, accounts):
    for account in accounts:
        try:
            with LobbySession(account['username'], account['password']) as session:
                session.authenticate()
                session.connect_lobby()
                profile = session.resolve_player_profile_1205(name, timeout=12)
                if not 0 < profile.target_uid < 2**64:
                    raise ValueError('Invalid target')
                page = session.query_user_feeds_12956(profile.target_uid, profile.world_id, 0, 15, timeout=12)
                if any(f.owner_uid != profile.target_uid or f.world_id != profile.world_id for f in page.items):
                    raise ValueError('Feed identity mismatch')
                return {'status': 'found' if page.items else 'no_posts', 'targetUid': str(profile.target_uid), 'postCount': len(page.items)}
        except Exception:
            # Try the second dedicated source; never expose credentials or protocol payloads.
            continue
    return {'status': 'unavailable'}


if __name__ == '__main__':
    try:
        name = json.loads(sys.stdin.readline())['targetName']
        accounts = json.loads(os.environ['BUFF_SCAN_ACCOUNTS'])
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or not accounts:
            raise ValueError('Invalid configuration')
        result = scan(name.strip(), accounts)
    except Exception:
        result = {'status': 'unavailable'}
    print(json.dumps(result), flush=True)
