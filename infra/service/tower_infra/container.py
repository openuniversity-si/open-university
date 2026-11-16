"""The container executor's process (P4 F1): `python -m tower_infra run-container` is the warm runner (runner.py) with
the image's fetch, prepare and upload.

fetch    one checkout per repository, kept between runs under the workdir (the warm part): a clone the first time, then
         a fetch of the job's ref (and of the commit itself, or of the job's base, when the ref does not reach it) only for a
         commit the checkout lacks, taken first from a sibling slot's checkout on the disk (AWS8), a
         forced checkout of the commit and a clean that keeps only the toolchain's link. git reaches the forge through the origin CLI, which
         exchanges the forge's key for a token on each call; the key goes only into git's environment, read when a fetch
         runs, so a missing key fails that run and never keeps the runner from starting.
prepare  links the checkout's .toolchain to a cache keyed by the toolchain's two manifests, then runs
         scripts/cloud/setup.sh, the same setup as every session's, which installs what the cache lacks and starts the
         test database (idempotent: seconds when the cache is warm, minutes the first time). A task runs it once for the
         same inputs (INFRA-EXE 1c): what setup runs and reads at the commit, as git's own hashes (SETUP_READS), so the
         checks of one head pay one setup, not one each (04/11, 376 runs: 3.5 s of wall time each for 0.7 s of CPU,
         about 1.7 s of it this setup). A failed setup is never kept; the next run sets up again.
upload   puts the log in the outputs bucket under runs/<job>/<run>.log and answers its s3:// URI; with no bucket
         (a local run) the log stays under the workdir's logs.

Every interval and name is a value of the environment with a default (D-308). The database connection is made again
after one breaks (Reconnecting). boto3 and psycopg are the image's, taken when first used. cold_start answers, from the
ECS task metadata, the seconds since the task's image pull started (P6 F1: a cold task's start).
"""
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.request

from .forge import SECRET

LOG = logging.getLogger('tower_infra.container')
KEEP = '.toolchain'
MANIFESTS = ('scripts/cloud/toolchain.json', 'config/registry/toolchain.json')
SETUP = ('bash', 'scripts/cloud/setup.sh')
# What setup.sh runs and reads: its scripts, the registry it reads its settings and pins from, the libraries it runs
# (config, origin_remote, merge_regenerate) and the attributes the merge driver installs for. SETUP-PER-HEAD: the
# libraries by name, with what they import of scripts/lib, not the whole of it: a head that changed any library of
# scripts/lib (most do) set up again in every slot on its first run there (prepare_s 1.2 to 12.8 s in #634 and #635)
SETUP_LIBRARIES = tuple(f'scripts/lib/{name}.py' for name in (
    'config', 'json_schema', 'session_identity', 'toolchain_manifest', 'origin_remote', 'merge_regenerate', 'generate',
    'units'))
SETUP_READS = ('scripts/cloud', *SETUP_LIBRARIES, 'config/registry', '.gitattributes')
PREPARED = 'tower-prepared'  # SETUP-PER-HEAD: in the checkout's .git, what setup inputs this task set up last
NAME_CHARS = 16  # of a sha256 in hex: one directory per repository and per toolchain
DETAIL_CHARS = 500


# GIT-TOKEN-AUTH (criterion 3): the delivery's merge fetched in 8.6 to 9.5 s and pushed in 8.2 to 9.4 s (#695, #696, 13/11
# 22:12 to 22:15 UTC): every request git authenticates ran the credential helper, two `origin` processes (auth token,
# credential-helper), on the service's quarter of a vCPU. A container made with token_auth mints the token once (the
# same `origin auth token`, kept until TOKEN_MARGIN_S before its exp) and gives it to git as the forge's Basic header, in
# git's environment (GIT_CONFIG_*), never on its command line (a check user may read argv, never root's environment); the
# helper stays behind it: no token, or a refused one, and git asks the helper as before
TOKEN_MARGIN_S, TOKEN_TTL_S, TOKEN_RETRY_S = 300, 600, 60
AUTH_REFUSED = re.compile(r'Authentication failed|\b401\b|could not read Username', re.I)

