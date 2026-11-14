"""The subscription CLIs as session providers (AWS-SUBSCRIPTION-PROVIDERS): 'claude-code' runs `claude -p` on a Max
subscription and 'codex' runs `codex exec` on a ChatGPT one, each on the service task, in a scratch checkout of the job's
repositories, with the brief as the prompt; the CLI commits, pushes a branch and opens the PR through git and the origin CLI.

The credentials are SecureStrings (/tower/sessions/claude-code: the CLI's credentials JSON, claudeAiOauth with accessToken,
refreshToken and expiresAt in ms; /tower/sessions/codex: auth.json). They are written only into a 0700 HOME made for the run
and removed after it; they are never logged, never in a result (what the CLI or git says is scrubbed of them).

Renewal: neither CLI is renewed by hand. The stored credential goes into the run's HOME as-is (Claude's own
~/.claude/.credentials.json, Codex's auth.json) and the CLI refreshes and rotates it itself while it runs. (A hand-rolled
refresh against console.anthropic.com/v1/oauth/token with an unverified client id answered 403 Forbidden: removed.) After
the run, success or failure, the file is read back and, when it changed, written to the same parameter through
save(name, value), so a rotated refresh token is never lost; the task role needs ssm:PutParameter on /tower/sessions/*
(#362); without it the run's result says "credentials_unsaved".
A Claude run whose CLI reports a login failure ("OAuth token has expired", "Invalid API key", "Please run /login") ends
failed with error 'auth: login needed (<reason>)', so the job says "login needed" instead of a bare HTTP 403.

One process-wide lock (LOCK) keeps the two CLIs from running at once, a launch queues behind it and follows as "running".
Codex is never resumed (resume does nothing); a Claude session that hit its limit ends failed, its job retries by policy.
Sessions live in the process: after a restart follow answers ended/failed "lost". Standard library only.
"""
import base64
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

LOCK = threading.Lock()
DETAIL = 600
NAMES = ('claude-code', 'codex')


def credential_helper(cli):
    quoted = shlex.quote(cli)
    return f'!f() {{ CURSOR_AUTH_TOKEN="$({quoted} auth token 2>/dev/null)" exec {quoted} credential-helper "$@"; }}; f'


class NoCredential(Exception):
    """The subscription's SecureString is not there."""


