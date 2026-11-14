"""Per-unit selection for the PR gate (GS1, D-064 (f), D-069 items 5 and 14): which units a diff affects.

The area plan (gate_areas) decides which stages run. This module names the units the changed paths can affect, through
the ownership map (units/*/unit.json, scripts/lib/units.py), and fails closed:

  full    a changed path is in a full-battery class (gate.full_battery_globs: the registry, contracts, the engine, shared
          code, lockfiles and toolchain, the ownership map itself), is not attributed to a unit, or sits outside
          gate.scoped_globs and is not documentation; selection is off; there is no diff
  scoped  every changed path is documentation, a tooling path (gate.reader_scoped_globs, not gate.reader_scoped_exclude)
          or an attributed path under gate.scoped_globs. The affected units are the changed ones plus every unit that
          (transitively) requires one of them. A tooling path adds only its owning unit (D-076)

A deleted or renamed-away path appears in the diff under its old name; unless the head map still attributes it, it is
unattributed and the run is full. The result is data: {kind, reason, paths, units, affected}; the batch gate attributes
failures by it (gate_batch) and the proof records it (gate_proof).

  gate_select.py select --base B --head H [--root R] [--output F]

OU-DECOUPLE F5 (D-113): the web test, `vitest related` and lint arguments (`tests`, `related`, `lint` and the `args`
command) left with Open University's web stages; their registry keys left the registry (VAZÃO F43, D-068 (3) expand
then contract).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import config
import units
from gate_areas import glob_match, load as load_areas

ROOT = Path(__file__).resolve().parents[2]


def setting(name, root):
    return config.get(f'gate.{name}', Path(root))


def _any(path, globs):
    return any(glob_match(path, pattern) for pattern in globs)


def full(reason, paths=()):
    return {'kind': 'full', 'reason': reason, 'paths': sorted(paths), 'units': [], 'affected': []}


def dependents(affected, manifests):
    """The units that require any of `affected`, transitively; plus `affected` itself."""
    found = set(affected)
    grew = True
    while grew:
        grew = False
        for unit, manifest in manifests.items():
            if unit not in found and found & set(manifest.get('requires') or {}):
                found.add(unit)
                grew = True
    return sorted(found)


def tracked(root):
    return subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True,
                          text=True).stdout.split('\0')[:-1]


def select(paths, root=ROOT, areas=None):
    """The selection for one diff (the changed paths, old names included)."""
    root = Path(root)
    paths = sorted({path for path in paths if path})
    if not setting('select_enabled', root):
        return full('selection is off (gate.select_enabled)', paths)
    if not paths:
        return full('no changed paths', paths)
    areas = areas or load_areas()
    classes = setting('full_battery_globs', root)
    scoped = setting('scoped_globs', root)
    manifests = units.manifests(root)
    changed = set()
    tooling = [path for path in paths if _any(path, setting('reader_scoped_globs', root))
               and not _any(path, setting('reader_scoped_exclude', root))]
    for path in paths:
        if path in tooling:  # D-076: its unit and that unit's dependents, never the whole battery
            owner = units.unit_of(path, root)
            if owner is not None:
                changed.add(owner)
            continue
        if _any(path, classes):
            return full(f'full-battery class: {path}', paths)
        if areas.is_documentation(path):
            continue
        owner = units.unit_of(path, root)
        if not _any(path, scoped):
            return full(f'outside the scoped paths: {path}', paths)
        if owner is None:
            return full(f'unattributed path: {path}', paths)
        changed.add(owner)
    if not changed and not tooling:
        return {'kind': 'scoped', 'reason': 'documentation only', 'paths': paths, 'units': [], 'affected': []}
    reason = 'every changed path is documentation or attributed to a unit'
    if tooling:
        reason = 'every changed path is documentation, attributed to a unit or tooling'
    return {'kind': 'scoped', 'reason': reason, 'paths': paths, 'units': sorted(changed),
            'affected': dependents(changed, manifests)}


def changed_paths(root, base, head):
    out = subprocess.run(['git', '-C', str(root), 'diff', '--no-renames', '--name-only', '-z', base + '...' + head],
                         capture_output=True, check=True, text=True).stdout
    return [p for p in out.split('\0') if p]


def main(argv):
    parser = argparse.ArgumentParser(prog='gate_select', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    chosen = commands.add_parser('select')
    chosen.add_argument('--base', required=True)
    chosen.add_argument('--head', required=True)
    chosen.add_argument('--root', default=str(ROOT))
    chosen.add_argument('--output')
    parsed = parser.parse_args(argv[1:])
    try:
        result = select(changed_paths(parsed.root, parsed.base, parsed.head), parsed.root)
    except (subprocess.CalledProcessError, OSError, units.UnitError) as error:
        result = full(f'the diff could not be read: {type(error).__name__}')
    text = json.dumps(result, indent=2)
    if parsed.output:
        Path(parsed.output).write_text(text + '\n')
    print(result['kind'])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
