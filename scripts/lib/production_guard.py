"""No production from a session (D-054, enforcement audit 2026-10-26 rule 7, PS1; D-069 item 13).

Two halves over one registry list, production.forbidden_entrypoints:
  refuse   `production_guard.py refuse <entrypoint>` exits non-zero inside a cloud session (a marker of
           production.cloud_session_markers is set); every production script calls it first.
  check    the gate's always-run "production guard" stage (D-322: its own stage, so the structure check, a lower
           layer, imports nothing of it), `production_guard.py check [--base SHA] [--root PATH]`: a diff that adds a mention of an entrypoint (or of its scripts/lib
           module, derived from the name) outside production.invocation_allowed_paths is refused, a new script
           included.
The host-side flow is unchanged: a shell with no marker passes both."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

import config
from entrypoint_mentions import mentions  # noqa: F401 - D-322: moved down to layer 0; re-exported


def cloud_session(env=None, root=None):
    env = os.environ if env is None else env
    return [name for name in config.get('production.cloud_session_markers', root) if env.get(name)]


def refusal(entrypoint, env=None, root=None):
    """The message a production script prints and the status it exits with, or None when it may run."""
    markers = cloud_session(env, root)
    if not markers:
        return None
    return (f'scripts/{entrypoint}: refused inside a cloud session ({markers[0]} is set). Production is changed only by '
            f'the host-side release pipeline (D-054, docs/process/RELEASES.md); a change production needs goes into '
            f'docs/process/host-swap-queue.md.', config.get('production.refusal_exit_code', root))


def added_lines(root, base):
    """{path: [added line, ...]} of base...HEAD plus the working tree; None when the diff cannot be read."""
    run = subprocess.run(['git', '-C', str(root), 'diff', '-U0', '--no-color', base], capture_output=True, text=True)
    if run.returncode != 0:
        return None
    files, path = {}, None
    for line in run.stdout.splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('+') and path:
            files.setdefault(path, []).append(line[1:])
    return files


def check(root, base=None):
    root = Path(root)
    if not base or not (root / 'config' / 'registry' / 'production.json').is_file():
        return [], []
    files = added_lines(root, base)
    if files is None:
        return [], [f'production: cannot diff {base}; the invocation scan did not run']
    entrypoints = config.get('production.forbidden_entrypoints', root)
    allowed = config.get('production.invocation_allowed_paths', root)
    roots = tuple(config.get('production.scanned_roots', root))
    suffixes = config.get('production.scanned_suffixes', root)
    errors = []
    for path, lines in sorted(files.items()):
        if path.startswith(roots) and Path(path).suffix in suffixes:
            for where, name, text in mentions(path, lines, entrypoints, allowed):
                errors.append(f'production: {where} adds a mention of scripts/{name} ({text[:80]!r}); a session never '
                              f'runs production entrypoints (D-054); queue the change in docs/process/host-swap-queue.md')
    return errors, []


def run_check(args):
    """The "production guard" stage: FAIL per error, WARN per warning, a summary line; exit 1 on an error."""
    parser = argparse.ArgumentParser(prog='production_guard.py check')
    parser.add_argument('--base')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[2]))
    parsed = parser.parse_args(args)
    errors, warnings = check(parsed.root, parsed.base)
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    scope = f'diff {parsed.base}...HEAD' if parsed.base else 'no base, nothing to diff'
    print(f'production guard ({scope}): {len(errors)} error(s), {len(warnings)} warning(s)')
    return 1 if errors else 0


def main(argv):
    if len(argv) == 3 and argv[1] == 'refuse':
        refused = refusal(argv[2])
        if refused:
            print(refused[0], file=sys.stderr)
            return refused[1]
        return 0
    if len(argv) >= 2 and argv[1] == 'check':
        return run_check(argv[2:])
    print('usage: production_guard.py refuse <entrypoint> | check [--base SHA] [--root PATH]', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
