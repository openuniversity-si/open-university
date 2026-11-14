"""Cursor Origin's forge port adapter (D-283).

The injected client owns CLI transport and API mappings. The journal (events and the forge.status trail) is the
git-ref log on Origin (D-300: never the Worker's /v1/events); merge and lease locks use conditional GitRefs advances.
Push history has no Origin route: pushes and force_pushes are answered from this clone's reflog of the branch's
remote-tracking ref, proven against Origin's head (forge_origin_history), or refused with the reason it cannot answer.
"""
from uuid import uuid4
import atexit
import fcntl
import os
import hashlib
from http import HTTPStatus
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

import config
import source_remote  # noqa: E402
from forge_origin_client import ACTOR_VARIANTS, VERDICT_APPROVE, VERDICT_BLOCK, OriginClientError, _redact
from forge_control import ControlAdapter, PortAdapter
import forge_events
from forge_events import Channel
from forge_git_ref import GitRefAdapter, GitRefs
import forge_origin_history
import release_policy


APPROVE, BLOCK = VERDICT_APPROVE, VERDICT_BLOCK
# The verdicts that decide a reviewer's standing. `comment` is not one of them: a reviewer who only
# commented has neither approved nor blocked, so their earlier decision still stands.
DECIDING_VERDICTS = (APPROVE, BLOCK)


class OriginAdapterError(RuntimeError):
    pass


def review_identity(review):
    """The review author's identity, or '' when the API sends none this can trust.

    An actor is one of the three variants the API documents. The user's `handle` is the identity a
    repository records -- it is the slug a lane and a unit owner are named by -- and it is published
    only while the author's profile is visible, so the user's `id` is the fallback. An app or a
    service account is named by its `id`: it has no handle, and its display name is prose.
    """
    actor = review.get('author')
    if not isinstance(actor, dict):
        return ''
    for variant in ACTOR_VARIANTS:
        found = actor.get(variant)
        if not isinstance(found, dict):
            continue
        if variant == ACTOR_VARIANTS[0]:
            return found.get('handle') or found.get('id') or ''
        return found.get('id') or ''
    return ''


def git_host(url):
    """The lowercased host a git remote URL names, or '' for a local path: https://host/o/n, ssh://user@host:port/o/n,
    and the scp form user@host:o/n. Credentials and the port are never part of the answer."""
    if '://' in url:
        return (urlsplit(url).hostname or '').lower()
    authority, colon, _ = url.partition(':')
    if not colon or '/' in authority:
        return ''
    _, _, host = authority.rpartition('@')
    return host.lower()


def on_github(url, repo):
    """GITHUB-SOURCE: whether `url` is `repo` on GitHub (the source of truth since 14/11/2026, D-314): asked of the GitHub
    adapter source_remote, so this Origin adapter never names another vendor's host."""
    return source_remote.on_github(url, repo, git_host)


def refuse_remote(url, repo):
    """Raise OriginAdapterError unless `url` is `repo` on a declared Origin git host. Merges and locks travel by git:
    a remote on another forge's host would carry them there (fail closed)."""
    hosts = config.get('origin-client.git_hosts')
    if not hosts:
        raise OriginAdapterError('no Origin git host declared: set origin-client.git_hosts')
    host = git_host(url)
    if host not in {item.lower() for item in hosts}:
        raise OriginAdapterError(f'{host or "a local path"}: git remote is not an Origin git host')
    # One git remote serves one repository (after the host's '/', or the scp form's ':'). Never push from another.
    path = url.removesuffix('.git').rstrip('/')
    if not any(path.endswith(mark + repo) for mark in '/:'):
        raise OriginAdapterError(f'{repo}: git remote belongs to another repository')


def credential_gaps(cached_probe, refs=None, client=None):
    """ORIGIN-FINISH R3: what this forge needs before the operation runs on it (preflight, when forge-events.adapter
    selects origin), as lines naming each gap, never a value: the origin CLI, a Cursor credential, a git remote on a
    declared Origin git host, and the API answering the credential's identity (cached like every credential probe)."""
    import forge_origin_client
    conf = forge_origin_client.settings()
    names = (config.get('origin-client.auth_token_env'), config.get('origin-client.credential_env'))
    gaps = []
    if not forge_origin_client.cli_binary(conf):
        gaps.append(f'missing {conf["cli"]} CLI (on PATH, or its path in ${conf["cli_env"]})')
    if not any(os.environ.get(name) for name in names):
        gaps.append(f'missing {" or ".join(names)}')
    try:
        url = (refs or GitRefs()).url()
        # GITHUB-SOURCE (14/11/2026): GitHub is the source of truth and Origin its mirror; a checkout whose origin is the
        # same repository on GitHub has no gap. refuse_remote still fails closed for the Origin operations that push
        if not on_github(url, config.get('forge-events.repo')):
            refuse_remote(url, config.get('forge-events.repo'))
    except (OriginAdapterError, RuntimeError) as error:
        gaps.append(f'Origin git remote: {error}')
    if gaps:
        return gaps

    def probe():
        try:
            return bool((client or forge_origin_client.client_from_config()).identity())
        except OriginClientError:
            return False
    return [] if cached_probe('origin', names, (), probe) else ['Origin API is not reachable']