class Cli:
    """One subscription CLI. read() answers the stored credential text or None; save(name, text) stores a renewed one;
    credential() answers the forge key the CLI's git and origin calls use; run(argv, **kw) is subprocess.run's shape;
    clock() answers epoch seconds; spawn(fn) starts the worker."""

    def __init__(self, name, read, save=None, credential=None, run=subprocess.run, clock=time.time, spawn=None,
                 environ=None, tmp=None, ids=lambda: uuid.uuid4().hex):
        self.name, self.read, self.save, self.credential = name, read, save, credential
        self.before = {}
        self.run, self.clock, self.ids, self.tmp = run, clock, ids, tmp
        self.environ = dict(os.environ if environ is None else environ)
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.sessions, self.state_lock = {}, threading.Lock()

    # -- the provider interface
    def launch(self, spec):
        text = self.read()
        if not text:
            raise NoCredential(f'no credential for the {self.name} subscription (/tower/sessions/{self.name})')
        session = f'{self.name}/{self.ids()}'
        with self.state_lock:
            self.sessions[session] = {'state': 'running', 'cancelled': False}
        self.spawn(lambda: self.work(session, spec))
        return session

    def follow(self, session):
        with self.state_lock:
            seen = self.sessions.get(session)
        if seen is None:
            return {'state': 'ended', 'outcome': 'failed', 'error': 'lost: the service restarted during the session'}
        return dict(seen['answer']) if seen['state'] == 'ended' else {'state': 'running'}

    def resume(self, session):
        return None  # Codex is never resumed; Claude's limit ends the session failed

    def end(self, session):
        with self.state_lock:
            if session in self.sessions:
                self.sessions[session]['cancelled'] = True

    # -- the run
    def work(self, session, spec):
        with LOCK:  # Claude Code and Codex never run at the same time
            answer = self.guarded(session, spec)
        with self.state_lock:
            self.sessions[session].update(state='ended', answer=answer)

    def guarded(self, session, spec):
        secrets, home = [], None
        try:
            if self.sessions[session]['cancelled']:
                return {'state': 'ended', 'outcome': 'cancelled', 'error': 'cancelled'}
            base = Path(self.tmp or tempfile.gettempdir())
            home = Path(tempfile.mkdtemp(prefix=f'{self.name}-', dir=base))
            home.chmod(0o700)
            text = self.read()
            unsaved = self.install(home, text, secrets)
            return self.execute(home, spec, secrets, unsaved, session)
        except Exception as error:  # noqa: BLE001 - the session fails, named, without a credential
            return {'state': 'ended', 'outcome': 'failed', 'error': self.scrub(f'{type(error).__name__}: {error}', secrets)}
        finally:
            if home is not None:
                shutil.rmtree(home, ignore_errors=True)

    @staticmethod
    def scrub(text, secrets):
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret and len(secret) > 3:
                text = text.replace(secret, '<redacted>')
        return re.sub(r'(sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{20,})', '<redacted>', text)

    def child_env(self, home, secrets):
        env = {'PATH': self.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'HOME': str(home),
               'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'credential.helper',
               'GIT_CONFIG_VALUE_0': '', 'GIT_CONFIG_KEY_1': 'credential.helper',
               'GIT_CONFIG_VALUE_1': credential_helper(self.environ.get('TOWER_ORIGIN_CLI', 'origin')),
               'GIT_AUTHOR_NAME': 'The Tower', 'GIT_COMMITTER_NAME': 'The Tower',
               'GIT_AUTHOR_EMAIL': 'tower@invalid', 'GIT_COMMITTER_EMAIL': 'tower@invalid'}
        key = self.credential() if self.credential else None
        if key:
            env['CURSOR_API_KEY'] = key
            secrets.append(key)
        return env

    def git(self, env, args, cwd, secrets):
        done = self.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True, check=False,
                        timeout=float(self.environ.get('TOWER_GIT_TIMEOUT_S', 300)))
        if done.returncode:
            said = self.scrub((done.stderr or '') + (done.stdout or ''), secrets)
            raise RuntimeError(f'git {args[0]} failed: {said.strip()[-DETAIL:]}')

    def checkout(self, env, spec, work, secrets):
        names = []
        for number, repo in enumerate(spec.get('repos') or []):
            name = re.sub(r'[^A-Za-z0-9._-]', '-', str(repo.get('name') or repo['url'].rstrip('/').split('/')[-1]
                                                       ).removesuffix('.git')) or f'repo{number}'
            if name in names:
                name = f'{name}-{number}'
            names.append(name)
            self.git(env, ['clone', '--quiet', repo['url'], name], work, secrets)
            if repo.get('ref'):
                self.git(env, ['checkout', '--quiet', repo['ref']], work / name, secrets)
        return names

    def prompt(self, spec, names, session):
        branch = spec.get('branch') or f"session/{session.split('/', 1)[1][:12]}"
        where = 'the repository in the current directory' if len(names) < 2 else f"the repositories {', '.join(names)}"
        return (f"{spec['brief'].strip()}\n\nYou work in {where}, a scratch checkout. When the work is done, commit it on "
                f"the branch {branch}, push that branch to origin and open a pull request with the origin CLI "
                f"(`origin pr create`). Answer with the pull request's URL.\n") if names else spec['brief']

    def execute(self, home, spec, secrets, unsaved, session):
        env = self.child_env(home, secrets)
        work = home / 'work'
        work.mkdir()
        names = self.checkout(env, spec, work, secrets)
        cwd = work / names[0] if len(names) == 1 else work
        argv = self.argv(spec, cwd)
        if self.sessions[session]['cancelled']:
            return {'state': 'ended', 'outcome': 'cancelled', 'error': 'cancelled'}
        try:
            done = self.run(argv, cwd=cwd, env=self.cli_env(env, home), input=self.prompt(spec, names, session),
                            capture_output=True, text=True, check=False,
                            timeout=float(self.environ.get('TOWER_CLI_TIMEOUT_S', 3600)))
        finally:  # a failed or timed-out run may still have rotated the refresh token: it is saved either way
            unsaved = self.writeback(home, secrets) or unsaved
        answer = self.parse(done.stdout or '', done.returncode, self.scrub(done.stderr or '', secrets))
        if unsaved:
            answer.setdefault('result', {})['credentials_unsaved'] = unsaved if isinstance(unsaved, str) else True
        return answer

    def cli_env(self, env, home):
        return env

    def credential_file(self, home):
        raise NotImplementedError

    def tokens(self, text):
        return re.findall(r'"(?:accessToken|refreshToken|access_token|refresh_token|id_token|OPENAI_API_KEY)"\s*:\s*"([^"]+)"',
                          text)

    def install(self, home, text, secrets):
        """The stored credential goes into the CLI's own file as it is; the CLI renews it while it runs."""
        json.loads(text)  # refuses a stored value that is not the CLI's credentials JSON
        secrets.extend(self.tokens(text))
        target = self.credential_file(home)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        target.write_text(text)
        target.chmod(0o600)
        self.before[str(home)] = text
        return False

    def writeback(self, home, secrets):
        """What the CLI left in its credential file goes back to the parameter only when it is a whole credential (parses,
        non-empty tokens, a numeric expiry) that expires strictly later than the value in the parameter RIGHT NOW (re-read
        here: the Torre shares the parameter and renews it too). Whatever the run's outcome, an empty, unparseable or older
        file is never written. Answers None (nothing to save, or saved) or the reason it was not saved (never a value)."""
        before = self.before.pop(str(home), None)
        try:
            now = self.credential_file(home).read_text()
        except OSError:
            return 'credential file unreadable' if before is not None else None
        if before is None or now == before:
            return None
        secrets.extend(self.tokens(now))
        ours, why = self.stamp(now)
        if ours is None:
            return f'not written: the file the CLI left is not a whole credential ({why})'
        try:
            stored = self.read()
        except Exception:  # noqa: BLE001 - cannot compare, so does not overwrite
            return 'not written: the stored credential could not be re-read'
        if stored:
            theirs, _ = self.stamp(stored)
            if theirs is not None and ours <= theirs:
                return ('not written: the stored credential changed during the run and is as new or newer'
                        if stored != before else 'not written: the CLI left a credential no newer than the stored one')
        return 'not written: the credential could not be stored' if self.renewed(f'/tower/sessions/{self.name}', now) else None

    def stamp(self, text):
        """(sortable expiry, None) of a whole credential, or (None, reason); the reason names no value."""
        raise NotImplementedError

    @staticmethod
    def jwt_exp(token):
        try:
            part = token.split('.')[1]
            exp = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))).get('exp')
            return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None
        except Exception:  # noqa: BLE001 - not a JWT
            return None

    def renewed(self, name, text):
        """Stores a renewed credential in the same parameter; True when it could not be stored."""
        try:
            if self.save is None:
                return True
            self.save(name, text)
            return False
        except Exception:  # noqa: BLE001 - PutParameter is not in the task role: the run goes on, the result says so
            return True


