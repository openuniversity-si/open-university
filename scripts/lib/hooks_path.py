"""The checkout's versioned git hooks (X1, D-022; D-237; D-322): point core.hooksPath at push-guard.hooks_path.

The machine bootstrap's step (engine-cloud): scripts/cloud/env.sh runs it when the checkout has no hooks path, so a
session that sources env.sh gets the pre-commit stage and the auto-push hook. The hooks themselves are delivery's
(push_guard.py, which re-exports install with its own options); this module reads only the registry value.

  hooks_path.py install [--root DIR]    set core.hooksPath when the checkout has none; prints `push-guard: <result>`
"""
import argparse
from pathlib import Path
import subprocess
import sys

import config

ROOT = Path(__file__).resolve().parent.parent.parent


def install(root, hooks_path):
    """Point core.hooksPath at the versioned hooks unless the checkout already has its own hooks path."""
    current = subprocess.run(['git', '-C', str(root), 'config', '--get', 'core.hooksPath'],
                             capture_output=True, text=True).stdout.strip()
    if current == hooks_path:
        return 'installed'
    if current:
        print(f'push-guard: core.hooksPath is {current}, not {hooks_path}; the auto-push hook is not active',
              file=sys.stderr)
        return 'kept'
    if not (Path(root) / hooks_path).is_dir():
        return 'absent'
    subprocess.run(['git', '-C', str(root), 'config', 'core.hooksPath', hooks_path], capture_output=True, text=True)
    return 'installed'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hooks_path.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('install').add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    print(f'push-guard: {install(args.root, config.get("push-guard.hooks_path"))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