class OriginAdapter:
    remote = True

    def __init__(self, client, repo, log=None, refs=None, checks=None):
        # F37 (D-299): `checks` posts the check run instead of the client (the control plane, holder of the app key)
        self.client, self.repo, self.checks = client, repo, checks
        self.refs = refs if refs is not None else GitRefs()
        self.log = log if log is not None else GitRefAdapter(refs=self.refs)  # D-300: the journal is on Origin
        refuse_remote(self.refs.url(), repo)

    def change(self, repo, number):
        """Client returns head/base SHAs, head_ref/base_ref, body, open, head_repo."""
        return dict(self.client.change(repo, number))

    def __getattr__(self, name):
        raise AttributeError(name)

    def pushes(self, repo, branch):
        """The branch's pushes, newest first, as {before, after, timestamp}: from this clone's reflog, or refused (see
        forge_origin_history): the reflog holds no record, or cannot prove it holds every move Origin saw."""
        return self._history(repo, branch, forced_only=False)

    def force_pushes(self, repo, branch):
        """The branch's forced pushes, newest first: the same answer as pushes, keeping only the forced moves."""
        return self._history(repo, branch, forced_only=True)

    def _history(self, repo, branch, forced_only):
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        try:  # a push landing between the two reads refuses (Origin's head is not the reflog's last): fail closed
            tip = self.refs.tip(branch)
            return forge_origin_history.reflog_history(self.refs.push_log(branch), f'refs/heads/{branch}', tip,
                                                       self.refs.is_ancestor, forced_only)
        except forge_origin_history.HistoryGap as gap:
            raise OriginAdapterError(str(gap)) from None

    def change_commits(self, repo, number):
        return self.client.change_commits(repo, number)

    def closed_changes(self, repo, since=None):
        return self.client.closed_changes(repo, since)

    def change_files(self, repo, number):
        return self.client.change_files(repo, number)

    def commit_files(self, repo, sha):
        return self.client.commit_files(repo, sha)

    def compare(self, repo, base, head):
        return self.client.compare(repo, base, head)

    def find_change(self, repo, head_ref):
        return self.client.find_change(repo, head_ref)

    def open_change(self, repo, head_ref, base_ref, title, body):
        return self.client.open_change(repo, head_ref, base_ref, title, body)

    def close_change(self, repo, number):
        self.client.close_change(repo, number)

    def calls(self):
        stats = getattr(self.client, 'stats', None)
        if stats is None:
            raise OriginAdapterError('the OriginAdapter has no calls operation: injected client has no request counter')
        return dict(stats)

    def lock(self, repo, name, owner, now, expires):
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        held = self.refs.read(name)
        if held is None:
            return self.refs.advance(name, {'owner': owner, 'expires': expires}, None)
        sha, holder = held
        if holder.get('owner') != owner and holder.get('expires', '') > now:
            return False
        return self.refs.advance(name, {'owner': owner, 'expires': expires}, sha)

    def unlock(self, repo, name, owner, died=None):
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        held = self.refs.read(name)
        if held and held[1].get('owner') == owner and held[1].get('expires'):
            record = {'owner': owner, 'expires': ''}
            if died:
                record['died'] = died  # TRAIN-TEMP-FIX R1: why the run that held the lock ended
            self.refs.advance(name, record, held[0])

    def open_pulls(self, repo, base=None):
        return self.client.open_pulls(repo, base)

    def pull(self, repo, number):
        pull = self.client.pull(repo, number)
        return {'number': int(pull['number']), 'title': pull.get('title') or '',
                'body': pull.get('body') or '',
                'state': 'merged' if pull.get('merged') else pull.get('state'),
                'head_ref': pull['head']['ref'], 'head_sha': pull['head']['sha'],
                'base_ref': pull['base']['ref'],
                'merge_sha': pull.get('mergeCommitSha') if pull.get('merged') else None,
                'created_at': pull.get('createdAt'), 'draft': bool(pull.get('draft'))}

    def comment(self, repo, number, body):
        self.client.append_comment(repo, number, body)

    def comments(self, repo, number):
        # Origin provides no repository association: never manufacture owner authority.
        return [{'body': item.get('body') or '', 'created_at': item.get('createdAt'),
                 'author_association': None} for item in self.client.comments(repo, number)]

    def upsert_comment(self, repo, number, first_line, body, comment_id=None, pages=1,
                       timeout=None, max_wait_s=None):
        """Edit the newest exact marker, or create. Only a missing id permits replacement.

        Origin has forward cursors, so finding the newest marker requires every page;
        `pages` is the GitHub backward-window hint and does not truncate this read.
        The local lock serializes find/create across this machine's gate processes.
        There is no client rate-budget wait; max_wait_s=0 also refuses a busy lock.
        """
        key = hashlib.sha256(f'origin:{repo}:{number}'.encode()).hexdigest()
        path = Path(tempfile.gettempdir()) / f'tower-origin-comment-{key}.lock'
        with path.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if max_wait_s == 0 else 0))
            previous = None
            if comment_id is None:
                found = next((item for item in reversed(self.client.comments(repo, number, timeout=timeout))
                              if (item.get('body') or '').split('\n', 1)[0] == first_line), None)
                if found:
                    comment_id, previous = found['id'], found.get('body') or ''
            rendered = _redact(body(previous) if callable(body) else body)
            if comment_id is not None:
                try:
                    self.client.edit_comment(repo, comment_id, rendered, timeout=timeout)
                    return comment_id
                except OriginClientError as error:
                    if error.status != HTTPStatus.NOT_FOUND:
                        raise
            return self.client.append_comment(repo, number, rendered, timeout=timeout)['id']

    def open_changes(self, repo, number_base):
        """The numbers of the open, non-draft changes that target `number_base` (the train's queue)."""
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        return [int(number) for number in self.client.open_changes(repo, number_base)]

    def approvals(self, repo, number):
        """Identities whose latest review of the change approves it: the ownership check's answer.

        The same reading as the GitHub adapter's, over Origin's own spellings. A review's verdict is
        `approve`, `request_changes` or `comment` (measured: they are not GitHub's APPROVED and
        CHANGES_REQUESTED), and only a review that decides a verdict sets a reviewer's standing -- a plain
        `comment` leaves it where it was, exactly as `COMMENTED` does on GitHub. A review carrying a
        `dismissal` decides nothing, whatever its verdict, because Origin keeps a dismissed review in the
        listing. The latest deciding review per author wins, so a later request_changes clears an earlier
        approval. An author with no readable identity cannot be counted as an approver.
        """
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        latest = {}
        for review in self.client.reviews(repo, number):
            author = review_identity(review)
            verdict = (review.get('verdict') or '').lower()
            if not author or review.get('dismissal'):
                continue
            if verdict in DECIDING_VERDICTS:
                latest[author] = verdict
        return sorted(author for author, verdict in latest.items() if verdict == APPROVE)

    def identity(self):
        identity = self.client.identity()
        if not isinstance(identity, str) or not identity.strip():
            raise OriginAdapterError('Origin client returned no identity')
        return identity

    def append(self, channel, envelopes):
        return self.log.append(channel, envelopes)

    def read(self, channel):
        return self.log.read(channel)

    @staticmethod
    def status_channel(repo):
        return Channel(f'{repo}:statuses', None)

    def set_status(self, repo, sha, context, state, description, url=None, landing=False):
        """CHECK-IN-LANDING: with landing and the port posting the check run (PortAdapter), the body comes back for the
        landing job to post right before its merge (forge.OriginForge.check), its trail asked as a publish's is; else it
        is published here and None comes back."""
        def trail():
            self.log.append(self.status_channel(repo), [{
                'event_id': str(uuid4()), 'type': 'forge.status',
                'payload': {'repo': repo, 'sha': sha, 'context': context, 'state': state,
                            'description': description, 'url': url, 'identity': self.identity()}}])
        # The journal is the trail. The check run is the verdict Origin shows on the commit.
        # A client that cannot post one (the contract's first double) leaves only the trail.
        if self.checks is not None:  # F37: the body is Origin's; the control plane posts it with the app's token
            import forge_origin_client
            body = forge_origin_client.check_run_body(sha, context, state, description, url)
            if landing and getattr(self.checks, 'lands', False):
                aside(trail)
                return body
            self.checks.check_run(repo, body)
            # STATUS-TRAIL-ASIDE: the trail after the verdict and beside what follows it: the journal's append (a git push
            # to its ref) and the identity (a CLI call) were 12.4 of the 13.5 s of a publish, before the check run, and
            # the landing is made once the success is published (the gate of #628: 18 s from its last check to it)
            aside(trail)
            return
        trail()
        publish = getattr(self.client, 'publish_check_run', None)
        if publish is not None:
            publish(repo, sha, context, state, description, url)

    def merge(self, repo, number, head_sha):
        if repo != self.repo:
            raise OriginAdapterError(f'{repo}: git remote belongs to another repository')
        change = self.change(repo, number)
        if change['head'] != head_sha or not change['open']:
            raise OriginAdapterError('merge requires the open change at the judged head')
        if change['head_repo'] != repo:
            raise OriginAdapterError('merge of a fork requires a local head ref')
        base, head = change['base_ref'], change['head_ref']
        if not base or not head:
            raise OriginAdapterError('merge requires base_ref and head_ref')
        release_policy.refuse_merge(base, head, self.refs.url())
        merged = self.refs.merge(base, head, head_sha, f'Merge change #{number} from {head}\n')
        if not merged:
            raise OriginAdapterError('merge lost the race to advance the base')
        return merged


