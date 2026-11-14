"""PR-OBSERVATION (docs/operations/aws.md 22.9; item 3 of the Torre's order of 13/11: the delivery off the lane): what
`pr metadata` reads of a pull request, read by the live service with the management credential, not by the lane.

`pr metadata` (scripts/structure-check --metadata) judges the PR's body, commits, comments, pushes and standing against
its base. The lane read them from Origin with the box's login (forge_origin_client, `origin api`) and the pushes from the
reflog of its own clone (forge_origin_history): a credential and a state of the lane on the path of every merge. The live
service holds the forge's key (/tower/origin/forge-key, the forge executor's) and the log holds every push Origin
delivered (forge.repository.pushed). So:
  - POST /v1/pr-observation {pr, head} is one event, platform.forge.observation {id, state: asked, pr, head}, and a
    NOTIFY of tower_deploy;
  - the live service's look (Observer) takes each asked one once and reads, by the forge's CLI and key: the pull, its
    commits and its comments (every page), and the comparison of its base with the head; and from the log, the head
    branch's pushes and forced pushes; it says observed {observation} or failed {why};
  - GET /v1/pr-observation/<id> answers the newest state, the observation with it: Origin's own answers, as the lane's
    client read them, so the judge's adapter maps them as it always did.
"""
import json
import logging
import re
import time
from urllib.parse import quote

LOG = logging.getLogger('tower_infra.observations')
EVENT = 'platform.forge.observation'
REPO = 'openuniversity-si/open-university'
SHA = re.compile(r'^[0-9a-f]{40}$')
ASKED_S = 600
PAGE_SIZE, MAX_PAGES = 100, 20
PUSHES_DAYS = 30

SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"select %(event)s, null, '{EVENT}', clock_timestamp(), %(producer)s, 'forge/observation', %(payload)s::jsonb "
       "|| jsonb_build_object('at', round(extract(epoch from clock_timestamp())::numeric, 3)) "
       f"where not exists (select 1 from log.event where event_id = %(event)s and type = '{EVENT}' "
       "and occurred_at > now() - interval '1 day') returning type) "
       "select said.type from said cross join lateral (select pg_notify('tower_deploy', said.type)) n")
NEWEST = (f"select payload::text from log.event where type = '{EVENT}' and tenant_id is null "
          "and occurred_at > now() - interval '1 day' and payload->>'id' = %(id)s order by occurred_at desc limit 1")
OPEN = (f"select a.payload::text from log.event a where a.type = '{EVENT}' and a.tenant_id is null "
        "and a.payload->>'state' = 'asked' and a.occurred_at > clock_timestamp() - make_interval(secs => %(asked_s)s::float8) "
        f"and not exists (select 1 from log.event t where t.type = '{EVENT}' and t.tenant_id is null "
        "and t.payload->>'id' = a.payload->>'id' and t.payload->>'state' <> 'asked') order by a.occurred_at")
# OBSERVE-PUSHES (criterion 3): the head branch's pushes only, chosen by the database (its refUpdates holding the ref): every
# push of 30 days came back to be filtered here, the observation's pushes_s 0.23 to 0.82 s (13/11 22:16 to 22:45 UTC)
PUSHED = ("select payload::text from log.event where type = 'forge.repository.pushed' "
          f"and occurred_at > now() - interval '{PUSHES_DAYS} days' "
          "and payload #> '{delivery,event,payload,refUpdates}' @> %(ref)s::jsonb order by occurred_at desc")
# OBSERVE-ON-PUSH: one observation per (pr, head) a day, so a pre-observation at the push is the delivery's own
FOR_HEAD = (f"select payload->>'id' from log.event where type = '{EVENT}' and tenant_id is null "
            "and payload->>'state' = 'asked' and payload->>'pr' = %(pr)s and payload->>'head' = %(head)s "
            "and occurred_at > now() - interval '1 day' order by occurred_at desc limit 1")


def say(db, ident, state, producer, **more):
    return bool(db.rows(SAY, {'event': f'{EVENT}:{ident}:{state}', 'producer': producer,
                              'payload': json.dumps({'id': ident, 'state': state, **more})}))


def ask(db, who, body, clock=time.time_ns, configured=None):
    """POST /v1/pr-observation: what `pr metadata` reads of PR `pr`, judged on `head`, asked of the live service."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    body = body or {}
    pr = body.get('pr')
    if not (isinstance(pr, int) and pr > 0) or not SHA.match(str(body.get('head') or '')):
        raise port.PortError(400, 'pr (a positive integer) and head (40 hex) required')
    found = db.rows(FOR_HEAD, {'pr': str(pr), 'head': body['head']})  # OBSERVE-ON-PUSH: the one already asked for this head
    if found:
        return {'id': found[0][0], 'state': 'asked'}
    ident = str(clock())
    say(db, ident, 'asked', port.PRODUCER, pr=pr, head=body['head'])
    return {'id': ident, 'state': 'asked'}


def state(db, who, ident, configured=None):
    """GET /v1/pr-observation/<id>: its newest state, with the observation once observed (404 for none in a day)."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    found = db.rows(NEWEST, {'id': str(ident)})
    if not found:
        raise port.PortError(404, 'no such observation')
    return json.loads(found[0][0]) if isinstance(found[0][0], str) else found[0][0]