ENVIRONMENTAL = ('download failed',)  # what setup says (scripts/cloud/toolchain.py) when the network, not the code, failed


class Unprepared(Exception):
    """A checkout the runner could not fetch or prepare: the run fails as not_started, named. With retryable (a toolchain
    download that failed, which says nothing of the code) the runner ends the run as lost instead, a few times: the job
    goes back to its queue without a verdict (runner.Runner.lost_limit)."""
    retryable = False


def helper(cli):
    """git's credential helper: the origin CLI mints a token from the key in the environment on each call."""
    quoted = shlex.quote(cli)
    return f'!f() {{ CURSOR_AUTH_TOKEN="$({quoted} auth token 2>/dev/null)" exec {quoted} credential-helper "$@"; }}; f'


def digest(text):
    return hashlib.sha256(text.encode('utf-8') if isinstance(text, str) else text).hexdigest()[:NAME_CHARS]


class Container:
    def __init__(self, workdir, credential=None, forge_url=None, bucket=None, cli=None, run=subprocess.run,
                 environ=None, s3=None, slot=0, token_auth=False):
        self.workdir, self.slot = Path(workdir), slot  # a slot of the task (INFRA-EXE 1e): its own checkout
        self.token_auth, self.token, self.expires, self.retry_at = token_auth, None, 0.0, 0.0  # GIT-TOKEN-AUTH
        self.credential, self.bucket, self.call, self.s3 = credential, bucket, run, s3
        self.environ = dict(os.environ if environ is None else environ)
        self.forge_url = (forge_url or self.environ.get('TOWER_FORGE_URL', 'https://origin.cursor.com')).rstrip('/')
        self.prepared = None  # the inputs of the last setup that succeeded in this task (INFRA-EXE 1c)
        self.cli = cli or self.environ.get('TOWER_ORIGIN_CLI', 'origin')

    def seconds(self, name, default):
        return float(self.environ.get(name, default))

    def checkout_of(self, spec):
        """Where the runner keeps the repository's checkout: a name from its hash, so no input names a path; one per
        slot, since two slots check out two commits at once (the toolchain's cache stays shared, by its manifests)."""
        name = digest(spec['repo'])
        return self.workdir / 'checkouts' / (name if not self.slot else f'{name}-{self.slot}')

    def minted(self, env):
        """GIT-TOKEN-AUTH: the forge's token for git, minted from the key once and kept (None: the helper answers)."""
        now = time.time()
        if self.token and now < self.expires - TOKEN_MARGIN_S:
            return self.token
        if now < self.retry_at or not env.get('CURSOR_API_KEY'):
            return None
        try:
            done = self.call([self.cli, 'auth', 'token'], capture_output=True, text=True, check=False, timeout=20,
                             env={name: value for name, value in env.items() if name != 'CURSOR_AUTH_TOKEN'})
            token = (done.stdout or '').strip()
            if done.returncode != 0 or not token or any(each.isspace() for each in token):
                raise ValueError('no token')
        except Exception as error:  # noqa: BLE001 - the helper answers git as before
            self.token, self.retry_at = None, now + TOKEN_RETRY_S
            LOG.warning('container: no token for git (%s); the credential helper answers it', type(error).__name__)
            return None
        self.token, self.expires = token, now + TOKEN_TTL_S
        try:
            import base64
            claims = token.split('.')[1]
            exp = json.loads(base64.urlsafe_b64decode(claims + '=' * (-len(claims) % 4))).get('exp')
            if isinstance(exp, (int, float)):
                self.expires = float(exp)
        except (IndexError, ValueError):
            pass
        return token

    def git(self, *args, cwd=None, env=None):
        asked = env
        env = dict(self.environ, GIT_TERMINAL_PROMPT='0', **(env or {}))  # PREMERGE: a call's own (a merge's fixed dates)
        if not env.get('CURSOR_API_KEY') and not env.get('CURSOR_AUTH_TOKEN'):
            key = self.credential() if self.credential else None
            if key:
                env['CURSOR_API_KEY'] = key
        token = self.minted(env) if self.token_auth else None
        if token:
            import base64
            count = int(env.get('GIT_CONFIG_COUNT') or 0)
            basic = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
            env.update({'GIT_CONFIG_COUNT': str(count + 1), f'GIT_CONFIG_KEY_{count}': f'http.{self.forge_url}/.extraHeader',
                        f'GIT_CONFIG_VALUE_{count}': f'Authorization: Basic {basic}'})
        done = self.call(['git', '-c', 'credential.helper=', '-c', f'credential.helper={helper(self.cli)}',
                          '-c', 'advice.detachedHead=false', *args], cwd=cwd, env=env, capture_output=True, text=True,
                         timeout=self.seconds('TOWER_GIT_TIMEOUT_S', 300), check=False)
        if done.returncode and token and AUTH_REFUSED.search((done.stderr or '') + (done.stdout or '')):
            # a refused token: forgotten, no new one for TOKEN_RETRY_S, and the helper answers this call
            self.token, self.expires, self.retry_at = None, 0.0, time.time() + TOKEN_RETRY_S
            return self.git(*args, cwd=cwd, env=asked)
        if done.returncode:
            said = SECRET.sub('<redacted>', (done.stderr or '') + (done.stdout or ''))
            raise Unprepared(f'git {args[0]}: {said.strip()[-DETAIL_CHARS:]}')
        return done.stdout

    def has(self, checkout, commit):
        found = self.call(['git', 'cat-file', '-e', f'{commit}^{{commit}}'], cwd=checkout, capture_output=True,
                          check=False)
        return found.returncode == 0

    def from_sibling(self, checkout, commit):
        """Fetch `commit` from another slot's checkout of the same repository, on the same disk (AWS8: the checks of one
        head reach the forge once per task, not once per slot); whether it is here now. A sibling that cannot say
        or serve it is skipped: the forge is the answer then."""
        for each in sorted(checkout.parent.glob(checkout.name.split('-')[0] + '*')):
            if each == checkout or not (each / '.git').is_dir() or not self.has(each, commit):
                continue
            try:
                self.git('fetch', '--quiet', '--no-tags', str(each), commit, cwd=checkout)
            except Unprepared:
                continue
            if self.has(checkout, commit):
                return True
        return False

    def lean_on_pushed(self, checkout):
        """PUSHED-ALTERNATES: this checkout reads the pushed clone's objects in place (objects/info/alternates), so a head
        pushed before its gate is here with nothing copied: a first run's `git fetch` from a sibling took 4.3 to 4.9 s in
        #640 and #641, the slow parts starting together. Only that clone, which never collects garbage (keep_pushed), is
        leaned on. Whether this checkout leans on it."""
        pushed = checkout.parent / f"{checkout.name.split('-')[0]}-{PUSHED_SLOT}"
        if pushed == checkout or not (pushed / '.git' / 'objects').is_dir():
            return False
        listing = checkout / '.git' / 'objects' / 'info' / 'alternates'
        objects = str((pushed / '.git' / 'objects').resolve())
        try:
            known = listing.read_text().split() if listing.exists() else []
            if objects not in known:
                listing.parent.mkdir(parents=True, exist_ok=True)
                listing.write_text(''.join(f'{each}\n' for each in [*known, objects]))
            return True
        except OSError:
            return False

    def clone_sibling(self, checkout):
        """PREWARM-LOCAL-CLONE: the checkout cloned from a sibling slot's, on the same disk; whether it was. Its origin is
        set to the forge right after (fetch), so nothing of the sibling's path stays."""
        for each in sorted(checkout.parent.glob(checkout.name.split('-')[0] + '*')):
            if each == checkout or not (each / '.git').is_dir():
                continue
            try:
                self.git('clone', '--quiet', '--no-checkout', '--local', str(each), str(checkout))
                return True
            except Unprepared:
                shutil.rmtree(checkout, ignore_errors=True)
        return False

    def fetch(self, spec, checkout):
        url = f"{self.forge_url}/{spec['repo']}.git"
        if not (checkout / '.git').is_dir():
            shutil.rmtree(checkout, ignore_errors=True)
            checkout.parent.mkdir(parents=True, exist_ok=True)
            # PREWARM-LOCAL-CLONE: a slot whose sibling already holds a clone of the repository copies it on the disk
            # (hard links), not over the network: a new runner task cloned it from the forge once per slot, four in a
            # row before it was healthy (its warm-up 68 to 75 s, on the slow path's rollout, 12 and 13/11)
            how = 'sibling'  # HEAD-ON-PUSH: where the head came from (the clone, when it brought it)
            if not self.clone_sibling(checkout):
                self.git('clone', '--quiet', '--no-checkout', url, str(checkout))
                how = 'forge'
        else:
            how = 'here'
        self.git('remote', 'set-url', 'origin', url, cwd=checkout)
        wanted = [commit for commit in (spec['commit'], spec.get('base')) if commit]  # the base too, for base...head
        missing = [commit for commit in wanted if not self.has(checkout, commit)]
        if spec['commit'] in missing:
            how = 'sibling'
        if missing and self.lean_on_pushed(checkout):  # PUSHED-ALTERNATES: the pushed clone's objects, read in place
            still = [commit for commit in missing if not self.has(checkout, commit)]
            if spec['commit'] in missing and spec['commit'] not in still:
                how = 'pushed'
            missing = still
        for commit in list(missing):  # AWS8: a sibling slot's checkout may hold it already: no network, no token
            if self.from_sibling(checkout, commit):
                missing.remove(commit)
        if spec['commit'] in missing:
            how = 'forge'
        if spec['commit'] in missing and spec.get('ref'):  # AWS8: a commit already here needs no round trip to the forge
            self.git('fetch', '--quiet', '--no-tags', 'origin', spec['ref'], cwd=checkout)
        for commit in missing:
            if not self.has(checkout, commit):
                self.git('fetch', '--quiet', '--no-tags', 'origin', commit, cwd=checkout)
        self.git('checkout', '--quiet', '--force', '--detach', spec['commit'], cwd=checkout)
        self.git('clean', '-ffdxq', '-e', KEEP, cwd=checkout)
        return how

    def keep_pushed(self, repo, ref, commit):
        """HEAD-ON-PUSH: `commit`, pushed to `ref`, fetched into this box's clone (one with no work tree, which no run
        checks out), so the slots take it from it on the disk; whether the forge was reached for it."""
        clone = self.checkout_of({'repo': repo})
        if (clone / '.git').is_dir() and self.has(clone, commit):
            return False
        url = f"{self.forge_url}/{repo}.git"
        if not (clone / '.git').is_dir():
            shutil.rmtree(clone, ignore_errors=True)
            clone.parent.mkdir(parents=True, exist_ok=True)
            if not self.clone_sibling(clone):
                self.git('clone', '--quiet', '--no-checkout', url, str(clone))
        self.git('remote', 'set-url', 'origin', url, cwd=clone)
        # PUSHED-ALTERNATES: the slots read these objects in place: nothing here is ever collected
        self.git('config', 'gc.auto', '0', cwd=clone)
        self.git('config', 'gc.pruneExpire', 'never', cwd=clone)
        # PUSHED-PACK: and they read them while a push is being fetched here. A fetch of fewer than 100 objects was
        # unpacked one loose object at a time, the commit before its tree, so a slot that leaned on this clone at that
        # instant saw the head and could not check it out ("unable to read tree": #654's bundle job, 13/11 13:26 UTC,
        # and its landing went the slow way). Kept as one pack, whose index is written last, a fetch appears whole or
        # not at all
        self.git('config', 'fetch.unpackLimit', '1', cwd=clone)
        if self.has(clone, commit):
            return False
        self.git('fetch', '--quiet', '--no-tags', 'origin', ref, cwd=clone)
        if not self.has(clone, commit):  # the ref moved again: the commit by itself
            self.git('fetch', '--quiet', '--no-tags', 'origin', commit, cwd=clone)
        return True

    def head_of(self, repo, ref):
        """The commit the forge's `ref` points at now (git ls-remote), for the warm-up; Unprepared when it cannot say."""
        said = self.git('ls-remote', f'{self.forge_url}/{repo}.git', ref).split()
        if not said or not re.fullmatch(r'[0-9a-f]{40}', said[0]):
            raise Unprepared(f'ls-remote: the forge has no {ref}')
        return said[0]

    def toolchain_of(self, checkout):
        manifests = b''.join((checkout / name).read_bytes() if (checkout / name).exists() else b''
                             for name in MANIFESTS)
        return self.workdir / 'toolchains' / digest(manifests)

    def prepare(self, checkout):
        cache, link = self.toolchain_of(checkout), checkout / KEEP
        cache.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and Path(os.readlink(link)) != cache:
            link.unlink()
        elif link.exists() and not link.is_symlink():
            shutil.rmtree(link)
        if not link.is_symlink():
            link.symlink_to(cache, target_is_directory=True)
        inputs = self.setup_inputs(checkout)
        if inputs is not None and inputs == self.prepared:
            return  # this task ran this same setup: its toolchain is installed and its test database is up
        # SETUP-PER-HEAD: a process that took the role in this task (a landing's swap) finds what the one before it set
        # up here: the disk, the toolchain and the test database are the task's, not the process's
        mark = checkout / '.git' / PREPARED
        if inputs is not None and self.prepared is None and self.marked(mark) == digest(inputs):
            self.prepared = inputs
            return
        self.prepared = None
        mark.unlink(missing_ok=True)
        done = self.call(list(SETUP), cwd=checkout, env=dict(self.environ), capture_output=True, text=True,
                         timeout=self.seconds('TOWER_SETUP_TIMEOUT_S', 1800), check=False)
        if done.returncode:
            said = SECRET.sub('<redacted>', (done.stderr or '') + (done.stdout or ''))
            error = Unprepared(f'setup: {said.strip()[-DETAIL_CHARS:]}')
            error.retryable = any(mark in said for mark in ENVIRONMENTAL)
            raise error
        self.prepared = inputs
        if inputs is not None:
            try:
                mark.write_text(digest(inputs) + '\n')
            except OSError:  # only the next process's setup again
                pass

    @staticmethod
    def marked(mark):
        try:
            return mark.read_text().strip()
        except OSError:
            return None

    def setup_inputs(self, checkout):
        """What setup.sh runs and reads at the checkout's commit, as git's own hashes, one line per path the commit has;
        None when git cannot say (the setup then always runs)."""
        found = self.call(['git', 'ls-tree', 'HEAD', '--', *SETUP_READS], cwd=checkout, capture_output=True, text=True,
                          check=False)
        return found.stdout if found.returncode == 0 and found.stdout else None

    def upload(self, run, log):
        if not self.bucket:
            kept = self.workdir / 'logs' / f"{run['run']}.log"
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(log, kept)
            return str(kept)
        key = f"runs/{run['job']}/{run['run']}.log"
        if self.s3 is None:
            import boto3
            self.s3 = boto3.client('s3', region_name=self.environ.get('AWS_REGION'))
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=log.read_bytes(), ContentType='text/plain; charset=utf-8')
        return f's3://{self.bucket}/{key}'


