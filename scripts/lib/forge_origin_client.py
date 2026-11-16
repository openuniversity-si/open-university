"""The real Cursor Origin client behind forge_origin.OriginAdapter (FORGE-PORT, CANALE8).

The adapter takes its client injected; this is the client that talks to the live Origin public
API. It maps pull metadata, lifecycle, commits, reviews and comments onto the port,
with pagination and request counters. The adapter uses git for merge and locks;
the guarded API merge helper remains available to client callers.

Transport: the `origin` CLI, not urllib. This is not a preference, it is the only path that works.
`CURSOR_API_KEY` is a `crsr_` personal user key and the API refuses it as a Bearer token: a direct
GET of /rate_limit with `Authorization: Bearer $CURSOR_API_KEY` answers 401. The key must be
exchanged for a short-lived user token, and the official OpenAPI 3.1 spec (120 operations)
documents no exchange operation -- the exchange lives inside the `origin` CLI and inside Cursor's
own host. The CLI is therefore the transport, and it is invoked with
`--input -` so a request body travels on stdin and never on the command line, and so the credential
is never an argv element: the key stays in the environment the CLI already reads.

Auth: read from the environment the process inherits (`CURSOR_API_KEY`, or `CURSOR_AUTH_TOKEN`,
which the CLI prefers). This module never reads the value, never passes it as an argument, and never
prints or logs it; any credential-shaped string is redacted out of an error before it is raised.

Identity: Origin publishes no user endpoint. `/user`, `/me`, `/viewer` and `/whoami` all answer
404, and no operation in the spec returns the calling principal. The identity this client reports
is the one the API itself attests: the `user`-type namespace that `GET /namespaces` returns for the
caller's own account. Because that is a namespace and not a user record, it is reported as a gap
(`OriginIdentityGap`) rather than guessed at whenever the answer is not exactly one such namespace.
`auth status` is deliberately not used: it reports an account for a key the API rejects with 401, so
it is local state, not an attestation.

Every path, field and body here comes from the official spec; nothing is invented. Every value an
engine may tune is a registry entry of owner `origin-client` (D-068, LT1), read with config.get, so
no status, page size, timeout or method name is spelled in this file.
"""
from datetime import datetime

import json
import os
import re
import shutil
import subprocess
from datetime import timezone
from urllib.parse import quote

import config
import operation_demands

SETTINGS = ('cli', 'cli_env', 'cli_dirs', 'timeout_s', 'page_size', 'max_pages', 'message_max_chars',
            'statuses', 'merge_methods', 'user_namespace_type', 'sha_chars')
SECRET = re.compile(r'crsr_[A-Za-z0-9_\-]+')
HTTP_STATUS = re.compile(r'HTTP (\d{3})')
OWNER = 'owner'
NAME = 'name'
STATE_OPEN = 'open'
# The review's verdict values, as the API reference spells them. They are not GitHub's: an approval is
# `approve`, not `APPROVED`, and a block is `request_changes`, not `CHANGES_REQUESTED`.
VERDICT_APPROVE, VERDICT_BLOCK = 'approve', 'request_changes'
# A review's author is one of three actor variants. The approval's identity is the user's handle.
ACTOR_VARIANTS = ('user', 'app', 'serviceAccount')


class OriginClientError(RuntimeError):
    """An Origin API call failed. `status` is the HTTP status when the API answered, else None."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class OriginIdentityGap(OriginClientError):
    """No operation on the Origin public API returns the calling user's identity."""


def settings(root=None):
    """The client's registry values, read once (config validates any stored override)."""
    return {key: config.get(f'origin-client.{key}', root) for key in SETTINGS}


def cli_binary(conf=None):
    """The Origin CLI to run: the path pinned in $<cli_env>, else the CLI on PATH, else the first executable one in
    origin-client.cli_dirs (F81: a lane no longer exports PATH=~/.local/bin first). None when there is none."""
    conf = conf if conf is not None else settings()
    found = os.environ.get(conf['cli_env']) or shutil.which(conf['cli'])
    for folder in ([] if found else conf.get('cli_dirs', ())):
        candidate = os.path.join(os.path.expanduser(folder), conf['cli'])
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return found


