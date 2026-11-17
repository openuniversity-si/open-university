"""Retired products (OU-DECOUPLE F5, D-113), a module of scripts/structure-check.

The engine names no product it retired (D-105, D-112). check(root) returns the errors of:
  path      a tracked path under a root of structure.retired_product_roots: the product left, so nothing returns there;
  mention   a tracked text file outside structure.record_globs that names such a root: acting code, config, tests and
            living docs describe the engine as it is; the historical records (structure.record_globs) keep the past.
One `git grep` (a fixed string per root) finds the mentions. Every word is a registry entry (config/registry/structure/).
"""
from pathlib import Path
import subprocess

import config
from globs import glob_match


def check(root):
    root = Path(root)
    roots = config.get('structure.retired_product_roots')
    records = config.get('structure.record_globs')
    if not roots:
        return []
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True)
    if listed.returncode != 0:
        return []
    paths = [path for path in listed.stdout.decode().split('\0') if path]
    errors = [f'{path}: lies under the retired product root {top} (structure.retired_product_roots)'
              for path in paths for top in roots if path == top or path.startswith(top.rstrip('/') + '/')]
    args = ['git', '-C', str(root), 'grep', '-I', '-l', '-F']
    for top in roots:
        args += ['-e', top]
    named = subprocess.run(args + ['--', '.'], capture_output=True, text=True).stdout.split()
    errors += [f'{path}: names a retired product root ({", ".join(roots)}); the engine names no retired product, and only '
               f'the records of structure.record_globs keep it (D-113)'
               for path in named if not any(glob_match(path, pattern) for pattern in records)]
    return errors