PUSHED_SLOT = 'pushed'  # HEAD-ON-PUSH: the clone beside the slots' that the pushed heads are fetched into
PUSHED = ("select occurred_at::text, payload::text from log.event where type = 'forge.repository.pushed' "
          "and occurred_at > %(since)s::timestamptz order by occurred_at limit 50")
NOW = 'select clock_timestamp()::text'
SHA = re.compile(r'[0-9a-f]{40}')


def pushed_heads(payload, repo):
    """The (branch, commit) a push of `repo` created or moved, from its forge.repository.pushed (Origin's delivery)."""
    event = ((payload or {}).get('delivery') or {}).get('event') or {}
    body = event.get('payload') or {}
    where = body.get('repository') or {}
    if f"{(where.get('owner') or {}).get('slug')}/{where.get('name')}" != repo:
        return []
    heads = []
    for update in body.get('refUpdates') or []:
        ref, commit = str(update.get('ref') or ''), str(update.get('after') or '')
        if update.get('deleted') or not ref.startswith('refs/heads/') or not SHA.fullmatch(commit) or not commit.strip('0'):
            continue
        heads.append((ref[len('refs/heads/'):], commit))
    return heads


class Pushed:
    """HEAD-ON-PUSH (docs/operations/aws.md 22.9): the heads pushed to the served repository, fetched as the forge says
    they were pushed (forge.repository.pushed, in the log within a second, notified on tower_deploy), into a clone beside
    the slots'. A gate starts once its PR is open, seconds to minutes after the push, and the first run of each slot
    took its head from the forge (about 2.4 s each, the five slots at once); from_sibling now finds it on the disk."""

    def __init__(self, box, repo, log=None):
        self.box, self.repo, self.since, self.log = box, repo, None, log or LOG.info

    def step(self, db):
        """The pushes since the last look fetched; answers how many heads reached the forge."""
        if self.since is None:  # from now on: a head pushed before the task started is the slots' to fetch
            self.since = db.rows(NOW)[0][0]
            return 0
        fetched = 0
        for at, payload in db.rows(PUSHED, {'since': self.since}):
            self.since = at
            for ref, commit in pushed_heads(json.loads(payload), self.repo):
                began = time.monotonic()
                try:
                    if self.box.keep_pushed(self.repo, ref, commit):
                        fetched += 1
                        self.log('pushed: %s %s fetched in %.2f s', ref, commit[:12], time.monotonic() - began)
                except Unprepared as error:  # the slot's own fetch is the answer then
                    self.log('pushed: %s %s not fetched: %s', ref, commit[:12], error)
        return fetched

    def start(self, scope, stop, wait, active=None):
        def loop():
            while not stop.is_set():
                if active is None or active():
                    try:
                        with scope() as db:
                            self.step(db)
                    except Exception:  # noqa: BLE001 - the next push looks again
                        LOG.exception('pushed: look failed')
                wait(60)
        thread = threading.Thread(target=loop, name='pushed', daemon=True)
        thread.start()
        return thread