def pushes_of(rows, repo, branch):
    """The branch's pushes, newest first, as {before, after, timestamp, forced}, from forge.repository.pushed payloads
    (newest first): what the lane's reflog answered (forge_origin_history), from Origin's own word."""
    owner, name = repo.split('/')
    found, seen = [], set()
    for (payload,) in rows:
        said = json.loads(payload) if isinstance(payload, str) else payload
        event = ((said or {}).get('delivery') or {}).get('event') or {}
        body = event.get('payload') or {}
        where = body.get('repository') or {}
        if where.get('name') != name or (where.get('owner') or {}).get('slug') != owner:
            continue
        for update in body.get('refUpdates') or []:
            key = (update.get('before'), update.get('after'))
            if update.get('ref') != f'refs/heads/{branch}' or update.get('deleted') or key in seen:
                continue  # Origin delivers at least once: a push is said once
            seen.add(key)
            found.append({'before': update.get('before'), 'after': update.get('after'),
                          'timestamp': body.get('pushedAt'), 'forced': bool(update.get('forced'))})
    return found


class Observer:
    """The live service's half: each asked observation read once, with the forge's key, and said."""

    def __init__(self, forge, repo=REPO, clock=time.monotonic):
        self.forge, self.repo, self.clock = forge, repo, clock

    def api(self, path):
        return self.forge.api_get(path)  # forge.OriginForge: the forge's CLI and key

    def pages(self, path, key):
        found, token = [], ''
        for _ in range(MAX_PAGES):
            page = self.api(f'{path}?pageSize={PAGE_SIZE}' + (f'&pageToken={token}' if token else ''))
            found.extend(page.get(key) or [])
            token = page.get('nextPageToken') or ''
            if not token:
                return found
        raise RuntimeError(f'the {key} read is still paginating at {MAX_PAGES} pages')

    def timed(self, parts, name, read, *args):
        """OBSERVE-HTTP: one read and its seconds in parts (the observation's own time, said with it)."""
        began = self.clock()
        try:
            return read(*args)
        finally:
            parts[f'{name}_s'] = round(self.clock() - began, 3)

    def observe(self, db, asked, parts=None):
        owner, name = self.repo.split('/')
        at = f'/repos/{owner}/{name}'
        parts = {} if parts is None else parts
        pull = self.timed(parts, 'pull', self.api, f"{at}/pulls/{asked['pr']}")
        # OBSERVE-PARALLEL: the pull first (it names the base), the other four reads at once: one after the other they were
        # most of the 7.5 s `pr metadata` held #652's landing for, every check answered from the cache in 0.8 s
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as reads:
            commits = reads.submit(self.timed, parts, 'commits', self.pages, f"{at}/pulls/{asked['pr']}/commits", 'commits')
            comments = reads.submit(self.timed, parts, 'comments', self.pages, f"{at}/pulls/{asked['pr']}/comments", 'comments')
            # OBSERVATION-FILES: the PR's own file list, which commit_check reads when the base already holds the head (a
            # merged PR judged again) or no tree has it: #645, judged again after its landing, was refused for want of it
            files = reads.submit(self.timed, parts, 'files', self.pages, f"{at}/pulls/{asked['pr']}/files", 'files')
            # quoted as the lane's client quotes it (forge_origin_client.compare): the base's ref has a slash (#642: 404)
            compare = reads.submit(self.timed, parts, 'compare', self.api,
                                   f"{at}/compare/{quote(pull['base']['ref'], safe='')}...{asked['head']}")
            commits, comments, files, compare = commits.result(), comments.result(), files.result(), compare.result()
        branch = pull['head']['ref']
        pushes = self.timed(parts, 'pushes', lambda: pushes_of(
            db.rows(PUSHED, {'ref': json.dumps([{'ref': f'refs/heads/{branch}'}])}), self.repo, branch))
        parts['via'] = getattr(self.forge, 'via', None) or 'cli'
        return {'pull': pull, 'commits': commits, 'comments': comments, 'files': files, 'compare': compare, 'pushes': pushes}

    def step(self, db):
        """Each asked observation, taken once and read; answers how many were observed."""
        observed = 0
        for (payload,) in db.rows(OPEN, {'asked_s': ASKED_S}):
            asked = json.loads(payload) if isinstance(payload, str) else payload
            if not say(db, asked['id'], 'taken', 'tower-service'):
                continue  # another live service took it
            began, parts = self.clock(), {}
            try:
                observation = self.observe(db, asked, parts)
            except Exception as error:  # noqa: BLE001 - said; the gate stops on it, fail closed
                say(db, asked['id'], 'failed', 'tower-service', why=f'{type(error).__name__}: {error}'[:300])
                LOG.warning('observations: PR #%s not observed: %s', asked.get('pr'), error)
                continue
            say(db, asked['id'], 'observed', 'tower-service', pr=asked['pr'], head=asked['head'],
                observation=observation, read_s=round(self.clock() - began, 3), parts=parts)
            observed += 1
        return observed


def start(scope, stop, wait, forge, active=None):
    """The look in a daemon thread, woken by tower_deploy (an asked observation notifies it)."""
    import threading
    observer = Observer(forge)

    def loop():
        while not stop.is_set():
            if active is None or active():
                try:
                    with scope() as db:
                        observer.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('observations: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='observations', daemon=True)
    thread.start()
    return thread
