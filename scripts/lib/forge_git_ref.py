"""Lock refs over the git protocol (GX-FIX-train-lock, D-070): the one way the engine writes a ref on the forge.

The Claude Code egress proxy refuses every REST git-data write (git/trees, git/commits, git/refs) and every ref delete,
and permits creating and fast-forwarding refs/heads/* over the git protocol (docs/units/GX-FIX-train-lock/audit.md).
So a lock ref only ever moves forward, and only through `git push` without force:

create   push of a new ref: the server refuses it when the ref already exists (a rival created it first).
advance  push of a child of the sha read: the server refuses it when the ref moved since (not a fast-forward).
append   advance from a fresh read of the tip, a bounded number of times: a log ref (train.wake_ref, GATE-ON-PUSH R2)
         whose commit history is the log; tip (ls-remote) and log (fetch, then the records after a sha) read it.

There is no delete and no rewind: the proxy refuses the first, the pre-push policy (no_history_rewrite) the second. A
release is an advance to a record the caller marks free. The commit holds the record twice, as its message and as
record.json, both canonical JSON. The push result is read from --porcelain: a refused push may still exit 0.

A lost race is told by the ref, not by the server's wording (F29). A rival that creates or moves the ref between this
push's ref advertisement and its update is refused by the server, which words it as it likes: stock git says
`failed to update ref`, Origin says `reference already exists`. So a refusal that is not a known lost race reads the tip
once more: a ref that now exists or moved off the parent this push started from is a lost race, retried by append; a ref
still at that parent refused for another reason (a hook, a permission), which is an error.
"""
from collections import namedtuple
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

import config

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_FILE = 'record.json'
LOCAL_NAMESPACE = 'refs/forge-git-ref/'  # where a read keeps the fetched tip (local only, never pushed)
MISSING = "couldn't find remote ref"
# --porcelain reasons for a push the server or git refused because the ref exists or moved (another contender won).
LOST = ('[rejected]', 'cannot lock ref', 'failed to update ref', 'stale info')
# a refusal by the server itself, whatever its reason: a lost race only when the tip shows the ref moved (F29)
REMOTE_REJECTED = '[remote rejected]'


# One reflog line as git writes it: old sha, new sha, identity, unix seconds and zone, a tab, the message.
REFLOG_LINE = re.compile(r'^(?P<before>\S+) (?P<after>\S+) .* (?P<seconds>\d+) [+-]\d+\t(?P<message>.*)$')
Move = namedtuple('Move', 'before after seconds message')


class GitRefError(RuntimeError):
    pass


BACKOFF_BASE = 0.05  # seconds waited after the first lost attempt; doubles each loss
BACKOFF_CAP = 2.0  # seconds, the ceiling of one wait


def _backoff(lost):
    """Seconds to wait after the lost-th lost attempt: exponential from BACKOFF_BASE up to BACKOFF_CAP, with full jitter so
    contenders that lost together do not retry together."""
    return random.uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (lost - 1)))


def _last_line(text):
    lines = text.strip().splitlines()
    return lines[-1] if lines else ''