FRACTION = re.compile(r'(\.\d{6})\d+')  # ECS writes nanoseconds; datetime keeps microseconds


def prewarm(boxes, repo, ref, clock=time.monotonic, heartbeat=None, beat_s=15.0, timeout_s=420.0, tries=2,
            record=None, name='runner', log=None):
    """Warm a starting task before its slots take any run (F1): fetch the base head and run setup once per slot, so the
    toolchain cache (keyed by the manifests' digest) and the base checkout exist when the first check arrives. The
    slots' loops have not started, so no lease is held; `heartbeat` is called every `beat_s` from a thread meanwhile. A
    toolchain download that failed is tried again (`tries` in all); any failure is logged and answered False, never
    raised: the runner then goes on cold. Answers (ok, seconds) and `record`s platform.runner.warm {task, seconds, ok}."""
    log = log or (lambda *_: None)
    started, stop, ok = clock(), threading.Event(), False
    slots, head_s = [], None
    beater = None
    if heartbeat is not None:
        def beat():
            while not stop.is_set():
                try:
                    heartbeat()
                except Exception:  # noqa: BLE001 - a heartbeat that fails must not end the warm-up
                    pass
                stop.wait(beat_s)
        beater = threading.Thread(target=beat, name='prewarm-heartbeat', daemon=True)
        beater.start()
    try:
        at = clock()
        head = boxes[0].head_of(repo, ref)
        head_s = round(clock() - at, 3)
        spec = {'repo': repo, 'ref': ref, 'commit': head}
        for box in boxes:
            for attempt in range(1, tries + 1):
                left = timeout_s - (clock() - started)
                if left <= 0:
                    raise Unprepared(f'prewarm: over {timeout_s:g} s')
                box.environ['TOWER_SETUP_TIMEOUT_S'] = str(min(left, box.seconds('TOWER_SETUP_TIMEOUT_S', 1800)))
                try:
                    checkout = box.checkout_of(spec)
                    at = clock()
                    box.fetch(spec, checkout)
                    fetched = clock()
                    box.prepare(checkout)  # setup.sh holds its own install lock (flock), so the slots' runs never overlap
                    # PREWARM-PARTS: where each slot's warm-up went, in platform.runner.warm
                    slots.append({'fetch_s': round(fetched - at, 3), 'setup_s': round(clock() - fetched, 3)})
                    break
                except Unprepared as error:
                    if not error.retryable or attempt == tries:
                        raise
                    log(f'prewarm: {error}; trying again')
        ok = True
    except Exception as error:  # noqa: BLE001 - a failed warm-up never stops the runner
        log(f'prewarm failed, going on cold: {error}')
    finally:
        stop.set()
        if beater is not None:
            beater.join(timeout=5)
    seconds = round(clock() - started, 3)
    if record is not None:
        try:
            record({'task': name, 'seconds': seconds, 'ok': ok, **({'head_s': head_s} if head_s is not None else {}),
                    **({'slots': slots} if slots else {})})
        except Exception as error:  # noqa: BLE001
            log(f'prewarm: the event was not recorded: {error}')
    return ok, seconds