class ClaudeCode(Cli):
    def __init__(self, *args, **kw):
        super().__init__('claude-code', *args, **kw)

    def credential_file(self, home):
        return home / '.claude' / '.credentials.json'

    def stamp(self, text):
        try:
            oauth = json.loads(text)['claudeAiOauth']
            access, refresh, expires = oauth['accessToken'], oauth['refreshToken'], oauth['expiresAt']
        except Exception:  # noqa: BLE001 - parse failure or missing field
            return None, 'unparseable or no claudeAiOauth fields'
        if not (isinstance(access, str) and access.strip() and isinstance(refresh, str) and refresh.strip()):
            return None, 'empty token'
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or expires <= 0:
            return None, 'no usable expiresAt'
        return (float(expires),), None

    def argv(self, spec, cwd):
        argv = ['claude', '-p', '--output-format', 'json', '--dangerously-skip-permissions']
        return argv + (['--model', str(spec['model'])] if spec.get('model') else [])

    LOGIN = (('oauth token has expired', 'token expired'), ('token has expired', 'token expired'),
             ('invalid api key', 'invalid key'), ('please run /login', 'not logged in'),
             ('not logged in', 'not logged in'), ('invalid bearer token', 'invalid token'),
             ('authentication_error', 'authentication failed'), ('failed to authenticate', 'authentication failed'),
             ('invalid authentication credentials', 'authentication failed'))

    def login_failure(self, *texts):
        """The short reason when the CLI says its login is gone or invalid, else None."""
        said = ' '.join(str(t) for t in texts if t).lower()
        return next((reason for phrase, reason in self.LOGIN if phrase in said), None)

    def parse(self, out, code, err):
        try:
            seen = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            seen = None
        if not isinstance(seen, dict):
            reason = self.login_failure(out, err)
            if reason:
                return {'state': 'ended', 'outcome': 'failed', 'error': f'auth: login needed ({reason})'}
            return {'state': 'ended', 'outcome': 'failed', 'error': f'claude exit {code}: {err[-DETAIL:]}'}
        failed = bool(seen.get('is_error')) or code != 0
        models = seen.get('modelUsage') or {}
        tokens = {model: sum(int(use.get(k, 0)) for k in ('inputTokens', 'outputTokens', 'cacheReadInputTokens',
                                                          'cacheCreationInputTokens'))
                  for model, use in models.items()}
        result = {key: seen[key] for key in ('result', 'total_cost_usd', 'duration_ms', 'num_turns') if key in seen}
        error = str(seen.get('result') or err)[-DETAIL:] if failed else None
        reason = self.login_failure(seen.get('result'), seen.get('error'), err) if failed else None
        if reason:
            error, result = f'auth: login needed ({reason})', {key: v for key, v in result.items() if key != 'result'}
        return {'state': 'ended', 'outcome': 'failed' if failed else 'succeeded', 'error': error, 'result': result,
                'tokens': tokens}


