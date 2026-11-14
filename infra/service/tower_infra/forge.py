"""The forge executor (P4 F2; ARQUITETURA-ALVO §6): Origin through its CLI, the one transport its API accepts a Cursor
key on (the CLI exchanges the key for a token).

A job of the forge executor carries its input inline, as a data: URI of JSON (base64 or percent-encoded): a forge
action is a few fields, never a file. The actions:
  {"action": "land", "repo": "org/name", "pr": N, "head": "<full sha>", "method": "merge" | "squash", "dry_run": false}
      merges the pull request with the expected head (compare-and-swap: a head that moved is refused, never merged) and
      answers the merge commit; with dry_run it only checks that the head is still the expected one (the shadow of P5).
The adapter answers how the run ended, in its own vocabulary: succeeded with the merge commit, or failed with
head_moved, refused or not_understood (an input it does not understand is refused, §6); an answer whose run called the
CLI carries its usage, the seconds its calls to Origin took: forge_merge_s for a merge, forge_view_s for a dry run's
view (P6 F1 measures the merge through Origin's API from them). The Cursor key comes from the
environment (CURSOR_API_KEY) or, in the service, from the credential the caller gives (Parameter Store, read when a
landing runs, so a missing key refuses landings and never keeps the service from starting); it goes only into the
environment of the CLI's process, and no answer carries it. Standard library only.
"""
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import unquote

