"""BRANCH-MERGE (docs/operations/aws.md 22.9; item 3 of the Torre's order of 13/11: the delivery off the lane): the base
merged into a PR's branch and pushed by the live service, with the forge's key, not by the lane.

A delivery whose base moved merges the base into its branch (a merge commit, never a rebase: FP1) and pushes it, so the gate
judges what the landing merges (scripts/lib/deliver.py _with_base). The lane did it in its clone, with the box's login: a
credential and a clone of the lane on the path. Now:
  - POST /v1/branch-merge {branch, head, base} is one event, platform.forge.branch_merge {id, state: asked, ...}, and a
    NOTIFY of tower_deploy;
  - the live service's look (Merger) takes each asked one once and, in a clone of its own (no work of the slots), fetches
    the branch and the base by the forge's key, refuses a branch that moved from `head` (moved), answers `current` when
    the base is already in it, else merges the base with the lane's own message and pushes it (a fast-forward of the
    branch: never forced): merged {sha}, or conflict {paths} (the merge undone), or failed {why};
  - GET /v1/branch-merge/<id> answers the newest state.
"""
import json
import logging
from pathlib import Path
import re
import time

LOG = logging.getLogger('tower_infra.branches')
EVENT = 'platform.forge.branch_merge'
REPO = 'openuniversity-si/open-university'
SHA = re.compile(r'^[0-9a-f]{40}$')
BRANCH = re.compile(r'^units/[A-Za-z0-9._/-]{1,120}$')
BASE = re.compile(r'^[A-Za-z0-9._/-]{1,120}$')
ASKED_S = 600
SLOT = 'merge'  # the clone of this look, beside the runner's slots' names: container.Container(slot=SLOT)
IDENTITY = ('-c', 'user.name=tower-service', '-c', 'user.email=tower-service@users.noreply.cursor.com')

SAY = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"select %(event)s, null, '{EVENT}', clock_timestamp(), %(producer)s, 'forge/branch-merge', %(payload)s::jsonb "
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


def say(db, ident, state, producer, **more):
    return bool(db.rows(SAY, {'event': f'{EVENT}:{ident}:{state}', 'producer': producer,
                              'payload': json.dumps({'id': ident, 'state': state, **more})}))


