"""The command line of the unit manifests (D-067): scripts/units owner <path>... | who <unit>... | list | check |
propose | measure. The lookups are scripts/lib/units.py (layer 0, D-322); propose and measure are the map generator
(scripts/lib/unit_map.py) and check --fix-requires the ownership check (scripts/lib/unit_check.py), both of the
planning layer, so the command line lives here and units.py imports neither.
"""
import argparse
from pathlib import Path
import sys

import units


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/units', description=units.__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, help='repository (default: this checkout)')
    commands = parser.add_subparsers(dest='command', required=True)
    owner = commands.add_parser('owner', help='the unit and owner of each path')
    owner.add_argument('paths', nargs='+')
    who = commands.add_parser('who', help='the owner of each unit')
    who.add_argument('units', nargs='+')
    commands.add_parser('list', help='every unit with its cell and owner')
    check = commands.add_parser('check', help='validate every manifest')
    check.add_argument('--fix-requires', action='store_true',
                       help='rewrite each manifest\'s requires to the measured import graph, then check')
    for name, text in (('propose', 'the generator\'s cut of the production files (scripts/lib/unit_map.py)'),
                       ('measure', 'each manifest\'s lines, closure and cohesion against its budget')):
        command = commands.add_parser(name, help=text)
        command.add_argument('--json', action='store_true', help='print JSON rows')
        if name == 'measure':
            command.add_argument('--emit', action='store_true',
                                 help='publish engine.step.measured and unit.oversize through the forge_events port')
            command.add_argument('--pr', type=int, help='the change the events are about (default: the repository)')
    args = parser.parse_args(argv)
    root = args.root
    if args.command in ('propose', 'measure'):
        import unit_map  # the generator reads the git log; the lookups above never need it
        return unit_map.main(args.command, args.json, root, getattr(args, 'pr', None), getattr(args, 'emit', False))
    if args.command == 'check':
        if args.fix_requires:
            import unit_check  # reads the git tree and the import graph; plain validation never needs it
            for line in unit_check.fix_requires(root or units.ROOT):
                print('FIXED ' + line)
        found, errors = units.read(root)
        for line in errors:
            print('FAIL ' + line)
        print(f'units: {len(found)} valid manifest(s), {len(errors)} error(s)')
        return 1 if errors else 0
    return units.lookup(args.command, getattr(args, 'paths', None) or getattr(args, 'units', None) or [], root)

if __name__ == '__main__':
    sys.exit(main())
