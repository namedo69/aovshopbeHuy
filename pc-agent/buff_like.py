"""chaysk.com -> original AutoBuffDoHot (4) localhost API. Python stdlib only."""
import argparse
import getpass
import json
import os
import ssl
import socket
import sys
from datetime import datetime
from pathlib import Path
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid


class ApiError(RuntimeError):
    pass


def describe_network_error(error):
    reason = getattr(error, 'reason', error)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'HTTPS certificate invalid. Check Windows clock and server certificate.'
    if isinstance(reason, ssl.SSLError):
        return 'TLS connection failed. Check VPN/proxy and Windows certificates.'
    if isinstance(reason, socket.gaierror):
        return 'DNS lookup failed. Check Internet and DNS.'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'Connection timed out.'
    return 'Connection failed. Check engine API port, Internet, firewall or proxy.'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Unexpected redirect; request not replayed')


class Bridge:
    def __init__(self, backend, port, state_path):
        if urllib.parse.urlsplit(backend).scheme != 'https':
            raise ValueError('Backend requires HTTPS')
        self.backend = backend.rstrip('/')
        self.engine = f'http://127.0.0.1:{port}'
        self.path = Path(state_path)
        self.state = json.loads(self.path.read_text('utf-8')) if self.path.exists() else {'deviceId': str(uuid.uuid4())}
        self.token = ''
        self.save()
        self.remote = urllib.request.build_opener(NoRedirect())
        self.local = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stage = self.path.with_suffix('.tmp')
        with stage.open('w', encoding='utf-8') as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, self.path)

    def request(self, path, data=None, engine=False):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if not engine and self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request((self.engine if engine else self.backend) + path,
            data=None if data is None else json.dumps(data).encode(), headers=headers)
        source = 'ENGINE localhost' if engine else 'WEB backend'
        try:
            with (self.local if engine else self.remote).open(req, timeout=20) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            hint = {
                401: 'Check engine license.' if engine else 'Wrong login or expired session.',
                403: 'Access denied; check admin permissions or engine license.',
                404: 'Wrong API port/path or backend version.',
                409: 'Order conflict; inspect existing claim/engine before retrying.',
                429: 'Too many requests; wait before logging in again.',
            }.get(exc.code, 'Server returned an error.')
            status = exc.code
            exc.close()
            raise ApiError(f'{source} {path}: HTTP {status}. {hint}') from None
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(f'{source} {path}: {describe_network_error(exc)}') from None
        except (ValueError, UnicodeError):
            raise ApiError(f'{source} {path}: response is not valid JSON; check API address.') from None
        if not isinstance(result, (dict, list)) or (isinstance(result, dict) and result.get('ok') is False):
            raise RuntimeError('Invalid API response')
        return result

    def login(self, email, password):
        result = self.request('/api/v1/auth/login', {'email': email, 'password': password})
        if result.get('user', {}).get('role') != 'admin':
            raise RuntimeError('Admin account required')
        self.token = result['accessToken']

    def validate_engine(self):
        status = self.request('/api/status', engine=True)
        slots = self.request('/api/slots', engine=True)
        if status.get('tool') != 'AutoBuffDoHot_Khach' or status.get('pool_size', 0) <= 0:
            raise RuntimeError('Open licensed engine (4) and load accounts first')
        if slots.get('mode') != 'moments' or not isinstance(slots.get('orders'), list):
            raise RuntimeError('Wrong engine API')

    def report(self, active, state, done, stopped):
        payload = dict(deviceId=self.state['deviceId'], claimToken=active['claimToken'],
            orderId=active['order_id'], engineOrderId=active.get('engineId', ''),
            state=state, done=done, engineStopped=stopped)
        self.state['pendingReport'] = payload
        self.save()
        self.flush_report()

    def flush_report(self):
        payload = self.state.get('pendingReport')
        if not payload:
            return
        result = self.request('/api/v1/admin/buff-like/report', payload)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('Report not acknowledged; retaining exact payload')
        self.state.pop('pendingReport')
        if payload['state'] == 'completed':
            self.state.pop('active', None)
            self.state.pop('claimToken', None)
        self.save()

    def tick(self):
        self.flush_report()
        active = self.state.get('active')
        if not active:
            self.validate_engine()
            self.state.setdefault('claimToken', str(uuid.uuid4()))
            self.save()  # persist before any claim request
            result = self.request('/api/v1/admin/buff-like/claim', {
                'deviceId': self.state['deviceId'], 'claimToken': self.state['claimToken']})
            job = result.get('job')
            if not job:
                return
            if job['state'] != 'claimed':
                raise RuntimeError('Claim already executed; inspect journal before continuing')
            active = dict(job, claimToken=self.state['claimToken'])
            self.state['active'] = active
            self.save()
        if not active.get('engineId'):
            if active.get('submissionIntent'):
                raise RuntimeError('Ambiguous engine submission: inspect engine; do not delete journal or retry order')
            self.validate_engine()
            active['submissionIntent'] = True
            self.save()  # engine POST is deliberately never retried
            result = self.request('/api/order', {'target_name': active['target_name'], 'amount': active['requested']}, engine=True)
            if not result.get('order_id'):
                raise RuntimeError('Missing engine order ID; inspect engine')
            active['engineId'] = str(result['order_id'])
            self.save()
        result = self.request('/api/order/' + urllib.parse.quote(active['engineId'], safe=''), engine=True)
        if str(result.get('order_id')) != active['engineId']:
            raise RuntimeError('Engine order identity mismatch')
        done = result.get('added_likes')
        if not isinstance(done, int) or isinstance(done, bool) or done < active.get('done', 0):
            raise RuntimeError('Invalid engine progress')
        done = min(done, active['requested'])
        status = result.get('status')
        stopped = status in ('DONE', 'STOPPED', 'ERROR', 'FAILED')
        state = 'completed' if status == 'DONE' and done == active['requested'] else ('needs_review' if stopped else 'running')
        active['done'] = done
        self.report(active, state, done, stopped)
        print(f"{active['order_id']}: {state} {done}/{active['requested']}", flush=True)
        if state == 'needs_review':
            raise RuntimeError('Engine stopped before quota: review required; no automatic refund/restart')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', default='https://api.chaysk.com')
    parser.add_argument('--port', type=int, default=18801)
    parser.add_argument('--state', default=str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ChaySKBuffLike' / 'state.json'))
    args = parser.parse_args()
    # OS lock prevents two receivers sharing the same journal.
    lock_path = Path(args.state + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            if lock_path.stat().st_size == 0:
                lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bridge = Bridge(args.backend, args.port, args.state)
        email = input('Admin email: ').strip()
        password = getpass.getpass('Admin password: ')
        print('Connecting to WEB backend...', flush=True)
        bridge.login(email, password)
        print('WEB login OK (admin). Checking ENGINE localhost port ' + str(args.port) + '...', flush=True)
        bridge.validate_engine()
        print('Connected. Ctrl+C stops receiver, not the engine. Keep journal for recovery.')
        logged_in = time.monotonic()
        while True:
            try:
                if time.monotonic() - logged_in > 600:
                    bridge.login(email, password)
                    logged_in = time.monotonic()
                bridge.tick()
            except (urllib.error.URLError, TimeoutError):
                print('Connection interrupted; retaining journal. Retry in 5 seconds.')
            time.sleep(5)


def run_console():
    try:
        main()
    except KeyboardInterrupt:
        print('\nReceiver stopped. Engine may still be running; journal retained.')
    except Exception as error:
        # Never record request bodies, passwords, access tokens or raw network errors.
        detail = str(error) if isinstance(error, (ApiError, RuntimeError)) else (
            describe_network_error(error) if isinstance(error, OSError)
            else f'{type(error).__name__}: unable to continue; check configuration and journal.')
        print('\nERROR: ' + detail, flush=True)
        print('No automatic resubmit. Keep state.json. Check the error before reopening.', flush=True)
        log = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ChaySKBuffLike' / 'diagnostics.log'
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf-8') as stream:
                stream.write(datetime.now().isoformat(timespec='seconds') + ' ' + detail + '\n')
            print('Diagnostic log: ' + str(log))
        except OSError:
            print('Could not write diagnostic log.')
    finally:
        if getattr(sys, 'frozen', False) and '--help' not in sys.argv and '-h' not in sys.argv:
            try:
                input('\nPress Enter to close this window...')
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == '__main__':
    run_console()