LOG = logging.getLogger(__name__)
SHA = re.compile(r'^[0-9a-f]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
MERGED = re.compile(r'Merge commit:\s*([0-9a-f]{40})')
MOVED = re.compile(r'expected head|head (has )?(moved|changed)|stale head|\baborted\b|\b409\b', re.I)
METHODS = {'merge': '--merge', 'squash': '--squash'}
SECRET = re.compile(r'(crsr_|oit_)[A-Za-z0-9_.-]+')
UNAUTHORIZED = re.compile(r'\b401\b|unauthori[sz]ed|token (is |has )?(expired|invalid)|expired token|invalid token', re.I)
TOKEN_MARGIN_S = 300  # a kept token is replaced this long before it expires
TOKEN_TTL_S = 600  # when the token does not say when it expires
TOKEN_RETRY_S = 60  # after a failed exchange, no new try for this long
# OBSERVE-HTTP: the API `origin api` calls (api.cursor.com/v1/origin, Bearer token), read by Python with the kept token
ORIGIN_API, HTTP_TIMEOUT_S = 'https://api.cursor.com/v1/origin', 15
# MERGE-READY (criterion 2: the landing's merge; forge_merge_s p50 1.527 s, p99 3.107 s on 512 CPU units, n=10, #704): the
# merge is one `origin pr merge` process, and the CLI (a 113 MB compiled binary) spends its start-up before its first call
# (0.21 to 0.25 s of wall on a box's vCPU, 0.365 s to the read of its body under strace; the service has half a vCPU). The
# CLI reads --body-file before any call (resolve the target, the base warning, getRepo, mergeStack: one after the other),
# so the merge of the train's front is started ahead, at its join (4.1 to 4.4 s before its landing's run, 13/11 23:57 to
# 00:35 UTC), with its body file a FIFO in a directory of its own: the CLI waits in open() until a writer comes, and the
# landing, once its check is posted, writes the PR's description (the body the forge composes when none is given: the same
# bytes, #714) and the merge goes on. A FIFO, not stdin: nobody writes to it unless the landing does, so a service that
# dies never gives the CLI an end of file it would merge with. READY_MAX_S below the token's TOKEN_MARGIN_S: the CLI's
# kept token is fresh when it is released
READY_MAX_S, READY_OPEN_S = 240.0, 5.0
# MERGE-READY-ORPHAN: a merge started ahead by a process that then ends (a swap retires it right after it readied the next
# front) would wait in open() for good: 70 MB each in the service's 1 GB. Each is started under `timeout -s KILL`, in a
# session of its own (stopped whole, its group killed), and is gone READY_LIFE_S after it began: the oldest one released
# (READY_MAX_S) ends its merge (TOWER_FORGE_TIMEOUT_S, 60) before that
READY_LIFE_S = 360


def decode(uri):
    """The JSON of a data: URI, or None for any other input."""
    if not isinstance(uri, str) or not uri.startswith('data:') or ',' not in uri:
        return None
    meta, data = uri[len('data:'):].split(',', 1)
    try:
        raw = base64.b64decode(data) if meta.endswith(';base64') else unquote(data).encode('utf-8')
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def encode(action):
    """The data: URI of an action, as a job's input_uri."""
    return 'data:application/json;base64,' + base64.b64encode(json.dumps(action, sort_keys=True).encode()).decode()


def failed(error, detail=''):
    return {'outcome': 'failed', 'error': error, 'result': {'detail': SECRET.sub('<redacted>', detail)[-500:]}}


def stop(process):
    """MERGE-READY-ORPHAN: a merge started ahead killed with its session (`timeout` and the CLI under it)."""
    import signal
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


class NoKey(Exception):
    pass


class OriginForge:
    def __init__(self, cli=None, run=subprocess.run, environ=None, credential=None, clock=time.monotonic, post_check=None,
                 opener=None, spawn=subprocess.Popen):
        self.cli = cli or os.environ.get('TOWER_ORIGIN_CLI', 'origin')
        self.opener = opener  # OBSERVE-HTTP: urllib's urlopen in the live service (its reads over HTTP); None: the CLI
        self.via = None  # OBSERVE-HTTP: how the last api_get read: 'http' or 'cli'
        self.post_check = post_check  # CHECK-IN-LANDING: checks.Poster.post, the Origin app's tower/gate before the merge
        self.call = run
        self.environ = environ
        self.credential = credential
        self.clock = clock
        self.token, self.expires, self.retry_at = None, 0.0, 0.0
        self.auth = None
        self.spawn = spawn  # MERGE-READY: the merge started ahead
        self.kept, self.landing, self.lock = None, None, threading.Lock()  # kept: {key, process, fifo, body, at}

    def exchange(self, environ):
        """The key exchanged for a short-lived token by the CLI itself (`origin auth token`, ~0.5 s a call), kept in
        memory with its expiry (the JWT's exp claim) so a landing's own call skips the exchange (AWS9). Never raises;
        the token goes only into the environment of the CLI's process, like the key, and nothing logs it."""
        try:
            done = self.call([self.cli, 'auth', 'token'], capture_output=True, text=True, check=False, timeout=20,
                             env={name: value for name, value in environ.items() if name != 'CURSOR_AUTH_TOKEN'})
            token = (done.stdout or '').strip()
            if done.returncode != 0 or not token or '\n' in token or ' ' in token:
                raise ValueError('no token')
            self.token, self.expires = token, time.time() + TOKEN_TTL_S
            try:
                claims = token.split('.')[1]
                exp = json.loads(base64.urlsafe_b64decode(claims + '=' * (-len(claims) % 4))).get('exp')
                if isinstance(exp, (int, float)):
                    self.expires = float(exp)
            except (IndexError, ValueError):
                pass
        except Exception as error:  # noqa: BLE001 - the key still works, a call just pays the exchange
            self.token, self.retry_at = None, time.time() + TOKEN_RETRY_S
            LOG.warning('forge: no token from the exchange (%s); landings pay it until the next try', type(error).__name__)

    def fresh(self):
        return bool(self.token) and time.time() < self.expires - TOKEN_MARGIN_S

    def env(self, keyed=False):
        """The CLI's environment: the kept token when there is a fresh one (the key stays out of the process), else the
        key; keyed=True forces the key (the retry after the CLI refused the token)."""
        environ = dict(os.environ if self.environ is None else self.environ)
        if not environ.get('CURSOR_API_KEY') and not environ.get('CURSOR_AUTH_TOKEN') and not environ.get('CURSOR_AUTH_TOKEN'):
            key = self.credential() if self.credential else None
            if not key:
                raise NoKey()
            environ['CURSOR_API_KEY'] = key
        if environ.get('CURSOR_API_KEY') and not environ.get('CURSOR_AUTH_TOKEN') and not keyed and self.fresh():
            environ['CURSOR_AUTH_TOKEN'] = self.token
            del environ['CURSOR_API_KEY']
        return environ

    def warm(self):
        """Read the credential now, off the path of a landing (AWS6): the service calls it between ticks, so a landing
        finds the key kept and pays no Parameter Store round trip. Never raises; a missing key is the landing's to refuse."""
        try:
            environ = self.env(keyed=True)
            if (environ.get('CURSOR_API_KEY') and not environ.get('CURSOR_AUTH_TOKEN') and not self.fresh()
                    and time.time() >= self.retry_at):
                self.exchange(environ)  # AWS9: once an hour between ticks, never in a landing's seconds
        except Exception:  # noqa: BLE001 - only a warm-up
            pass

    def origin(self, *args, spent=None, env=None):
        started = self.clock()
        try:
            for attempt in (0, 1):
                done = self.call([self.cli, *args], capture_output=True, text=True, check=False,
                                 timeout=float(os.environ.get('TOWER_FORGE_TIMEOUT_S', '60')),
                                 env=self.env() if env is None else env)
                said = (done.stdout or '') + (done.stderr or '')
                # AWS10: which credential this call carried, so a landing's usage says whether the kept token was used
                self.auth = 'token' if (env or {}).get('CURSOR_AUTH_TOKEN') else 'key'
                kept = (env or {}).get('CURSOR_AUTH_TOKEN') == self.token and self.token
                if attempt or done.returncode == 0 or not kept or not UNAUTHORIZED.search(said):
                    break
                # the CLI refused the kept token before it did anything (the expected-head compare-and-swap is
                # untouched): forget it and make the same call once with the key
                self.token, self.expires = None, 0.0
                env = self.env(keyed=True)
        finally:
            if spent is not None:
                spent.append(self.clock() - started)
        return done.returncode, said

    def http_get(self, path):
        """OBSERVE-HTTP (criterion 3): a fresh PR observation was 10.3 to 11.0 s (#692 and #694 read again, 13/11 21:50
        UTC; #690 and #692 behind the base paid it at the gate, 11.6 and 10.1 s): five `origin api` processes, a Node CLI
        each, on the service's quarter of a vCPU. The same GET of api.cursor.com/v1/origin with the kept token (the key's
        exchange, AWS9) by Python: its JSON object; None when there is no fresh token or the API refused it (the CLI reads
        it then, as before: a 401 drops the token); RuntimeError for any other refusal, as the CLI's. The token is the one
        warm() exchanges between ticks: no exchange is paid here."""
        import urllib.error
        import urllib.request
        if self.opener is None or not self.fresh():  # the live service's forge has the opener; warm() keeps the token
            return None
        url = ORIGIN_API + (path if path.startswith('/') else '/' + path)
        request = urllib.request.Request(url, method='GET', headers={
            'authorization': f'Bearer {self.token}', 'accept': 'application/json', 'user-agent': 'tower-service'})
        try:
            with self.opener(request, timeout=HTTP_TIMEOUT_S) as answer:
                said = json.loads(answer.read() or b'{}')
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.token, self.expires = None, 0.0
                return None
            raise RuntimeError(f'origin api {path.split("?")[0]} failed: HTTP {error.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            LOG.warning('forge: the API was not read over HTTP (%s); the CLI reads it', type(error).__name__)
            return None
        if not isinstance(said, dict):
            raise RuntimeError(f'origin api {path.split("?")[0]}: not a JSON object')
        return said

    def api_get(self, path):
        """PR-OBSERVATION: one GET of the API with the forge's credential: OBSERVE-HTTP first, else `origin api <path>` (a
        kept token refused: once more with the key, as origin() does); its JSON object, or RuntimeError with the CLI's
        last line, redacted."""
        said = self.http_get(path)
        if said is not None:
            self.via = 'http'
            return said
        self.via = 'cli'
        for keyed in (False, True):
            env = self.env(keyed=keyed)
            done = self.call([self.cli, 'api', path, '-X', 'GET'], capture_output=True, text=True, check=False,
                             timeout=float(os.environ.get('TOWER_FORGE_TIMEOUT_S', '60')), env=env)
            if done.returncode == 0:
                said = json.loads(done.stdout or '{}')
                if not isinstance(said, dict):
                    raise RuntimeError(f'origin api {path.split("?")[0]}: not a JSON object')
                return said
            refused = (done.stderr or '') + (done.stdout or '')
            if keyed or not env.get('CURSOR_AUTH_TOKEN') or not UNAUTHORIZED.search(refused):
                break
            self.token, self.expires = None, 0.0
        last = (refused.strip().splitlines() or ['no word'])[-1]
        raise RuntimeError(SECRET.sub('<redacted>', f'origin api {path.split("?")[0]} failed: {last}')[:300])

    def start(self, run):
        """How the run ended; with its usage when it called Origin. Each run counts its own calls."""
        spent = []
        answer = self.land(run, spent)
        if spent:
            meter = 'forge_view_s' if (decode(run.get('input_uri')) or {}).get('dry_run') else 'forge_merge_s'
            answer = dict(answer, usage={meter: round(sum(spent), 3)})
            if isinstance(answer.get('result'), dict) and self.auth:
                answer['result'] = dict(answer['result'], auth=self.auth)  # 'token' (kept, no exchange) or 'key'
        return answer

    def ready(self, repo, pr, head, method='merge'):
        """MERGE-READY: the merge of (repo, pr, head) started ahead, waiting for its body; True when one is kept for it.
        Only with the kept token (the CLI makes no call before its body then) and the description read over HTTP; the one
        kept for another merge is stopped (one at a time), as is one older than READY_MAX_S."""
        key = (str(repo), str(pr), str(head), method)
        with self.lock:
            kept = self.kept
            if kept and kept['key'] == key and kept['process'].poll() is None and self.clock() - kept['at'] < READY_MAX_S:
                return True
            if self.landing == key:  # its landing runs: nothing is started for it
                return False
            self.drop()
        if not (REPO.match(key[0]) and key[1].isdigit() and SHA.match(key[2]) and method in METHODS):
            return False
        try:
            said = self.http_get(f'/repos/{repo}/pulls/{pr}')
            environ = self.env() if said is not None else None
        except (RuntimeError, NoKey):
            return False
        if (not said or said.get('state') != 'open' or (said.get('head') or {}).get('sha') != head
                or not isinstance(said.get('body'), str) or not (environ or {}).get('CURSOR_AUTH_TOKEN')):
            return False
        where = tempfile.mkdtemp(prefix='tower-merge-')
        fifo = os.path.join(where, 'body')
        os.mkfifo(fifo, 0o600)
        process = self.spawn(['timeout', '-s', 'KILL', str(READY_LIFE_S), self.cli, 'pr', 'merge', key[1], '-R', key[0],
                              '--expect-head', f'{key[1]}={head}', METHODS[method], '-F', fifo],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=environ, start_new_session=True)
        with self.lock:
            self.drop()
            if self.landing == key:  # its landing began meanwhile and runs its own merge
                self.kept = {'key': key, 'process': process, 'fifo': fifo, 'body': '', 'at': self.clock()}
                self.drop()
                return False
            self.kept = {'key': key, 'process': process, 'fifo': fifo, 'body': said['body'], 'at': self.clock()}
        LOG.info('forge: the merge of #%s at %s started ahead', pr, head[:12])
        return True

    def drop(self, key=None):
        """MERGE-READY: the kept merge stopped (killed before anything wrote its body: it never called the forge) and its
        FIFO removed; with key, only when it is not that one's. The caller holds the lock."""
        kept = self.kept
        if not kept or (key is not None and kept['key'] == key):
            return
        self.kept = None
        try:
            stop(kept['process'])
            kept['process'].communicate(timeout=5)
        except Exception:  # noqa: BLE001 - it was never released
            pass
        import shutil
        shutil.rmtree(os.path.dirname(kept['fifo']), ignore_errors=True)

    def released(self, key, spent):
        """MERGE-READY: (code, output, ready_s) of the merge kept for key, its body written now; None when none is kept
        for it, or it is not waiting in its FIFO's open (it is stopped then, and the landing merges as before)."""
        with self.lock:
            kept = self.kept if self.kept and self.kept['key'] == key else None
            if kept is None:
                return None
            self.kept = None
        process, began = kept['process'], self.clock()
        import errno
        import fcntl
        import shutil
        try:
            while True:  # the writer's end opens only while the CLI waits in the reader's open (ENXIO before)
                try:
                    handle = os.open(kept['fifo'], os.O_WRONLY | os.O_NONBLOCK)
                    break
                except OSError as error:
                    if error.errno != errno.ENXIO or process.poll() is not None or self.clock() - began > READY_OPEN_S:
                        with self.lock:
                            self.kept = kept
                            self.drop()
                        return None
                    time.sleep(0.01)
            fcntl.fcntl(handle, fcntl.F_SETFL, fcntl.fcntl(handle, fcntl.F_GETFL) & ~os.O_NONBLOCK)
            with os.fdopen(handle, 'w', encoding='utf-8') as body:
                body.write(kept['body'])
            try:
                out, err = process.communicate(timeout=float(os.environ.get('TOWER_FORGE_TIMEOUT_S', '60')))
            except subprocess.TimeoutExpired:
                stop(process)
                process.communicate()
                raise
        finally:
            spent.append(self.clock() - began)
            shutil.rmtree(os.path.dirname(kept['fifo']), ignore_errors=True)
        return process.returncode, (out or '') + (err or ''), round(began - kept['at'], 3)

    def land(self, run, spent):
        action = decode(run.get('input_uri'))
        if not action or action.get('action') != 'land':
            return failed('not_understood', 'the forge understands {"action": "land"} in a data: URI')
        repo, pr, head = action.get('repo'), action.get('pr'), action.get('head')
        method = action.get('method', 'merge')
        if not (REPO.match(str(repo)) and str(pr).isdigit() and SHA.match(str(head)) and method in METHODS):
            return failed('not_understood', 'land needs repo, pr, a full head sha and merge or squash')
        try:
            env = self.env()  # once per landing: the call below reuses it, not a second read of the credential
        except NoKey:
            return failed('refused', 'the forge has no Cursor key (/tower/origin/forge-key)')
        if action.get('dry_run'):
            return self.would_land(repo, str(pr), head, spent, env)
        check, posted = action.get('check_run'), {}
        if check is not None:  # CHECK-IN-LANDING: the gate's tower/gate success, posted here, the merge right after it
            refused = self.check(check, head, posted)
            if refused:
                return refused
        key = (str(repo), str(pr), str(head), method)
        with self.lock:
            self.landing = key
            self.drop(key)  # MERGE-READY: one kept for another merge is not this landing's
        try:
            ready = self.released(key, spent)  # MERGE-READY: the merge started ahead, released by its body
            if ready is not None and ready[0] != 0 and UNAUTHORIZED.search(ready[1]):
                self.token, self.expires = None, 0.0  # its kept token refused before any call: merged as before, keyed
                ready = None
                env = self.env(keyed=True)
            if ready is None:
                code, said = self.origin('pr', 'merge', str(pr), '-R', repo, '--expect-head', f'{pr}={head}',
                                         METHODS[method], spent=spent, env=env)
            else:
                code, said = ready[:2]
                posted['ready_s'] = ready[2]  # how long the merge waited, started, for its landing
                self.auth = 'token'
        finally:
            with self.lock:
                self.landing = None
        merged = MERGED.search(said)
        if code == 0 and merged:
            return {'outcome': 'succeeded', 'result': {'merge_sha': merged.group(1), 'repo': repo, 'pr': int(pr),
                                                       'head': head, 'method': method, 'ready': ready is not None,
                                                       **posted}}
        return failed('head_moved' if MOVED.search(said) else 'refused', said)

    def check(self, check, head, posted):
        """CHECK-IN-LANDING (criterion 3 of F4: the delivery's gate, p99 10 s): the forge requires tower/gate on the
        head it merges (the ruleset tower-gate-required, F37), and the gate's client published the success itself, before
        it made this landing: a POST to the port, the live service woken to post it to Origin, and the client's poll of
        0.5 s for its word, 1.0 to 2.4 s of each delivery's 13/11 gates (before_s less the train's front). The landing
        carries the success's body and posts it here, with the same app key (checks.Poster), right before the merge:
        the order the forge asks for, one process. Only for the head it merges; a failed post is a landing refused, and
        nothing merges (the forge would refuse it the same). None when posted, else the refusal."""
        if not isinstance(check, dict) or check.get('headSha') != head or not isinstance(check.get('checkRun'), dict):
            return failed('not_understood', 'check_run must be a check run body on the head that lands')
        if self.post_check is None:
            return failed('refused', 'tower/gate: the forge has no Origin app key to post the check run with')
        began = self.clock()
        try:
            answer = self.post_check(check) or {}
        except Exception as error:  # noqa: BLE001 - said in the landing's result; nothing merges
            return failed('refused', SECRET.sub('<redacted>', f'tower/gate not posted: {type(error).__name__}: {error}')[:300])
        if answer.get('outcome') == 'ignored_stale':
            return failed('refused', 'tower/gate: the forge ignored the check run as stale')
        posted.update(check_posted=check['checkRun'].get('conclusion') or check['checkRun'].get('status'),
                      check_post_s=round(self.clock() - began, 3))
        return None

    def would_land(self, repo, pr, head, spent=None, env=None):
        code, said = self.origin('pr', 'view', pr, '-R', repo, '--json', 'status,latestVersion', spent=spent, env=env)
        try:
            view = json.loads(said) if code == 0 else None
        except ValueError:
            view = None
        if not view:
            return failed('refused', said)
        now = (view.get('latestVersion') or {}).get('headSha')
        if now != head:
            return failed('head_moved', f'the head is {now}, not {head}')
        if view.get('status') == 'merged':  # merged already (in shadow, by the box first): nothing to retry
            return failed('merged', 'the pull request is merged')
        if view.get('status') not in ('open', 'draft'):
            return failed('refused', f"the pull request is {view.get('status')}")
        return {'outcome': 'succeeded', 'result': {'would_merge': True, 'repo': repo, 'pr': int(pr), 'head': head}}
