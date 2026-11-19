"""QUEUE-RELOAD (the Torre, 15/11/2026; Daniel's target of 09/11): a code-only merge is live about a second after it lands.

The target counts from the merge into main to the new code running, for a merge that changes code only (no network, data
or infrastructure). The new version is prepared while the merge queue verifies the merge's commit, so the deploy is the
reload alone. Before this, the push's doorbell started the deploy build (8 s after the merge), CodeBuild provisioned it
(7 s), and the build classified, bundled, asked for the reload and waited for the look (8 s): the reload began at +26 s
(#25: merged 17:59:21, running at 17:59:49, proven at 18:00:00).

GitHub's merge queue builds the merge's commit itself (gh-readonly-queue/main/pr-<n>-<base>), runs tower/gate on it and
moves main to that same commit. The doorbell workflow's merge_group job (services/runner/github/deploy-doorbell.yml) is
already running there: it rings `prepare` with that sha at once, watches main (scripts/lib/deploy.py queue) and rings
`landed` the moment main is that sha. The doorbell Lambda passes both to the port (a direct invocation, IAM's), which
records platform.deploy.queue {event, sha} and wakes this look on tower_deploy (http_port.queue_state).

  prepare  the service fetches main and the merge-queue branches from the engine's repository (engine.repo(), public) into
           a clone of its own. The sha must be the head of one of them. The changes are /tower/deploy/last-sha..sha. The
           classifier and the bundler are the ones of last-sha's tree, the deployed and verified code: the merge's own code
           is only read, never run, before its verdict. Code-only (deploy_classify.code_only: the deploy build's own rule
           of code_live), the bundle is built from the sha's files (lambda_package.build_code, deterministic) and put at
           artifacts/lambda/tower-code/<sha256>.zip. Recorded as platform.deploy.prepared {sha, base, parent, code_only,
           why, key, sha256, bytes, s}, once per (sha, base).
  landed   the claim is checked, never trusted: main on the engine's repository is the sha (git ls-remote),
           /tower/deploy/last-sha (the build of the merge before it ended green) is an ancestor of the sha, and the
           prepared bundle, classified on every path from last-sha to the sha (so the classification is the one the deploy
           build will make), is code-only. BURST-SWAP (the Torre, 16/11/2026): a sha whose first parent is not last-sha
           is a burst, merges that landed together (the queue merges up to max_entries_to_merge at once) or one after
           another faster than a build ends; its bundle is the sha's tree alone, so the heir of the last green commit
           takes the pointer once, and the merges before it in the burst need no deploy of their own. Then the swap below, or, with no heir
           ready, the order of the reload in place of the service alone (AutoDeploy.order, by: queue): the same order,
           proof and deploy.live_code as FAST-PATH-RELOAD. Recorded as platform.deploy.queue_reload {sha, state:
           swapped|ordered|skipped, why, verify_s, version, wrote_at}. PUSH-STEPS (REQ-deploy-1s, 19/11): and the
           instant of each step, epoch seconds: began_at (the look took the landing), main_at (git ls-remote answered),
           verified_at (the claim checked); with the word's heard (the doorbell) and port_at (the port) of
           platform.deploy.queue, `scripts/deploy status` prints the landing's steps (deploy.steps).

QUEUE-SWAP (the Torre, 15/11: the deploy is the pointer's move). A prepared code-only bundle is also wanted
(platform.deploy.successor {digest, key, branch: queue, state: wanted}, and tower_config woken): each
ECS task's process tells its supervisor, which starts the heir, a successor process of that bundle inside the task
(live_image IN-TASK-STANDBY). The heir boots, launches DBOS and warms its statements while the queue verifies; it takes
no work, no lease and writes no engine state, and beats (work.standby_beat). At the landing, a heir that beat within
deploy.standby_fresh_s gets the service's pointer, alone and in one statement (SWAP: deploy.live_image_service = the
bundle, and platform.deploy.image_swap {by: queue, roles: [service], head, versions}); the NOTIFY of the pointer's write
turns it live, and the old process stands by. Its proof is its own (no runner's canary: the gate already proved the code
in the queue): its first work (image_live) and PROVE_QUEUE_S of live beats after it (live_image.RELOAD_OF), then the old
process gives it the role for good (Reload.heir), it adopts it ({state: reloaded}) and hands the pointer back to empty,
and this look writes deploy.live_code for the merge (adopted(); AutoDeploy.live_code). If the heir stops beating, the old
process takes the role back by its watch (deploy.live_stale_s, IMAGE-SWAP-FAILOVER); if it never works, the swap is
undone (settle_image, SWAP_LIMIT_S). A heir of a head that did not land is withdrawn at the next landing.

The push still rings the deploy build, which stays the net: it classifies the merge itself, finds the head's code live
(code_live) or asks for the same order (the look's order is the build's: ordered already), and runs the smoke and moves
last-sha. A merge that is not code-only, or a check that fails, leaves everything to it, as before. deploy.queue_reload
false turns this look off. A change to the classifier, the bundler or their storage adapter is never prepared here: the
deploy build's own copy decides it.
"""
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time