class GitRefs:
    """Records on refs/heads/<name> of one git remote, read and advanced with plain git."""

    def __init__(self, root=None, remote=None, timeout=None):
        self.root = Path(root or ROOT)
        self.remote = remote or config.get('train.git_remote')
        self.timeout = timeout or config.get('train.git_timeout_s')
        name, email = config.get('train.git_author_name'), config.get('train.git_author_email')
        self.identity = {'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email,
                         'GIT_COMMITTER_NAME': name, 'GIT_COMMITTER_EMAIL': email}

    def _git(self, *args, stdin=None, env=None):
        # input '' when there is none: a git command that reads stdin (mktree) must never wait on the caller's.
        return subprocess.run(['git', '-C', str(self.root), *args], input=stdin or '', capture_output=True, text=True,
                              timeout=self.timeout, env=dict(os.environ, **(env or {})))

    def _must(self, *args, stdin=None, env=None):
        done = self._git(*args, stdin=stdin, env=env)
        if done.returncode != 0:
            raise GitRefError(f'git {args[0]} failed: {_last_line(done.stderr)}')
        return done.stdout.strip()

    def url(self):
        return self._must('remote', 'get-url', self.remote)

    def read(self, name):
        """(sha, record) of refs/heads/<name> on the remote, or None when the ref does not exist."""
        local = f'{LOCAL_NAMESPACE}{name}'
        done = self._git('fetch', '--no-tags', '--quiet', self.remote, f'+refs/heads/{name}:{local}')
        if done.returncode != 0:
            if MISSING in done.stderr:
                return None
            raise GitRefError(f'git fetch {name} failed: {_last_line(done.stderr)}')
        sha = self._must('rev-parse', '--verify', f'{local}^{{commit}}')
        try:
            return sha, json.loads(self._must('show', '-s', '--format=%B', sha))
        except ValueError:
            raise GitRefError(f'refs/heads/{name} is not a record commit') from None

    def tip(self, name):
        """The sha refs/heads/<name> points at on the remote, or None when it does not exist: one `git ls-remote`, no
        fetch and no REST (what a waiter on a log ref polls)."""
        out = self._must('ls-remote', '--heads', self.remote, f'refs/heads/{name}')
        return out.split()[0] if out else None

    def push_log(self, branch):
        """[Move(before, after, unix seconds, message)] of refs/remotes/<remote>/<branch> in this clone's reflog, oldest
        first, or [] when it holds none (D-300: the push history Origin has no route for). Every lane's worktree and
        deliver share one .git, and git records each push of refs/heads/<branch> there as `update by push`, with the
        sha it replaced (40 zeros for the push that created the branch); a fetch that moved it is recorded as a fetch."""
        common = Path(self._must('rev-parse', '--git-common-dir'))
        path = (common if common.is_absolute() else self.root / common) / 'logs' / 'refs' / 'remotes' / self.remote / branch
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            found = REFLOG_LINE.match(line)
            if not found:
                raise GitRefError(f'{path.name}: a reflog line git did not write: {line!r}')
            entries.append(Move(found['before'], found['after'], int(found['seconds']), found['message']))
        return entries

    def is_ancestor(self, older, newer):
        """True when `older` is an ancestor of `newer`, False when not; None when this clone lacks either commit."""
        code = self._git('merge-base', '--is-ancestor', older, newer).returncode
        return {0: True, 1: False}.get(code)

    def log(self, name, since=None):
        """[(sha, record)] of refs/heads/<name> after `since` (exclusive; None: from its first commit), oldest first.
        A `since` the fetched tip does not descend from (an unknown sha) reads the whole log."""
        held = self.read(name)
        if held is None:
            return []
        local = f'{LOCAL_NAMESPACE}{name}'
        known = since and self._git('merge-base', '--is-ancestor', since, local).returncode == 0
        shas = self._must('rev-list', '--reverse', f'{since}..{local}' if known else local).split()
        try:
            return [(sha, json.loads(self._must('show', '-s', '--format=%B', sha))) for sha in shas]
        except ValueError:
            raise GitRefError(f'refs/heads/{name} holds a commit that is not a record') from None

    def _commit(self, record, parent):
        text = json.dumps(record, sort_keys=True)
        blob = self._must('hash-object', '-w', '--stdin', stdin=text)
        tree = self._must('mktree', stdin=f'100644 blob {blob}\t{RECORD_FILE}\n')
        parents = ['-p', parent] if parent else []
        # the message goes through stdin: as an argument it fails past MAX_ARG_STRLEN (128 KB), which a shared-results record reached
        return self._must('commit-tree', tree, *parents, stdin=text, env=self.identity)  # no -m, no -F: git reads the message from stdin

    def advance(self, name, record, parent):
        """Point refs/heads/<name> at a new commit holding record: create it when parent is None, else fast-forward it
        from parent. True when this push moved the ref; False when the server refused it because the ref exists or moved
        (another contender won); GitRefError for anything else, so a refused transport is never read as a lost race."""
        return self._push(name, self._commit(record, parent), parent)

    def _push(self, name, commit, parent):
        """True when the push of commit (a child of parent, None for a create) moved refs/heads/<name>; False when a rival
        won (the ref exists or moved); GitRefError otherwise."""
        target = f'refs/heads/{name}'
        done = self._git('push', '--porcelain', self.remote, f'{commit}:{target}')
        for line in done.stdout.splitlines():
            flag, _, rest = line.partition('\t')
            if rest.partition('\t')[0] != f'{commit}:{target}':
                continue
            if flag in ('*', ' '):
                return True
            if flag == '!' and any(reason in rest for reason in LOST):
                return False
            if flag == '!' and REMOTE_REJECTED in rest and self.tip(name) != parent:
                return False  # the server refused it, whatever its words, because a rival created or moved the ref
            raise GitRefError(f'git push {target}: {line.strip()} {_last_line(done.stderr)}')
        raise GitRefError(f'git push {target} gave no result (refused before the server?): {_last_line(done.stderr)}')

    def append(self, name, record, attempts):
        """Add record on top of refs/heads/<name> whatever it holds (a log, not a lock): each attempt reads the tip and
        fast-forwards from it, so a rival's record is kept, never overwritten. The sha of the new commit, or None when
        every attempt lost the race. A lost attempt waits (backoff with jitter) before the next, never after the last."""
        for lost in range(attempts):
            if lost:
                time.sleep(_backoff(lost))
            held = self.read(name)
            parent = held[0] if held else None
            commit = self._commit(record, parent)
            if self._push(name, commit, parent):
                return commit
        return None


    def merge(self, base, head_ref, head_sha, message):
        """FORGE-PORT (CANALE8): merge refs/heads/<head_ref> into refs/heads/<base> by pushing the merge commit, with no forge
        API (the vendor-independent merge of the port). The head must still be head_sha (as a merge that matches the head
        commit); the merge is computed by `git merge-tree` and a conflict refuses it; the push is a fast-forward of the base
        from the tip read, so a base that moved meanwhile is a lost race (None), never a force push. Returns the merge sha."""
        base_held, head_held = self.read_tip(base), self.read_tip(head_ref)
        if base_held is None or head_held is None:
            raise GitRefError(f'merge: refs/heads/{base if base_held is None else head_ref} does not exist')
        if head_held != head_sha:
            raise GitRefError(f'merge: refs/heads/{head_ref} is {head_held[:12]}, not the head {head_sha[:12]} that was judged')
        merged = self._git('merge-tree', '--write-tree', base_held, head_held)
        if merged.returncode != 0:
            raise GitRefError(f'merge: {head_ref} does not merge cleanly into {base}: {_last_line(merged.stdout)}')
        tree = merged.stdout.split()[0]
        commit = self._must('commit-tree', tree, '-p', base_held, '-p', head_held, stdin=message, env=self.identity)
        return commit if self._push(base, commit, base_held) else None

    def read_tip(self, name):
        """The sha of refs/heads/<name> on the remote, fetched into this clone (its objects are then local), or None."""
        local = f'{LOCAL_NAMESPACE}{name}'
        done = self._git('fetch', '--no-tags', '--quiet', self.remote, f'+refs/heads/{name}:{local}')
        if done.returncode != 0:
            if MISSING in done.stderr:
                return None
            raise GitRefError(f'git fetch {name} failed: {_last_line(done.stderr)}')
        return self._must('rev-parse', '--verify', f'{local}^{{commit}}')