class ObservedAdapter(OriginAdapter):
    """PR-OBSERVATION (docs/operations/aws.md 22.9): the Origin adapter over the answers the live service read of one PR
    with the forge's key (GET /v1/pr-observation): the same mapping of Origin's pull, commits, comments and comparison,
    replayed, and the head branch's pushes as the log has them. No credential, no clone: `pr metadata` off the lane's
    login and reflog. A read the observation does not hold (another PR, another comparison, a file list) refuses."""

    def __init__(self, observation, repo):
        import forge_origin_client
        self.observation, self.repo, self.checks, self.refs, self.log = observation, repo, None, None, None
        self.client = forge_origin_client.OriginClient(run=self.replay)

    def replay(self, method, path, body=None):
        seen, bare = self.observation, path.split('?')[0]
        pull = seen['pull']
        at = f'/repos/{self.repo}/pulls/{pull["number"]}'
        if method == 'GET' and bare == at:
            return pull
        if method == 'GET' and bare in (f'{at}/commits', f'{at}/comments', f'{at}/files') and bare.rsplit('/', 1)[1] in seen:
            key = bare.rsplit('/', 1)[1]  # OBSERVATION-FILES: an observation from before it holds no files: refused below
            return {key: seen[key]}
        if method == 'GET' and bare.startswith(f'/repos/{self.repo}/compare/') and bare.endswith(f'...{seen["head"]}'):
            return seen['compare']
        raise OriginClientError(f'origin: the observation of PR #{pull["number"]} holds no {method} {bare}')

    def pushes(self, repo, branch):
        if repo != self.repo or branch != self.observation['pull']['head']['ref']:
            raise OriginAdapterError(f'{repo} {branch}: the observation holds the pushes of its own head branch only')
        return [{'before': each['before'], 'after': each['after'], 'timestamp': each['timestamp']}
                for each in self.observation['pushes']]

    def force_pushes(self, repo, branch):
        forced = {(each['before'], each['after']) for each in self.observation['pushes'] if each.get('forced')}
        return [each for each in self.pushes(repo, branch) if (each['before'], each['after']) in forced]