def ask(db, who, body, clock=time.time_ns, configured=None):
    """POST /v1/branch-merge: the base merged into a unit's branch at `head`, asked of the live service."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    body = body or {}
    if not BRANCH.match(str(body.get('branch') or '')) or '..' in str(body.get('branch')) \
            or not SHA.match(str(body.get('head') or '')) or not BASE.match(str(body.get('base') or '')) \
            or '..' in str(body.get('base')):
        raise port.PortError(400, 'branch (units/...), head (40 hex) and base (a branch name) required')
    ident = str(clock())
    say(db, ident, 'asked', port.PRODUCER, branch=body['branch'], head=body['head'], base=body['base'])
    return {'id': ident, 'state': 'asked'}


def state(db, who, ident, configured=None):
    """GET /v1/branch-merge/<id>: its newest state (404 for none in a day)."""
    from . import canary, port
    (configured or canary.configured)(db, who)
    found = db.rows(NEWEST, {'id': str(ident)})
    if not found:
        raise port.PortError(404, 'no such branch merge')
    return json.loads(found[0][0]) if isinstance(found[0][0], str) else found[0][0]


def refused(error):
    """A git refusal of the box (container.Unprepared, by name: the port's Lambda imports this module, not container's)."""
    if type(error).__name__ != 'Unprepared':
        raise error


class Merger:
    """The live service's half: each asked merge done once in this look's own clone, with the forge's key."""

    def __init__(self, box, repo=REPO, clock=time.monotonic):
        self.box, self.repo, self.clock = box, repo, clock
        self.premerged = {}  # PREMERGE: each branch's newest premerge ref, deleted when the next is pushed
        self.made = {}  # MERGE-REUSE: (head, onto) -> the merge commit a premerge made, the very one the delivery pushes

    def clone(self):
        """BRANCH-MERGE-FAST (criterion 3: #672's delivery waited 71.2 s for the merge, a whole clone of the repository on the
        service's 0.25 vCPU): the look's clone is blobless (--filter=blob:none: the commits and trees, 14 MB, not 186), and
        the merge needs no work tree (merge-tree), so only the blobs both sides changed come, when they are asked."""
        box = self.box
        clone = box.checkout_of({'repo': self.repo})
        url = f'{box.forge_url}/{self.repo}.git'
        if not (clone / '.git').is_dir():
            clone.parent.mkdir(parents=True, exist_ok=True)
            box.git('clone', '--quiet', '--no-checkout', '--filter=blob:none', url, str(clone))
        box.git('remote', 'set-url', 'origin', url, cwd=clone)
        return clone

    def warm(self):
        """BRANCH-MERGE-FAST: the clone made before the first merge is asked (the live service's look, at its start)."""
        try:
            self.clone()
        except Exception as error:  # noqa: BLE001 - a merge asked later makes it then
            LOG.warning('branches: the clone was not made ahead: %s', error)

    def combine(self, clone, branch, base, head, onto):
        """The merge of `onto` (the base's tip) into `head`: ('merged', sha) or ('conflict', paths). PREMERGE: the same
        commit whenever it is made, for the same head and base (its dates the base's commit's, its committer the service):
        the pre-gate's merge, made when the base moved, is the very commit the delivery's merge pushes later, so the
        delivery finds its plan and its checks done."""
        self.attributes(clone, onto)
        try:  # the merge's tree, with no work tree: the blobs both sides changed only
            tree = self.box.git('merge-tree', '--write-tree', '--name-only', '--no-messages', head, onto, cwd=clone).split()[0]
        except Exception as error:  # noqa: BLE001 - container.Unprepared: a conflict (exit 1): its paths, nothing written
            refused(error)
            said = str(error).split(':', 1)[-1].split()
            at = next((n for n, each in enumerate(said) if SHA.match(each)), None)  # the tree's line, then the paths
            return 'conflict', {'paths': (said[at + 1:] if at is not None else [])[:50]}
        when = '@' + self.box.git('show', '-s', '--format=%ct', onto, cwd=clone).strip() + ' +0000'
        merged = self.box.git(*IDENTITY, 'commit-tree', tree, '-p', head, '-p', onto, '-m', f'Merge origin/{base} into {branch}',
                              cwd=clone, env={'GIT_AUTHOR_DATE': when, 'GIT_COMMITTER_DATE': when}).strip()
        return 'merged', {'sha': merged}

    def attributes(self, clone, onto):
        """MERGE-UNION: the base's .gitattributes as the clone's info/attributes. The clone has no work tree (--no-checkout),
        so merge-tree read no .gitattributes and merged docs/operations/aws-pendencias.md (merge=union) as any file: two
        PRs that each touched the board conflicted at the service (#692 behind #691, 13/11 21:30 UTC: no premerge, and the
        delivery refused) where git merge in a checkout merges them. info/attributes is read with or without a work tree."""
        try:
            text = self.box.git('show', f'{onto}:.gitattributes', cwd=clone)
        except Exception as error:  # noqa: BLE001 - container.Unprepared: a base without the file, none
            refused(error)
            text = ''
        where = Path(clone) / '.git' / 'info'
        where.mkdir(parents=True, exist_ok=True)
        (where / 'attributes').write_text(text.rstrip('\n') + '\n' if text.strip() else '', encoding='utf-8')

    def fetched(self, clone, branch, base):
        self.box.git('fetch', '--quiet', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/remotes/origin/{branch}',
                     f'+refs/heads/{base}:refs/remotes/origin/{base}', cwd=clone)
        return (self.box.git('rev-parse', f'refs/remotes/origin/{branch}', cwd=clone).strip(),
                self.box.git('rev-parse', f'refs/remotes/origin/{base}', cwd=clone).strip())

    def contains(self, clone, older, newer):
        try:
            self.box.git('merge-base', '--is-ancestor', older, newer, cwd=clone)
            return True
        except Exception as error:  # noqa: BLE001 - container.Unprepared: it does not
            refused(error)
            return False

    def merge(self, asked):
        """The delivery's merge. MERGE-REUSE (criterion 3): #690 and #692 waited 19.4 and 20.5 s for it, though a premerge
        had made the same commit minutes before (its dates the base's: the same head and base give the same sha); that commit
        is pushed as it is, and each step's seconds are said (fetch_s, combine_s, push_s, reused)."""
        box, branch, base, head = self.box, asked['branch'], asked['base'], asked['head']
        began = self.clock()
        clone = self.clone()
        tip, onto = self.fetched(clone, branch, base)
        parts = {'fetch_s': round(self.clock() - began, 3)}
        if tip != head:
            return 'moved', {'tip': tip}
        if self.contains(clone, onto, head):
            return 'current', {'sha': head}
        made, at = self.made.get((head, onto)), self.clock()
        if made:
            outcome, said = 'merged', {'sha': made}
        else:
            outcome, said = self.combine(clone, branch, base, head, onto)
        parts.update(combine_s=round(self.clock() - at, 3), reused=bool(made))
        if outcome != 'merged':
            return outcome, {**said, **parts}
        at = self.clock()
        box.git('push', '--quiet', 'origin', f"{said['sha']}:refs/heads/{branch}", cwd=clone)  # a fast-forward: never forced
        parts['push_s'] = round(self.clock() - at, 3)
        return 'merged', {**said, **parts}

    def premerge(self, asked):
        """PREMERGE (the Torre's choice of 13/11: the long work while the PR is authored, never on its branch): the base
        that moved merged into a unit's head and pushed to a ref of its own, premerge/<branch>/<base12>, for the pre-gate
        to plan and run the combination; the PR's branch is not touched. The branch's previous premerge ref is deleted
        (never forced: a new ref each base)."""
        box, branch, base, head = self.box, asked['branch'], asked['base'], asked['head']
        clone = self.clone()
        tip, onto = self.fetched(clone, branch, base)
        if tip != head:
            return 'moved', {'tip': tip}
        if self.contains(clone, head, onto):
            return 'landed', {'onto': onto}
        if self.contains(clone, onto, head):
            return 'current', {'sha': head, 'onto': onto}
        outcome, said = self.combine(clone, branch, base, head, onto)
        if outcome != 'merged':
            return outcome, said
        ref = f'premerge/{branch}/{onto[:12]}'
        box.git('push', '--quiet', 'origin', f"{said['sha']}:refs/heads/{ref}", cwd=clone)
        old = self.premerged.get(branch)
        if old and old != ref:
            try:
                box.git('push', '--quiet', 'origin', f':refs/heads/{old}', cwd=clone)
            except Exception as error:  # noqa: BLE001 - a stale ref left: a later premerge of the branch tries again
                refused(error)
                LOG.warning('branches: %s not deleted: %s', old, error)
        self.premerged[branch] = ref
        self.made = {key: sha for key, sha in self.made.items() if key[0] != head} | {(head, onto): said['sha']}
        return 'premerged', {'sha': said['sha'], 'ref': ref, 'onto': onto, 'head': head}

    def step(self, db):
        """Each asked merge, taken once and done; answers how many ended."""
        done = 0
        for (payload,) in db.rows(OPEN, {'asked_s': ASKED_S}):
            asked = json.loads(payload) if isinstance(payload, str) else payload
            if not say(db, asked['id'], 'taken', 'tower-service'):
                continue
            began = self.clock()
            try:
                outcome, more = (self.premerge if asked.get('premerge') else self.merge)(asked)
            except Exception as error:  # noqa: BLE001 - said; the delivery merges it itself then
                say(db, asked['id'], 'failed', 'tower-service', why=f'{type(error).__name__}: {error}'[:300])
                LOG.warning('branches: %s not merged: %s', asked.get('branch'), error)
                continue
            say(db, asked['id'], outcome, 'tower-service', branch=asked['branch'], merge_s=round(self.clock() - began, 3),
                **more)
            done += 1
        return done


def start(scope, stop, wait, box, active=None):
    import threading
    merger = Merger(box)

    def loop():
        warm = False
        while not stop.is_set():
            if active is None or active():
                if not warm:  # BRANCH-MERGE-FAST: the clone before the first merge is asked
                    merger.warm()
                    warm = True
                try:
                    with scope() as db:
                        merger.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('branches: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='branches', daemon=True)
    thread.start()
    return thread