from . import config_data, engine, live_image

LOG = logging.getLogger('tower_infra.queue_deploy')
QUEUE, PREPARED, OUTCOME = 'platform.deploy.queue', 'platform.deploy.prepared', 'platform.deploy.queue_reload'
EVENTS = ('prepare', 'landed')
SHA = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'[0-9a-f]{64}')
LAST_SHA = '/tower/deploy/last-sha'
WORK = Path(os.environ.get('TOWER_QUEUE_WORK', '/tmp/tower-queue'))
GIT_TIMEOUT_S = 60
LS_TIMEOUT_S = 10
CONTROL = ('scripts/lib/deploy_classify.py', 'scripts/lib/lambda_package.py', 'scripts/lib/adapters/')
CODE_INPUTS = ('infra/service/tower_infra', 'infra/db/migrations', 'infra/service/requirements.txt')
REFS = ('+refs/heads/main:refs/remotes/origin/main', '+refs/heads/gh-readonly-queue/*:refs/remotes/origin/queue/*')

# the doorbell's words of the last half hour, oldest first: (event, sha, epoch)
QUEUED = ("select payload->>'event', payload->>'sha', extract(epoch from occurred_at)::float8 from log.event "
          f"where type = '{QUEUE}' and tenant_id is null and occurred_at > now() - interval '30 minutes' "
          "order by occurred_at")
PREPARED_OF = (f"select payload::text from log.event where type = '{PREPARED}' and event_id = %(id)s "
               "and occurred_at > now() - interval '1 day' limit 1")
# BASE-MOVED: the records of a commit prepared on other bases, newest first
PREPARED_FOR = (f"select payload::text from log.event where type = '{PREPARED}' and event_id like %(prefix)s "
                "and occurred_at > now() - interval '1 day' order by occurred_at desc limit 5")
OUTCOME_OF = (f"select payload::text from log.event where type = '{OUTCOME}' and event_id = %(id)s "
              "and occurred_at > now() - interval '1 day' limit 1")
SAY = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       "select %(id)s, null, %(type)s, clock_timestamp(), 'autodeploy', 'deploy/queue', %(payload)s::jsonb "
       "where not exists (select 1 from log.event where event_id = %(id)s and type = %(type)s "
       "and occurred_at > now() - interval '2 days')")

# QUEUE-SWAP: a want said or withdrawn, once per id, and the tasks' processes woken
WANT = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        f"select %(id)s, null, '{live_image.SUCCESSOR}', clock_timestamp(), 'autodeploy', 'deploy/successor', %(payload)s::jsonb "
        f"where not exists (select 1 from log.event where event_id = %(id)s and type = '{live_image.SUCCESSOR}' "
        "and occurred_at > now() - interval '2 days') returning type) select pg_notify('tower_config', type) from said")
# the merge queue's wants still standing: the newest want of each digest in a day, said by this look (branch: queue)
WANTED = ("select digest, sha from (select distinct on (payload->>'digest') payload->>'digest' as digest, "
          "payload->>'state' as state, payload->>'sha' as sha "
          f"from log.event where type = '{live_image.SUCCESSOR}' and tenant_id is null and occurred_at > now() - interval '1 day' "
          "and payload->>'branch' = 'queue' and payload->>'state' in ('wanted', 'withdrawn') "
          "order by payload->>'digest', occurred_at desc) w where state = 'wanted'")