TRAILS = []  # STATUS-TRAIL-ASIDE: the trails being written, each waited for before the process ends


def aside(write):
    """write() in a thread of its own; a failure is said on stderr (a trail is no verdict). The process waits for every
    one before it ends (atexit), so none is lost to a delivery that ended first. While the port holds the trails
    (forge_events.trails_held, TRAIL-AFTER-LANDING) it is only kept, and written when the hold ends."""
    import threading
    if forge_events.kept_aside(lambda: aside(write)):
        return None

    def run():
        try:
            write()
        except Exception as error:  # noqa: BLE001
            print(f'forge: the status trail was not written ({type(error).__name__}: {error})', file=sys.stderr, flush=True)
    thread = threading.Thread(target=run, name='status-trail', daemon=True)
    TRAILS.append(thread)
    thread.start()
    return thread


@atexit.register
def wait_for_trails(timeout_s=120.0):
    for thread in list(TRAILS):
        thread.join(timeout_s)


def adapter_from_config():
    """The adapter the port builds when forge-events.adapter is origin. The client comes from the registry, and
    forge-events.check_run_publisher chooses who posts the check run: the client, or the control plane (F37, D-299)."""
    import forge_origin_client
    publisher = config.get('forge-events.check_run_publisher')
    checks = ControlAdapter() if publisher == 'control' else PortAdapter() if publisher == 'port' else None  # CHECK-RUN-AWS
    return OriginAdapter(forge_origin_client.client_from_config(), config.get('forge-events.repo'), checks=checks)