def cold_start(now=None, environ=None, opener=urllib.request.urlopen):
    """Seconds since this task's image pull started, from the ECS task metadata (v4); None outside ECS or unread."""
    uri = (os.environ if environ is None else environ).get('ECS_CONTAINER_METADATA_URI_V4')
    if not uri:
        return None
    try:
        with opener(f'{uri}/task', timeout=5) as answer:
            pulled = json.loads(answer.read()).get('PullStartedAt')
        started = datetime.fromisoformat(FRACTION.sub(r'\1', pulled).replace('Z', '+00:00'))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return ((now or datetime.now(timezone.utc)) - started).total_seconds()


class Ahead:
    """LOGIN-AHEAD: a login started now, in a thread of its own, for the caller that will need it: result() waits for
    it and answers the connection once, or None when the login failed (the caller then logs in itself, and raises
    what it finds). A successor the role waits for (one started, or a reserve told to go, under a pointer that already
    names it) logged in one connection after the other, each a TLS handshake and an IAM check: the ones its first work
    needs are started together."""

    def __init__(self, connect, start=None):
        self.found = None

        def work():
            try:
                self.found = connect()
            except Exception:  # noqa: BLE001 - the caller's own login says why
                LOG.exception('container: a login started ahead failed; the caller logs in itself')
        self.thread = (start or (lambda target: threading.Thread(target=target, name='login-ahead', daemon=True)))(work)
        self.thread.start()

    def result(self):
        self.thread.join()
        found, self.found = self.found, None
        return found


