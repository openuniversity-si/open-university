"""GX-05 (B-09, GA-PG1, D-070): the pinned gate. The base tip's tooling judges; the PR head is only code under test.

`scripts/gate-local --pr N | --sha S`, unless already pinned (OU_GATE_PINNED) or --report-only, hands its arguments to
`gate_pin.py run --root <invoking checkout> -- <args>`, which:
  1. resolves the base sha: --pr reads the head and base in the one port change read the driver makes (handed to the
     child in OU_GATE_PR_IDENTITY, so it makes no second one); --sha takes the `base` of --plan-file (a batch), else
     the fetched tip of gate.batch_base_ref;
  2. takes the tool root: the invoking checkout when it is the clean base sha, else the tool worktree
     <gate.slot_dir>/<gate-pin.dir>/<clone id>/<base sha>, created under the directory lock and reused while the base
     is the same; the run holds a shared lock on it, and eviction keeps gate-pin.keep_worktrees base shas;
  3. prints `gate: pinned to <base sha>` and `gate: version <gate_version>` first, then runs that tool root's
     scripts/gate-local with the same arguments, OU_GATE_PINNED=<base sha> and the invoking checkout as record root
     (OU_GATE_RECORD_ROOT, GATE_RECORD_DIR, GATE_LOCK_FILE). Its verdict, events, status and record are the gate's;
  4. when the diff base...head touches the gate (commit_check.GATE_FILE), runs the head's own tooling with
     --report-only (no events, record, status or pr.ready), prints its verdict as advisory and, for --pr, posts it as
     its own advisory comment. The exit code is always the pinned run's.

A tool worktree has no .toolchain/: its .toolchain is a symlink to the invoking checkout's, so the pinned env.sh
resolves the caller's PATH, OU_PYTHON and PostgreSQL, and the caller's exported environment (its own test database)
is inherited. gate_version is the git tree id of scripts/ at the tooling commit (same tooling, same version).
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import config

GATE_LOCAL = 'scripts/gate-local'
TOOLCHAIN = '.toolchain'
USE_SUFFIX = '.use'
HEADS = 'heads'
REPORT_ONLY_DIR = '.gate/report-only'
REPORT_ONLY_MODES = ('dev', 'tier3', 'pr-sha')  # the modes that reach no outside database
# The pinned tooling's hermetic sitecustomize may have imported its own config module into this process first; the code
# under test reads its own checkout's registry (GX-01 retro), so every key names this checkout's root.
ROOT = Path(__file__).resolve().parent.parent.parent
SHA = re.compile(r'[0-9a-f]{40}')
REF = re.compile(r'(?!-)[A-Za-z0-9._/-]+')
CONSUMER = 'scripts/lib/gate_pin.py'  # this module's demand on the forge port (operation_demands.json)
PRODUCER = 'gate-pin'
UNPINNED = 'off'  # OU_GATE_PINNED value of a run the switch left unpinned


def setting(name):
    return config.get(name, ROOT)


class PinError(Exception):
    """A setup error of the pin (the driver's classified abort, a setup error), with the message to print."""


def git(root, *args, check=True):
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines() or ['']
        raise PinError(f'git {" ".join(args)}: {lines[-1]}')
    return done.stdout.strip() if done.returncode == 0 else None


def options(args):
    """The driver arguments that matter to the pin: pr, sha, plan_file, mode."""
    found = {'pr': None, 'sha': None, 'plan_file': None, 'flags': set()}
    items = list(args)
    for index, item in enumerate(items):
        if item in ('--pr', '--sha', '--plan-file') and index + 1 < len(items):
            found[item.removeprefix('--').replace('-', '_')] = items[index + 1]
        elif item.startswith('--'):
            found['flags'].add(item.removeprefix('--'))
    flags = found['flags']
    if 'db' in flags:
        mode = 'db'
    elif 'tier3' in flags:
        mode = 'tier3'
    elif 'noite' in flags:
        mode = 'noite'
    elif 'dev' in flags:
        mode = 'dev'
    elif 'nightly' in flags:
        mode = 'nightly'
    else:
        mode = 'pr' if found['pr'] else 'pr-sha'
    found['mode'] = mode
    return found


def forge_port(pr):
    """The forge port pr_identity reads the change through (ORIGIN-FINISH): the configured adapter, this consumer."""
    import forge_events  # only a --pr pin reads the forge; a --sha pin never loads the port
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(), PRODUCER,
                                    f'pr-{pr}', consumer=CONSUMER)