# the service's pointer to the heir, in one statement, only while it beats: the swap and its record (the pointer's write
# notifies tower_config, which turns the heir live). Answers (version, wrote_at) when it swapped
SWAP = ("with w as (insert into work.config_value as v (tenant_id, key, value, actor, reason) "
        f"select t.id, '{live_image.KEYS['service']}', to_jsonb(%(digest)s::text), 'autodeploy', %(reason)s from work.tenant t "
        "where t.name = %(tenant)s and exists (select 1 from work.standby_beat b where b.role = 'service' "
        "and b.digest = %(digest)s and b.beat_at > clock_timestamp() - make_interval(secs => %(fresh_s)s::float8)) "
        "on conflict (tenant_id, key) do update set value = excluded.value, version = v.version + 1, actor = excluded.actor, "
        "reason = excluded.reason, updated_at = clock_timestamp() returning v.version, v.updated_at), "
        "swap as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
        "select %(id)s, null, 'platform.deploy.image_swap', clock_timestamp(), 'autodeploy', 'deploy/image', %(payload)s::jsonb "
        "|| jsonb_build_object('swapped', true, 'by', 'queue', 'roles', jsonb_build_array('service'), 'versions', "
        f"jsonb_build_object('{live_image.KEYS['service']}', w.version), "
        "'wrote_at', round(extract(epoch from w.updated_at)::numeric, 3)) from w returning 1) "
        "select version, round(extract(epoch from updated_at)::numeric, 3)::float8 from w")
# a swap of the merge queue for this head and bundle, in the hour: the swap is in charge (the build orders nothing)
SWAP_OF = ("select 1 from log.event where type = 'platform.deploy.image_swap' and tenant_id is null "
           "and occurred_at > now() - interval '1 hour' and payload->>'swapped' = 'true' and payload->>'by' = 'queue' "
           "and payload->>'head' = %(head)s and payload->>'digest' = %(digest)s limit 1")
# MERGED-WANTS: the bundle the live code is (deploy.live_code '<bundle>@<merge>'): a landing with nothing to deploy never
# withdraws its want, whatever commit asked for it
LIVE_CODE = ("select v.value #>> '{}' from work.config_value v join work.tenant t on t.id = v.tenant_id "
             "where t.name = %(tenant)s and v.key = 'deploy.live_code'")
# the head of the newest swap of the merge queue whose heir took the role over ({state: reloaded} of its bundle by the
# service since the swap): what deploy.live_code names (AutoDeploy.live_code writes it once, guarded by the swap's time)
ADOPTED = ("select s.payload->>'head' from (select payload, occurred_at from log.event "
           "where type = 'platform.deploy.image_swap' and tenant_id is null and occurred_at > now() - interval '1 hour' "
           "and payload->>'swapped' = 'true' and payload->>'by' = 'queue' order by occurred_at desc limit 1) s "
           f"where exists (select 1 from log.event r where r.type = '{live_image.RELOAD}' and r.tenant_id is null "
           "and r.occurred_at >= s.occurred_at and r.payload->>'role' = 'service' and r.payload->>'state' = 'reloaded' "
           "and r.payload->>'digest' = s.payload->>'digest')")

# run in a subprocess with last-sha's scripts/lib first on the path: the classifier's verdict and, code-only, the bundle
BUILD = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import deploy_classify
paths = json.loads(sys.stdin.read())
ok, why = deploy_classify.code_only(paths)
out = {'code_only': bool(ok), 'why': why}
if ok:
    import lambda_package
    data, digest, _ = lambda_package.build_code(sys.argv[2])
    with open(sys.argv[3], 'wb') as sink:
        sink.write(data)
    out.update(sha256=digest, bytes=len(data))