class Reconnecting:
    """rows(sql, params) over a connection that is made again on the call after one broke. A call that breaks is not
    repeated: what the runner sends is fenced by its lease, so a lost answer costs at most a lease that expires."""

    def __init__(self, connect, wrap):
        self.connect, self.wrap, self.db, self.early = connect, wrap, None, None

    def ahead(self, start=None):
        """LOGIN-AHEAD: this connection's login starts now, apart; ready() waits for it instead of logging in."""
        if self.db is None and self.early is None:
            self.early = Ahead(self.connect, start)
        return self

    def ready(self):
        """IMAGE-SWAP-TICK: the kept connection, made (again) when there is none: what a caller times apart from its
        statement (connect_s). Nothing on the wire when it is there."""
        early, self.early = self.early, None
        if early is not None and self.db is None:
            found = early.result()
            if found is not None:
                self.db = self.wrap(found)
        if self.db is None or self.db.connection.closed:
            self.db = self.wrap(self.connect())
        return self.db

    @contextlib.contextmanager
    def scope(self):
        """IMAGE-SWAP-TICK: a scope over the kept connection, ready on entry: what workflows.connected is over the pool."""
        self.ready()
        yield self

    def rows(self, sql, params=None):
        self.ready()
        try:
            return self.db.rows(sql, params)
        except Exception:
            if self.db.connection.closed or getattr(self.db.connection, 'broken', False):
                self.db = None
            raise