class GitRefAdapter:
    """EVENTS-REF (E1, D-273): the event port's log on one git ref, refs/heads/<forge-events.git_ref_log>. One commit per
    append holds {channel: {repo, pr}, events: [...]}, advanced by fast-forward from a fresh read of the tip (append), so
    no REST call, no comment ceiling and no secondary write limit. Every channel shares the ref (the proxy can create and
    advance refs/heads/* but never delete one, so a ref per PR would only accumulate). A read fetches the tip once and
    parses the records in one `git log`; the parse is kept per tip, so a second read of an unmoved ref costs one fetch."""

    remote = True

    def __init__(self, refs=None, name=None, attempts=None, window=None):
        self.refs = refs or GitRefs()
        self.name = name or config.get('forge-events.git_ref_log')
        self.attempts = attempts or config.get('forge-events.git_ref_attempts')
        self.window = window or config.get('forge-events.git_ref_window')
        self._parsed = {}  # (tip sha, window) -> [(channel key, events)], oldest first

    @staticmethod
    def _key(channel):
        return [channel.repo, channel.pr]

    def append(self, channel, envelopes):
        events = [json.loads(json.dumps(e)) for e in envelopes]
        if not events:
            return
        record = {'channel': {'repo': channel.repo, 'pr': channel.pr}, 'events': events}
        if self.refs.append(self.name, record, self.attempts) is None:
            raise GitRefError(f'refs/heads/{self.name}: every one of {self.attempts} appends lost the race')

    def _records(self, limit=None):
        held = self.refs.read(self.name)
        if held is None:
            return [], True
        sha = held[0]
        if (sha, limit) not in self._parsed:
            local = f'{LOCAL_NAMESPACE}{self.name}'
            args = ['log', '--format=%B%x1e', *(['-n', str(limit)] if limit else []), local]
            records = []
            for chunk in reversed(self.refs._must(*args).split('\x1e')):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    record = json.loads(chunk)
                    where = record['channel']
                    records.append(([where.get('repo'), where.get('pr')], list(record.get('events') or [])))
                except (ValueError, KeyError, TypeError, AttributeError):
                    raise GitRefError(f'refs/heads/{self.name} holds a commit that is not an event record') from None
            complete = not limit or int(self.refs._must('rev-list', '--count', local)) <= limit
            self._parsed[(sha, limit)] = (records, complete)
        return self._parsed[(sha, limit)]

    def _events(self, channel, limit=None):
        records, complete = self._records(limit)
        key = self._key(channel)
        return [event for where, events in records if where == key for event in events], complete

    def read(self, channel):
        return self._events(channel)[0]

    def recent(self, channel, tail=None):
        """(events, complete) of the newest forge-events.git_ref_window records of the ref (D-085's windowed read), or
        of the newest `tail` records when a reader needs a deeper window."""
        return self._events(channel, tail or self.window)