print(json.dumps(out))
'''


class Refused(Exception):
    """A step of the preparation that says why the merge is left to the deploy build."""


def url(environ=None):
    return f'https://github.com/{engine.repo(environ)}.git'


class QueueReload:
    """The look's part for the doorbell's queue words. ssm(name) reads a parameter (None when absent); put(key, data)
    stores a bundle unless the key exists; run is subprocess.run."""

    def __init__(self, ssm, put, run=subprocess.run, clock=time.time, work=WORK, remote=None, config=None,
                 tenant=config_data.TENANT):
        self.ssm, self.put, self.run, self.clock, self.work = ssm, put, run, clock, Path(work)
        self.remote, self.config, self.tenant = remote, config, tenant
        self.done = set()  # (event, sha) this process already handled

    def setting(self, name):
        """A deploy.* datum as the service reads it (config_data.Config), its default without one."""
        return self.config.get(name) if self.config is not None else config_data.SPEC[name][1]

    # --- git ------------------------------------------------------------------------------------------------------
    def git(self, *args, timeout=GIT_TIMEOUT_S, data=None):
        out = self.run(['git', '-C', str(self.work / 'repo'), *args], capture_output=True, timeout=timeout, input=data)
        if out.returncode != 0:
            raise Refused(f"git {args[0]} failed: {(out.stderr or b'').decode('utf-8', 'replace').strip()[:200]}")
        return out.stdout

    def fetch(self):
        repo = self.work / 'repo'
        if not (repo / '.git').is_dir():
            shutil.rmtree(repo, ignore_errors=True)
            repo.mkdir(parents=True, exist_ok=True)
            self.git('init', '-q')
        self.git('fetch', '-q', '--no-tags', '--prune', self.remote or url(), *REFS)

    def heads(self):
        return set(self.git('for-each-ref', '--format=%(objectname)', 'refs/remotes/origin/').decode().split())

    def queued(self):
        """PREPARE-ON-BASE-MOVE: the heads of main and the merge-queue branches now (fetched once), or none when the
        repository does not answer (then nothing is prepared again: the landing prepares it, as before)."""
        try:
            self.fetch()
            return self.heads()
        except (Refused, OSError, subprocess.SubprocessError):
            return set()

    def ancestor(self, base, sha):
        """BURST-SWAP: refuses unless base is an ancestor of sha (git merge-base --is-ancestor)."""
        out = self.run(['git', '-C', str(self.work / 'repo'), 'merge-base', '--is-ancestor', base, sha],
                       capture_output=True, timeout=GIT_TIMEOUT_S)
        if out.returncode != 0:
            raise Refused(f'the deployed {base[:12]} is not an ancestor of {sha[:12]}')

    def main_head(self):
        out = self.run(['git', 'ls-remote', self.remote or url(), 'refs/heads/main'], capture_output=True,
                       timeout=LS_TIMEOUT_S)
        if out.returncode != 0:
            raise Refused('git ls-remote of main failed')
        found = (out.stdout or b'').decode().split()
        return found[0] if found else ''

    def tree(self, sha, paths, into):
        shutil.rmtree(into, ignore_errors=True)
        into.mkdir(parents=True)
        data = self.git('archive', '--format=tar', sha, '--', *paths)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(into, filter='data')

    # --- the two words ----------------------------------------------------------------------------------------------
    def prepared(self, db, sha, base):
        rows = db.rows(PREPARED_OF, {'id': f'{PREPARED}:{sha}:{base}'})
        return json.loads(rows[0][0]) if rows and rows[0][0] else None

    def prepare(self, db, sha):
        """The bundle of a merge's commit, prepared once per (sha, base) and recorded; answers the record."""
        began = self.clock()
        base = str(self.ssm(LAST_SHA) or '').strip()
        found = self.prepared(db, sha, base) if SHA.fullmatch(base) else None
        if found:
            return found
        found = self.carried(db, sha, base) if SHA.fullmatch(base) else None
        if found:
            return found
        found = {'sha': sha, 'base': base, 'code_only': False}
        try:
            if not SHA.fullmatch(base):
                raise Refused(f'{LAST_SHA} is {base[:40] or "absent"}')
            self.fetch()
            if sha not in self.heads():
                raise Refused(f'{sha[:12]} is the head of neither main nor a merge-queue branch of {engine.repo()}')
            found['parent'] = self.git('rev-parse', f'{sha}^1').decode().strip()
            self.git('cat-file', '-e', f'{base}^{{commit}}')
            paths = self.git('diff', '--name-only', '--no-renames', f'{base}..{sha}').decode().splitlines()
            control = [path for path in paths if path.startswith(CONTROL)]
            if control:
                raise Refused('the classifier or the bundler changes (' + ', '.join(control[:3]) + '): the deploy build decides')
            self.tree(base, ['scripts/lib'], self.work / 'ctl')
            self.tree(sha, list(CODE_INPUTS), self.work / 'tree')
            bundle = self.work / 'bundle.zip'
            out = self.run([sys.executable, '-I', '-c', BUILD, str(self.work / 'ctl' / 'scripts' / 'lib'),
                            str(self.work / 'tree'), str(bundle)], input=json.dumps(paths).encode(), capture_output=True,
                           timeout=GIT_TIMEOUT_S)
            if out.returncode != 0:
                raise Refused(f"the classifier failed: {(out.stderr or b'').decode('utf-8', 'replace').strip()[-200:]}")
            said = json.loads((out.stdout or b'{}').decode().strip().splitlines()[-1])
            found.update(code_only=bool(said.get('code_only')), why=str(said.get('why') or '')[:300])
            if found['code_only']:
                if not DIGEST.fullmatch(str(said.get('sha256') or '')):
                    raise Refused('the bundle has no digest')
                key = f"artifacts/lambda/tower-code/{said['sha256']}.zip"
                self.put(key, bundle.read_bytes())
                found.update(key=key, sha256=said['sha256'], bytes=said.get('bytes'))
                self.want(db, found['sha256'], key, sha)  # QUEUE-SWAP: the heir boots while the queue verifies
        except Refused as error:
            found.update(code_only=False, why=str(error))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            found.update(code_only=False, why=f'{type(error).__name__}: {str(error)[:200]}')
        found['s'] = round(self.clock() - began, 3)
        if SHA.fullmatch(base):
            db.rows(SAY, {'id': f'{PREPARED}:{sha}:{base}', 'type': PREPARED, 'payload': json.dumps(found)})
        LOG.info('queue: prepared %s on %s: %s (%s) in %.1fs', sha[:12], base[:12],
                 'code-only' if found['code_only'] else 'not code-only', found.get('why'), found['s'])
        return found

    def carried(self, db, sha, base):
        """BASE-MOVED (the Torre, 16/11/2026): the record of the sha prepared on an earlier deployed base, carried to this
        base with no new bundle, when the earlier base is an ancestor of this one, this one of the sha, and every path from
        this base to the sha was a path from the earlier one (so the classification of this diff, a part of a code-only
        diff, is code-only or has nothing for the service; the bundle is the sha's tree either way). A build that ends during
        a burst moves the base under a landing; without this the landing prepared the bundle again (#117: the pointer 2.1 s
        after main moved, against 0.4 s). Local git only; anything it cannot read is no carry, and the prepare runs."""
        began = self.clock()
        for (payload,) in db.rows(PREPARED_FOR, {'prefix': f'{PREPARED}:{sha}:%'}) or []:
            earlier = json.loads(payload) if payload else {}
            old = str(earlier.get('base') or '')
            if not earlier.get('code_only') or not SHA.fullmatch(old) or old == base:
                continue
            try:
                self.ancestor(old, base)
                self.ancestor(base, sha)
                now = set(self.git('diff', '--name-only', '--no-renames', f'{base}..{sha}').decode().splitlines())
                then = set(self.git('diff', '--name-only', '--no-renames', f'{old}..{sha}').decode().splitlines())
            except (Refused, OSError, subprocess.SubprocessError):
                return None
            if not now <= then:
                return None
            found = {**earlier, 'base': base, 'carried_from': old, 's': round(self.clock() - began, 3)}
            db.rows(SAY, {'id': f'{PREPARED}:{sha}:{base}', 'type': PREPARED, 'payload': json.dumps(found)})
            LOG.info('queue: prepared %s on %s carried from %s in %.3fs', sha[:12], base[:12], old[:12], found['s'])
            return found
        return None

    def want(self, db, digest, key, sha, state='wanted'):
        """QUEUE-SWAP: the heir of a bundle wanted (or withdrawn) in each ECS task: platform.deploy.successor and the NOTIFY
        of tower_config its processes read the wants on (live_image.Order.wants)."""
        at = self.clock()
        db.rows(WANT, {'id': f'{live_image.SUCCESSOR}:{digest}:{state}:queue:{sha}', 'payload': json.dumps(
            {'digest': digest, 'key': key, 'branch': 'queue', 'sha': sha, 'state': state, 'at': round(at, 3)})})
        LOG.info('queue: a heir of %s (%s) in each ECS task is %s', digest[:12], sha[:12], state)

    def withdraw(self, db, sha, keep=None):
        """QUEUE-SWAP: the heirs of the merge queue's bundles but `keep` withdrawn at a landing. BURST-HEIRS (the Torre,
        16/11/2026): but for an entry still in the queue. The queue builds up to five entries side by side, so a want whose
        commit is still the head of a merge-queue branch is an entry behind this landing, and its heir is the next swap's;
        a want of a group that merged with this one or left the queue has no branch any more. MERGED-WANTS (16/11): a want
        whose commit is in main's history by now (an ancestor of the landing) is withdrawn even while its branch is still
        seen, the moment after a batch merged (#130's at 03:24:25), and so is one a landing with nothing to deploy never
        withdrew (#114's at 02:35, still held at 03:41 in one of the two places). With no answer from the repository
        every want but `keep` is withdrawn, as before."""
        try:
            self.fetch()
            queued = self.heads()
        except (Refused, OSError, subprocess.SubprocessError):
            queued = set()
        for digest, wanted in db.rows(WANTED, {}) or []:
            if not digest or digest == keep:
                continue
            if wanted and wanted != sha and wanted in queued and not self.merged(wanted, sha):
                continue
            self.want(db, digest, None, sha, state='withdrawn')

    def settle(self, db, sha):
        """MERGED-WANTS (the Torre, 16/11/2026): at a landing on main that the fast path does not carry (a merge of docs,
        tests or the classifier), the wants of the commits in main's history are withdrawn but the live code's bundle
        (deploy.live_code). Before, such a landing withdrew nothing, so a merged commit's want stood and, with two heirs
        the oldest first, held a place a landing after it needed (#114's at 02:35, #132's landing at 03:41: reloaded).
        Never raises."""
        try:
            said = db.rows(LIVE_CODE, {'tenant': self.tenant}) or []
            live = str((said[0][0] if said else '') or '').split('@')[0]
            for digest, wanted in db.rows(WANTED, {}) or []:
                if digest and digest != live and wanted and (wanted == sha or self.merged(wanted, sha)):
                    self.want(db, digest, None, sha, state='withdrawn')
        except Exception:  # noqa: BLE001 - a want left standing is the next landing's to withdraw
            LOG.exception('queue: the wants of %s were not settled', sha[:12])

    def merged(self, wanted, sha):
        """MERGED-WANTS: whether `wanted` is an ancestor of `sha` (in main's history once sha landed); unknown is not."""
        try:
            out = self.run(['git', '-C', str(self.work / 'repo'), 'merge-base', '--is-ancestor', wanted, sha],
                           capture_output=True, timeout=GIT_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return False
        return out.returncode == 0

    def swapping(self, db, head, digest):
        """QUEUE-SWAP: whether a swap of the merge queue gave the service's pointer to this head's bundle (the hour)."""
        return bool(db.rows(SWAP_OF, {'head': head, 'digest': digest}))

    def adopted(self, db):
        """QUEUE-SWAP: the head of the newest queue swap whose heir took the role over, else None."""
        found = db.rows(ADOPTED, {})
        return found[0][0] if found and found[0][0] else None

    def swap(self, db, sha, found):
        """QUEUE-SWAP: the service's pointer to the heir of the merge's bundle when it beats; answers (version, wrote_at)
        or None (no heir ready: the order of the reload in place, as before)."""
        digest, key = found['sha256'], found['key']
        done = db.rows(SWAP, {
            'digest': digest, 'tenant': self.tenant, 'fresh_s': float(self.setting('deploy.standby_fresh_s')),
            'reason': f'QUEUE-SWAP: the merge queue landed {sha[:12]}: its heir takes the role',
            'id': f'platform.deploy.image_swap:{digest}:queue:{sha}',
            'payload': json.dumps({'digest': digest, 'key': key, 'head': sha})})
        if not done:
            return None
        version, wrote_at = int(done[0][0]), float(done[0][1])
        # what deploy.sh's reload_live reads of this head (reload_states): the swap is the head's own reload
        db.rows(SAY, {'id': f'{live_image.RELOAD}:service:{digest}:swapped:{sha}', 'type': live_image.RELOAD,
                      'payload': json.dumps({'role': 'service', 'digest': digest, 'head': sha, 'state': 'swapped',
                                             'by': 'queue', 'version': version, 'at': wrote_at})})
        return version, wrote_at

    def landed(self, db, sha, order):
        """The reload of a merge that landed, ordered once its claim is checked; answers the outcome recorded."""
        began = self.clock()
        outcome = {'sha': sha, 'state': 'skipped', 'began_at': round(began, 3)}  # PUSH-STEPS: each step's instant
        on_main = False
        try:
            head = self.main_head()
            outcome['main_at'] = round(self.clock(), 3)  # the ls-remote of main answered
            if head != sha:
                raise Refused(f'main is {head[:12] or "unknown"}, not {sha[:12]}')
            on_main = True
            found = self.prepare(db, sha)
            if not found.get('code_only'):
                raise Refused(f"not code-only: {found.get('why')}")
            if found.get('parent') != found.get('base'):  # BURST-SWAP: the deployed commit is behind the sha on main
                self.ancestor(found['base'], sha)
            verified = self.clock()
            outcome.update(verify_s=round(verified - began, 3), verified_at=round(verified, 3))
            swapped = self.swap(db, sha, found)  # QUEUE-SWAP: the pointer's move to the heir already up
            if swapped:
                outcome.update(digest=found['sha256'], state='swapped', version=swapped[0], wrote_at=swapped[1])
            else:
                made, busy, bad = order(sha, found['sha256'], found['key'])
                outcome.update(digest=found['sha256'], state='ordered' if made or busy == sha else 'skipped')
                if not (made or busy == sha):
                    outcome['why'] = f'a reload onto {found["sha256"][:12]} failed before' if bad else \
                        f'the order of {str(busy)[:12]} is not settled'
            self.withdraw(db, sha, keep=found['sha256'] if swapped else None)
        except Refused as error:
            outcome['why'] = str(error)
            if on_main:  # MERGED-WANTS: nothing for the fast path, but the merged commits' heirs are done
                self.settle(db, sha)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            outcome['why'] = f'{type(error).__name__}: {str(error)[:200]}'
        outcome['s'] = round(self.clock() - began, 3)
        db.rows(SAY, {'id': f'{OUTCOME}:{sha}', 'type': OUTCOME, 'payload': json.dumps(outcome)})
        LOG.info('queue: landed %s: %s%s', sha[:12], outcome['state'], f" ({outcome['why']})" if outcome.get('why') else '')
        return outcome

    def look(self, db, order):
        """Each word not handled yet: every prepare (newest last), then the newest landing only. PREPARE-ON-BASE-MOVE (the
        Torre's AWS review, 16/11/2026): a prepare is handled once per deployed base, so when the deploy build of a merge
        that was not code-only (a stack) ends green and moves last-sha (its platform.deploy.ended wakes this look), each
        commit still at the head of a merge-queue branch is prepared again on the new base, and its heir warms while it
        waits. Before, it was prepared only at its landing, too late for a heir: #144 and #145, queued behind #142's stacks,
        landed at 05:11:29, wanted at 05:11:30.432, ordered a reload 23 ms later (21.8 s) with the heir held 93 ms after it.
        A process that starts
        mid-way (the reloaded one) finds the landing's outcome recorded and only follows the order: AutoDeploy.order
        answers it busy with this head, which makes it the order this look follows. Never raises."""
        try:
            words = [(event, sha) for event, sha, _ in db.rows(QUEUED, {}) or []
                     if event in EVENTS and SHA.fullmatch(str(sha or ''))]
            landings = [sha for event, sha in words if event == 'landed']
            waiting = list(dict.fromkeys(sha for event, sha in words if event == 'prepare' and sha not in landings))
            base = str(self.ssm(LAST_SHA) or '').strip() if waiting else ''
            queued = None
            for sha in waiting:
                if ('prepare', sha, base) in self.done:
                    continue
                again = ('prepare', sha) in self.done  # PREPARE-ON-BASE-MOVE: prepared before, on another base
                self.done.update({('prepare', sha), ('prepare', sha, base)})
                if again:
                    queued = self.queued() if queued is None else queued
                    if sha not in queued:
                        continue
                self.prepare(db, sha)
            if landings and ('landed', landings[-1]) not in self.done:
                sha = landings[-1]
                self.done.add(('landed', sha))
                said = db.rows(OUTCOME_OF, {'id': f'{OUTCOME}:{sha}'})
                if said:
                    found = self.prepared(db, sha, str(self.ssm(LAST_SHA) or '').strip())
                    if found and found.get('code_only') and json.loads(said[0][0]).get('state') == 'ordered':
                        order(sha, found['sha256'], found['key'])  # follow it: the order exists, this answers busy
                    return  # a swap needs no following: the heir and the process it took over from do the rest
                self.landed(db, sha, order)
        except Exception:  # noqa: BLE001 - the deploy build is the net
            LOG.exception('queue: the look failed')