def client_from_config():
    """The client the port builds when forge-events.adapter is origin."""
    return OriginClient()


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _redact(text):
    return SECRET.sub('<redacted>', str(text))


def _split(repo):
    """`owner/name`, as the adapter's repo string and Origin's two path segments."""
    owner, _, name = str(repo).partition('/')
    if not owner or not name or '/' in name or not re.fullmatch(r'[\w.-]+', owner + name):
        raise OriginClientError(f'{repo}: a repository must be owner/name')
    return {OWNER: owner, NAME: name}


def _message(stderr, limit):
    """The API's own one-line message from the CLI's stderr, without the body it rides in.

    The CLI prints the error envelope as JSON on stderr and the status on its last line. Only the
    envelope's `message` is kept: it is the sentence that names the failure ("Origin pull request
    not found"), it is what makes an error actionable, and it is never the response body.
    """
    for line in reversed(str(stderr).splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict) and isinstance(found.get('message'), str):
                return _redact(found['message'])[:limit]
    return ''


def _run_cli(method, path, body, binary, conf):
    """One `origin api` call: JSON object out, OriginClientError out, never a credential in argv."""
    argv = [binary, 'api', path, '-X', str(method).upper()]
    stdin = None
    if body is not None:
        stdin = json.dumps(body)
        argv += ['--input', '-']
    timeout = conf['timeout_s']
    try:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise OriginClientError(f'origin CLI not found at {binary}; set {conf["cli_env"]} or install it') from None
    except subprocess.TimeoutExpired:
        raise OriginClientError(f'origin: timeout; the Origin API did not answer in {timeout}s') from None
    if done.returncode != 0:
        found = HTTP_STATUS.search(done.stderr or '')
        status = int(found.group(1)) if found else None
        kind = (dict((int(item['status']), item['kind']) for item in conf['statuses']).get(status, 'http')
                if status else 'cli')
        detail = _message(done.stderr, conf['message_max_chars'])
        raise OriginClientError(
            f'origin: exit {status or 1} ({kind}); Origin API request failed'
            + (f': {detail}' if detail else ''), status=status)
    raw = (done.stdout or '').strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        raise OriginClientError('origin: response was not JSON (payload withheld)') from None
    if not isinstance(payload, dict):
        raise OriginClientError('origin: expected a JSON object (payload withheld)')
    return payload


def check_run_body(sha, context, state, description, url=None, limit=None):
    """The body of POST /repos/{owner}/{name}/check-runs for one gate status: the status map and the suite are
    forge-events.origin_* . The client posts it with its own credential; the control plane posts the same body with the
    Origin app's installation token (F37, D-299)."""
    mapped = next((item for item in config.get('forge-events.origin_status_map') if item.get('state') == state), None)
    if not mapped:
        raise OriginClientError(f'no Origin check-run mapping for status {state}')
    when = _stamp()
    limit = limit or config.get('origin-client.message_max_chars')
    text = description or ''
    run = {'key': context, 'name': context, 'status': mapped['status'], 'externalUpdatedAt': when,
           'externalId': context, 'output': {'title': text[:limit], 'summary': text}}
    if mapped.get('conclusion'):
        run['conclusion'] = mapped['conclusion']
        run['completedAt'] = when
    suite = {'key': config.get('forge-events.origin_check_suite_key'),
             'name': config.get('forge-events.origin_check_suite_name'), 'externalId': context}
    if url:
        run['detailsUrl'] = url
        suite['detailsUrl'] = url
    return {'headSha': sha, 'checkSuite': suite, 'checkRun': run}