def pr_identity(root, pr, port=None):
    """(head, reported base sha, base ref name) of PR <pr> from one change read through the forge port.
    GX-FIX-forge-rate-2 (D-070): GitHub's base sha is the base as of the PR's last synchronization, not the tip of its
    base branch, so resolve() pins to the fetched tip of the base REF and only reports a lagging base sha."""
    try:
        port = port or forge_port(pr)
        change = port.change(setting('forge-events.repo'), int(pr))
    except (RuntimeError, OSError, ValueError, KeyError) as error:  # the port's, its adapter's and config's errors
        raise PinError(f'cannot read PR #{pr} head/base: {str(error).strip() or type(error).__name__}') from None
    change = change if isinstance(change, dict) else {}
    head, base, ref = (str(change.get(key) or '') for key in ('head', 'base', 'base_ref'))
    if not (SHA.fullmatch(head) and SHA.fullmatch(base) and REF.fullmatch(ref)):
        raise PinError(f'cannot read PR #{pr} head/base (the forge returned no valid head, base and base ref)')
    return head, base, ref


def base_tip(root, ref):
    """The tip of origin's branch <ref>, fetched now. A fetch that fails is a PinError, never a stale local ref."""
    if not REF.fullmatch(ref):
        raise PinError(f'invalid base ref {ref!r}')
    git(root, 'fetch', '-q', 'origin', f'+refs/heads/{ref}:refs/remotes/origin/{ref}')
    return fetch_commit(root, f'refs/remotes/origin/{ref}')


def fetch_commit(root, sha):
    """The full sha of <sha>, fetched from origin when it is not here yet."""
    if git(root, 'rev-parse', '--verify', '-q', f'{sha}^{{commit}}', check=False) is None:
        if git(root, 'fetch', '-q', 'origin', sha, check=False) is None:
            git(root, 'fetch', '-q', 'origin', check=False)
    full = git(root, 'rev-parse', '--verify', '-q', f'{sha}^{{commit}}', check=False)
    if not full:
        raise PinError(f'unknown commit {sha}')
    return full


def batch_base(root):
    """The fetched tip of gate.batch_base_ref (the train's batch base)."""
    ref = setting('gate.batch_base_ref')
    remote, _, branch = ref.partition('/')
    if branch:  # GX-FIX-forge-rate-2: a failed fetch is a PinError, never the stale local ref (older tooling)
        git(root, 'fetch', '-q', remote, f'+refs/heads/{branch}:refs/remotes/{remote}/{branch}')
    return fetch_commit(root, ref)


def resolve(root, opts, identity=pr_identity):
    """(head, base, pr_identity or None) for the pinned run."""
    if opts['pr']:
        head, reported, *named = identity(root, opts['pr'])
        base = base_tip(root, named[0]) if named else fetch_commit(root, reported)
        if base != reported:
            print(f'gate: GitHub reports base {reported} for PR #{opts["pr"]}; pinned to the fetched tip of '
                  f'{named[0]} instead', file=sys.stderr)
        return fetch_commit(root, head), base, f'{head}\t{base}'
    if not opts['sha']:
        raise PinError('the pin needs --pr or --sha')
    head = fetch_commit(root, opts['sha'])
    if opts['plan_file']:
        try:
            base = json.loads(Path(opts['plan_file']).read_text())['base']
        except (OSError, ValueError, KeyError) as error:
            raise PinError(f'cannot read the batch plan {opts["plan_file"]}: {error}') from error
        return head, fetch_commit(root, base), None
    return head, batch_base(root), None


def gate_version(root, sha):
    """Content address of the gate tooling: the tree id of scripts/ at <sha>."""
    return git(root, 'rev-parse', f'{sha}:scripts')


def gate_changed(root, base, head):
    """The gate files (commit_check.GATE_FILE) the diff base...head touches."""
    import commit_check
    names = git(root, 'diff', '--name-only', f'{base}...{head}') or ''
    return [name for name in names.splitlines() if commit_check.GATE_FILE.match(name)]


def clean_at(root, sha):
    """True when the checkout's HEAD is <sha> and no tracked file differs."""
    return (git(root, 'rev-parse', 'HEAD', check=False) == sha
            and git(root, 'status', '--porcelain', '--untracked-files=no', check=False) == '')


def pin_root(root):
    """<gate.slot_dir>/<gate-pin.dir>/<clone id>: the clone id is a hash of the absolute git common dir."""
    common = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    clone = hashlib.sha1(common.encode()).hexdigest()
    slot_dir = os.environ.get('GATE_SLOT_DIR') or setting('gate.slot_dir')
    return Path(slot_dir) / setting('gate-pin.dir') / clone