class Codex(Cli):
    def __init__(self, *args, **kw):
        super().__init__('codex', *args, **kw)

    def credential_file(self, home):
        return home / '.codex' / 'auth.json'

    def stamp(self, text):
        """auth.json: tokens.access_token / refresh_token and last_refresh (ISO); newer = later JWT exp, then later last_refresh."""
        try:
            auth = json.loads(text)
            tokens = auth['tokens']
            access, refresh = tokens['access_token'], tokens['refresh_token']
        except Exception:  # noqa: BLE001 - parse failure or missing field
            return None, 'unparseable or no tokens'
        if not (isinstance(access, str) and access.strip() and isinstance(refresh, str) and refresh.strip()):
            return None, 'empty token'
        refreshed = 0.0
        try:
            refreshed = datetime.datetime.fromisoformat(str(auth.get('last_refresh')).replace('Z', '+00:00')).timestamp()
        except Exception:  # noqa: BLE001 - no usable last_refresh
            pass
        exp = self.jwt_exp(access) or 0.0
        if not (exp or refreshed):
            return None, 'no expiry (JWT exp or last_refresh)'
        return (exp, refreshed), None

    def cli_env(self, env, home):
        return dict(env, CODEX_HOME=str(home / '.codex'))

    def argv(self, spec, cwd):
        argv = ['codex', 'exec', '--json', '--skip-git-repo-check', '--dangerously-bypass-approvals-and-sandbox',
                '-C', str(cwd)]
        return argv + (['-m', str(spec['model'])] if spec.get('model') else []) + ['-']

    def parse(self, out, code, err):
        events = []
        for line in out.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        used = [e.get('usage') or {} for e in events if e.get('type') == 'turn.completed']
        total = sum(int(u.get('input_tokens', 0)) + int(u.get('output_tokens', 0)) for u in used)
        failures = [str((e.get('error') or {}).get('message') or e.get('message') or 'error') for e in events
                    if e.get('type') in ('error', 'turn.failed')]
        said = [str((e.get('item') or {}).get('text', '')) for e in events
                if e.get('type') == 'item.completed' and (e.get('item') or {}).get('type') == 'agent_message']
        failed = code != 0 or bool(failures) or not used
        return {'state': 'ended', 'outcome': 'failed' if failed else 'succeeded',
                'error': ((failures[-1] if failures else err or f'codex exit {code}')[-DETAIL:] if failed else None),
                'result': {'result': said[-1]} if said else {}, 'tokens': {self.model_name(): total} if used else {}}

    def model_name(self):
        return self.environ.get('TOWER_CODEX_MODEL', 'codex')


def providers(read, save=None, credential=None, **kw):
    """{'claude-code': ..., 'codex': ...}; read(name) answers /tower/sessions/<name>'s text or None."""
    return {'claude-code': ClaudeCode(lambda: read('claude-code'), save, credential, **kw),
            'codex': Codex(lambda: read('codex'), save, credential, **kw)}