def shape_change(pull, repo):
    """The adapter's port-shaped change from Origin's PullRequest.

    `head_repo` is always `repo`: Origin's PullRequestRef carries only `ref` and `sha` (no
    repository), it has no cross-repository or fork pull request, and CreatePullRequestRequest
    takes `head` and `base` as branch names that "must resolve in the repo at call time". A change
    therefore never comes from another repository, and the adapter's fork guard is satisfied
    truthfully rather than by assuming a field the API does not send.
    """
    head = pull.get('head') if isinstance(pull.get('head'), dict) else {}
    base = pull.get('base') if isinstance(pull.get('base'), dict) else {}
    merged = bool(pull.get('merged'))
    return {
        'head': head.get('sha') or '',
        'base': base.get('sha') or '',
        'head_ref': head.get('ref') or '',
        'base_ref': base.get('ref') or '',
        'head_repo': repo,
        'body': pull.get('body') or '',
        'open': str(pull.get('state') or '').lower() == 'open' and not merged,
    }


class OriginClient:
    """The Origin public API, as forge_origin.OriginAdapter expects its injected client.

    `run(method, path, body)` is the transport; it defaults to the `origin` CLI and a test passes
    its own. Nothing else in this class touches the network, so the mapping, the pagination and the
    error semantics are testable without one.
    """

    def __init__(self, run=None, conf=None, binary=None, root=None):
        self.conf = conf if conf is not None else settings(root)
        self.binary = binary
        self._run = run
        self.stats = {'sent': 0, 'not_modified': 0}

    def _cli(self, method, path, body=None, timeout=None):
        conf = dict(self.conf)
        if timeout is not None:
            conf['timeout_s'] = timeout
        binary = self.binary or cli_binary(conf)
        if not binary:
            raise OriginClientError(f'origin CLI not found on PATH; set {conf["cli_env"]} to its path')
        return _run_cli(method, path, body, binary, conf)

    def _call(self, method, path, body=None, timeout=None):
        # Attempts include errors; the CLI has no conditional GET/304 transport.
        self.stats['sent'] += 1
        try:
            if self._run is None:
                return self._cli(method, path, body, timeout=timeout)
            return self._run(method, path, body)
        except OriginClientError:
            raise
        except (OSError, ValueError) as error:  # a transport that fails below the CLI's own contract
            raise OriginClientError(_redact(f'origin: transport failed ({type(error).__name__})')) from None

    def pull(self, repo, number):
        """GET /repos/{ownerSlug}/{repoName}/pulls/{pullNumber}: the PullRequest as the API sends it."""
        parts = _split(repo)
        return self._call('GET', f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}')

    def change(self, repo, number):
        """The adapter's `change`: head/base SHAs, head_ref/base_ref, body, open, head_repo."""
        return shape_change(self.pull(repo, number), repo)

    def change_commits(self, repo, number):
        parts = _split(repo)
        commits = self._pages(f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/commits', 'commits')
        if any(not isinstance((item.get('commit') or {}).get('message'), str) for item in commits):
            raise operation_demands.CompatibilityError(
                'operation change_commits, adapter origin: commit message is unavailable')
        return [{'sha': item['sha'], 'parents': [parent['sha'] for parent in item.get('parents', [])],
                 'message': item['commit']['message']} for item in commits]

    def closed_changes(self, repo, since=None):
        """Closed merged pulls in Origin's default creation-descending order, across cursor pages.

        The OpenAPI defines mergedSince as an inclusive merge-time bound and mergedAt as
        unset unless merged. Retain a local bound as well; transport evidence is not live server proof.
        """
        parts = _split(repo)
        path = f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls?state=closed'
        lower = datetime.fromisoformat(since.replace('Z', '+00:00')) if since is not None else None
        if since is not None:
            path += f'&mergedSince={quote(since, safe="")}'
        return [{'number': int(item['number']), 'body': item.get('body') or '', 'merged_at': item['mergedAt']}
                for item in self._pages(path, 'pullRequests')
                if item.get('merged') and item.get('mergedAt') and (lower is None or
                    datetime.fromisoformat(item['mergedAt'].replace('Z', '+00:00')) >= lower)]

    def change_files(self, repo, number):
        parts = _split(repo)
        return [{'filename': item['filename']} for item in self._pages(
            f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/files', 'files')]

    def commit_files(self, repo, sha):
        parts = _split(repo)
        return [{'filename': item['filename']} for item in self._pages(
            f'/repos/{parts[OWNER]}/{parts[NAME]}/commits/{quote(sha, safe="")}/files', 'files')]

    def compare(self, repo, base, head):
        parts = _split(repo)
        comparison = self._call('GET', f'/repos/{parts[OWNER]}/{parts[NAME]}/compare/'
                                f'{quote(base, safe="")}...{quote(head, safe="")}')
        return {'merge_base': comparison['mergeBaseCommit']['sha'], 'behind_by': comparison['behindBy']}

    def find_change(self, repo, head_ref):
        parts = _split(repo)
        # Filter locally as well: never select another branch if a server ignores head.
        pulls = self._pages(f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls?state=all', 'pullRequests')
        return max((int(pull['number']) for pull in pulls if pull['head']['ref'] == head_ref), default=None)

    def open_change(self, repo, head_ref, base_ref, title, body):
        parts = _split(repo)
        pull = self._call('POST', f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls',
                          {'head': head_ref, 'base': base_ref, 'title': title, 'body': body})
        return int(pull['number'])

    def close_change(self, repo, number):
        parts = _split(repo)
        self._call('PATCH', f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}', {'state': 'closed'})

    def open_pulls(self, repo, base=None):
        """All open heads, including drafts; base filtering is local across every page."""
        parts = _split(repo)
        return [{'number': int(pull['number']), 'head_ref': pull['head']['ref'],
                 'head_sha': pull['head']['sha'], 'draft': bool(pull.get('draft'))}
                for pull in self._pages(f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls?state={STATE_OPEN}',
                                        'pullRequests')
                if not base or (pull.get('base') or {}).get('ref') == base]

    def open_changes(self, repo, base):
        """The train excludes drafts from the locally base-filtered open heads."""
        return [pull['number'] for pull in self.open_pulls(repo, base) if not pull['draft']]

    def reviews(self, repo, number):
        """GET .../pulls/{pullNumber}/reviews, following nextPageToken: submitted reviews, oldest first."""
        parts = _split(repo)
        return self._pages(f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/reviews', 'reviews')

    def _pages(self, path, key, timeout=None):
        """Every page of a paged read, following the spec's opaque cursor; a truncated read raises.

        Pagination is `pageSize` plus `nextPageToken`, resent as `pageToken` until it comes back
        empty -- it is not a page number. A read still paginating at max_pages raises rather than
        returning a silently truncated list.
        """
        found, token = [], ''
        joiner = '&' if '?' in path else '?'  # a path that already asks a filter keeps it
        for _ in range(self.conf['max_pages']):
            page_token = f'&pageToken={quote(token, safe="")}' if token else ''
            payload = self._call('GET', f'{path}{joiner}pageSize={self.conf["page_size"]}{page_token}', timeout=timeout)
            batch = payload.get(key)
            if isinstance(batch, list):
                found.extend(batch)
            token = payload.get('nextPageToken') or ''
            if not token:
                return found
        raise OriginClientError(f'origin: the {key} read is truncated; it is still paginating at max_pages')

    def identity(self):
        """The caller's Origin identity: the `user`-type namespace of the credential.

        Origin has no user endpoint (the spec has no operation returning the calling principal), so
        this is the only identity the API attests. It is a namespace slug, not a user record: when
        the answer is not exactly one user-type namespace the gap is raised, never a guess.
        """
        wanted = self.conf['user_namespace_type']
        personal = []
        for item in self._pages('/namespaces', 'namespaces'):
            namespace = item.get('namespace') if isinstance(item, dict) else None
            if isinstance(namespace, dict) and namespace.get('type') == wanted and namespace.get('slug'):
                personal.append(namespace['slug'])
        if len(personal) != 1:
            raise OriginIdentityGap(
                'Origin exposes no user identity for a user credential: no operation on the public API '
                'returns the calling principal, so this client reads the user-type namespace from '
                f'GET /namespaces, and the credential returned {len(personal)}'
                + (f' ({", ".join(personal)})' if personal else ''))
        return personal[0]

    def comments(self, repo, number, timeout=None):
        """GET .../pulls/{pullNumber}/comments, following nextPageToken. Oldest first."""
        parts = _split(repo)
        return self._pages(f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/comments', 'comments', timeout=timeout)

    def append_comment(self, repo, number, body, timeout=None):
        """POST .../pulls/{pullNumber}/comments with a general-discussion comment.

        The spec's body is `{body, threadId?, inline?, file?, versionNumber?}`; without `threadId` or
        an anchor the comment opens a new general-discussion thread, which is what the port's
        channel storage would need. This adapter does not call it today: `append`/`read` stay on
        the control plane and `set_status` on its journal, as FORGE-PORT decided.
        """
        parts = _split(repo)
        if not isinstance(body, str) or not body.strip():
            raise OriginClientError('origin: a comment needs a non-empty body')
        return self._call('POST', f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/comments', {'body': body}, timeout=timeout)

    def edit_comment(self, repo, comment_id, body, timeout=None):
        """Update the stable Origin comment id; only a 404 permits an upsert to recreate it."""
        parts = _split(repo)
        return self._call('PATCH',
                          f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/comments/{quote(str(comment_id), safe="")}',
                          {'body': body}, timeout=timeout)

    def merge(self, repo, number, expected_head_sha, method=None):
        """POST .../pulls/{pullNumber}/merge with the race guard the adapter's `head_sha` maps onto.

        `expectedHeadSha` is the spec's guard: when the head has moved the API answers 409 ABORTED
        and merges nothing, so the judged head and the merged head cannot diverge. The adapter
        itself merges by pushing the tested merge commit (forge_git_ref) and does not call this;
        Origin additionally rejects a merge on a mirrored repository, which is what every Origin
        copy of this repository is today.
        """
        parts = _split(repo)
        lengths = self.conf['sha_chars']
        if not isinstance(expected_head_sha, str) or not (
                len(expected_head_sha) in lengths and re.fullmatch(r'[0-9a-f]+', expected_head_sha)):
            raise OriginClientError('origin: merge needs the full head SHA, not an abbreviation')
        body = {'expectedHeadSha': expected_head_sha}
        if method is not None:
            if method not in self.conf['merge_methods']:
                raise OriginClientError(f'origin: mergeMethod is one of {sorted(self.conf["merge_methods"])}')
            body['mergeMethod'] = method
        return self._call('POST', f'/repos/{parts[OWNER]}/{parts[NAME]}/pulls/{number}/merge', body)

    def rate_limit(self):
        """GET /rate_limit: the credential's budget. Free: it consumes none."""
        return self._call('GET', '/rate_limit')

    def publish_check_run(self, repo, sha, context, state, description, url=None):
        """POST /repos/{owner}/{name}/check-runs for the gate verdict.

        The adapter writes the journal first and then calls this. Check runs require an installation
        token (repository:checks:write). This method does not read the credential: a user key is
        refused by the API, and that refusal is the error. The status map and the suite name are
        forge-events.origin_* ; the transport is the same `origin api` call as every other method.
        """
        parts = _split(repo)
        body = check_run_body(sha, context, state, description, url, self.conf['message_max_chars'])
        posted = self._call('POST', f'/repos/{parts[OWNER]}/{parts[NAME]}/check-runs', body)
        if posted.get('outcome') == 'ignored_stale':
            raise OriginClientError('Origin ignored the check run as stale')
        return posted.get('outcome')