def link_toolchain(root, tool):
    """tool/.toolchain -> root/.toolchain (replaced atomically when it points elsewhere); absent when root has none."""
    source, link = Path(root).resolve() / TOOLCHAIN, Path(tool) / TOOLCHAIN
    if Path(tool).resolve() == Path(root).resolve():
        return
    if not source.is_dir():
        if link.is_symlink():
            link.unlink()
        return
    if link.is_symlink() and os.readlink(link) == str(source):
        return
    if link.exists() and not link.is_symlink():
        raise PinError(f'{link} is a real directory; the tool worktree must use the caller\'s toolchain')
    temp = Path(tool) / f'{TOOLCHAIN}.{os.getpid()}'
    if temp.is_symlink():
        temp.unlink()
    os.symlink(source, temp)
    os.replace(temp, link)


def lock(path, kind):
    handle = open(path, 'a')
    fcntl.flock(handle, kind)
    return handle


def valid_worktree(root, path, sha):
    return (path.is_dir() and git(path, 'rev-parse', 'HEAD', check=False) == sha
            and git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir', check=False)
            == git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))


def add_worktree(root, path, sha):
    if path.exists():
        git(root, 'worktree', 'remove', '--force', str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
    git(root, 'worktree', 'prune')
    git(root, 'worktree', 'add', '-q', '--detach', str(path), sha)


def evict(root, base_dir, keep, current):
    """Remove the least recently used base worktrees beyond <keep>; never <current>, never one a run holds."""
    uses = sorted(base_dir.glob(f'*{USE_SUFFIX}'), key=lambda path: path.stat().st_mtime, reverse=True)
    kept, removed = 1, []
    for use in uses:
        sha = use.name[:-len(USE_SUFFIX)]
        if sha == current:
            continue
        if kept < keep:
            kept += 1
            continue
        handle = open(use, 'a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            continue
        git(root, 'worktree', 'remove', '--force', str(base_dir / sha), check=False)
        shutil.rmtree(base_dir / sha, ignore_errors=True)
        use.unlink()
        handle.close()
        removed.append(sha)
    git(root, 'worktree', 'prune', check=False)
    return removed


def ensure(root, base):
    """(tool root, shared-lock handle or None) of the base sha; the handle must stay open for the whole run."""
    if clean_at(root, base):
        return Path(root), None
    base_dir = pin_root(root)
    base_dir.mkdir(parents=True, exist_ok=True)
    tool, use = base_dir / base, base_dir / f'{base}{USE_SUFFIX}'
    with lock(base_dir / '.lock', fcntl.LOCK_EX):
        if not valid_worktree(root, tool, base):
            add_worktree(root, tool, base)
        link_toolchain(root, tool)
        held = lock(use, fcntl.LOCK_SH)
        os.utime(use)
        evict(root, base_dir, setting('gate-pin.keep_worktrees'), base)
    return tool, held


def head_tooling(root, head):
    """(tool root, throwaway path or None) of the head's own tooling for the report-only run."""
    if clean_at(root, head):
        return Path(root), None
    heads = pin_root(root) / HEADS
    heads.mkdir(parents=True, exist_ok=True)
    path = heads / f'{head}-{os.getpid()}'
    add_worktree(root, path, head)
    link_toolchain(root, path)
    return path, path


def drop(root, path):
    if path is not None:
        git(root, 'worktree', 'remove', '--force', str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
        git(root, 'worktree', 'prune', check=False)


def pinned_env(root, base, version, identity, environ):
    env = dict(environ)
    root = Path(root).resolve()
    env.update(OU_GATE_PINNED=base, OU_GATE_RECORD_ROOT=str(root), OU_GATE_VERSION=version)
    env.setdefault('GATE_RECORD_DIR', str(root / '.gate/records'))
    env.setdefault('GATE_LOCK_FILE', str(root / '.gate/gate.lock'))
    if identity:
        env['OU_GATE_PR_IDENTITY'] = identity
    else:
        env.pop('OU_GATE_PR_IDENTITY', None)
    return env


def report_env(root, head_version, environ):
    """The report-only run's environment: unpinned, its own record dir (it writes no record, and a failure must not
    delete the pinned run's), the caller's lock; its reports stay under <root>/.gate/report-only for reading."""
    env = dict(environ)
    for name in ('OU_GATE_PINNED', 'OU_GATE_PR_IDENTITY', 'GATE_REPORT_DIR'):
        env.pop(name, None)
    root = Path(root).resolve()
    env.update(OU_GATE_RECORD_ROOT=str(root), OU_GATE_VERSION=head_version, GATE_RECORD_DIR=str(root / REPORT_ONLY_DIR))
    env.setdefault('GATE_LOCK_FILE', str(root / '.gate/gate.lock'))
    return env


def verdict(rc):
    return 'PASSED' if rc == 0 else f'FAILED (exit {rc})'


def advisory_body(base, head, mode, pinned_rc, report_rc, files):
    """(state, body) of the advisory comment: gate_status's marker line with mode <mode>+advisory, so it is found
    again and edited in place next to the status comment of the same head, never duplicated."""
    import gate_status
    state = {'pr': None, 'sha': head, 'mode': f'{mode}+advisory'}
    shown = ', '.join(f'`{name}`' for name in files)
    return state, '\n'.join([
        gate_status.marker_line(head, state['mode']),
        f'**Advisory (report-only):** the head\'s own gate tooling says **{verdict(report_rc)}**.',
        f'The verdict is the pinned gate on base `{base}`: **{verdict(pinned_rc)}** (GA-PG1, D-070).',
        f'This PR changes the gate ({shown}); its new behaviour judges PRs only after it merges.',
    ])


def post_advisory(pr, state, body):
    """Publish through the status comment's publisher (forge adapter). A failure is printed, never fails the gate."""
    try:
        import gate_status
        gate_status.Publisher().publish({**state, 'pr': int(pr)}, body)
    except Exception as error:  # noqa: BLE001 - the advisory view never changes the verdict
        print(f'gate: advisory comment not posted ({error})', file=sys.stderr)


def run(root, args, environ=None, identity=pr_identity, call=subprocess.call, post=post_advisory, out=print,
        abort_file=None):
    """The pinned gate; returns the pinned run's exit code. A pin setup error returns 1 and, with abort_file, writes
    its message there so the driver ends the run with its classified abort (driver_abort "gate pin")."""
    environ = dict(os.environ if environ is None else environ)
    if not setting('gate-pin.enabled'):
        # The rollback (gate-pin.enabled=false): the invoking checkout's own tooling judges, as before GX-05.
        return call([str(Path(root) / GATE_LOCAL), *args], env={**environ, 'OU_GATE_PINNED': UNPINNED})
    opts = options(args)
    try:
        head, base, pair = resolve(root, opts, identity)
        tool, held = ensure(root, base)
    except PinError as error:
        if abort_file:
            Path(abort_file).write_text(str(error))
        else:
            out(f'gate: pin failed: {error}')
        return 1
    try:
        version = gate_version(root, base)
        out(f'gate: pinned to {base}')
        out(f'gate: version {version}')
        sys.stdout.flush()
        rc = call([str(Path(tool) / GATE_LOCAL), *args], env=pinned_env(root, base, version, pair, environ))
    finally:
        if held is not None:
            held.close()
    out(f'gate: pinned verdict {verdict(rc)}')
    if setting('gate-pin.report_only_on_gate_change'):
        report(root, args, opts, base, head, rc, environ, call, post, out)
    return rc


def report(root, args, opts, base, head, pinned_rc, environ, call, post, out):
    """The head's own tooling, --report-only, when the diff touches the gate; prints (and posts) its verdict."""
    files = gate_changed(root, base, head)
    if not files:
        return None
    if opts['mode'] not in REPORT_ONLY_MODES:
        out(f'gate: advisory skipped (mode {opts["mode"]} reaches an outside database; the report-only run never does)')
        return None
    if git(root, 'merge-base', '--is-ancestor', base, head, check=False) is None:
        # GX-FIX-forge-rate-2 (D-070): a head behind the base tip carries older tooling than the base's (it may predate
        # the base's forge fixes, e.g. the per-test event comments); it is never run, not even report-only.
        out(f'gate: advisory skipped (head {head} does not contain the base tip {base}; merge the base first)')
        return None
    try:
        tool, throwaway = head_tooling(root, head)
    except PinError as error:
        out(f'gate: advisory skipped ({error})')
        return None
    try:
        out(f'gate: advisory run of the head tooling {head} (version {gate_version(root, head)}), report-only')
        sys.stdout.flush()
        rc = call([str(Path(tool) / GATE_LOCAL), *args, '--report-only'],
                  env=report_env(root, gate_version(root, head), environ))
    finally:
        drop(root, throwaway)
    out(f'gate: advisory (head tooling, report-only): {verdict(rc)}; the verdict is the pinned gate: {verdict(pinned_rc)}')
    if opts['pr']:
        post(opts['pr'], *advisory_body(base, head, opts['mode'], pinned_rc, rc, files))
    return rc


def main(argv):
    """gate_pin.py run --root <checkout> [--abort-file <path>] -- <gate-local args>"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--abort-file')
    split = argv.index('--') if '--' in argv else len(argv)
    found = parser.parse_args(argv[:split])
    return run(found.root, argv[split + 1:], abort_file=found.abort_file)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
