"""The gate's "gate maps" stage (D-322): the checks of the gate's own maps, run by the gate, not by the structure check.

The structure check (planning, layer 1) imports nothing of the gate (layer 2): the checks that judge the gate's data run
here, as an always-run stage after it, the way the production guard does (D-054, D-322):
  area coverage   every tracked path of the checkout belongs to an area of gate-areas.json (gate_areas, D-106);
  test orphans    every Python test is run by exactly one wrapper of the script suite (test_orphans, TX25);
  hermetic tests  no unit or script test reads the wall clock, an unseeded random source or a host (hermetic_check, H1).

check(root, base) returns (errors, warnings); `python3 gate_maps.py check [--base B] [--root R]` prints FAIL/WARN lines and a
summary, and exits 1 on an error.
"""
import argparse
from pathlib import Path
import sys

import gate_areas
import hermetic_check
import script_covers
import test_orphans


def check(root, base=None):
    errors = list(gate_areas.coverage_errors(root))  # OU-DECOUPLE F1 (D-106): every tracked path has an area
    errors += test_orphans.check(root)  # TX25: every test_*.py is run by exactly one wrapper
    hermetic_errors, warnings = hermetic_check.check(root, base)  # plan v3 H1, D-069 item 5
    traced_errors, traced_warnings = script_covers.traced_findings(root)  # C6: traced-covers integrity & freshness
    return errors + list(hermetic_errors) + list(traced_errors), list(warnings) + list(traced_warnings)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='gate_maps.py check', description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--base')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors, warnings = check(args.root, args.base)
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    scope = f'against {args.base}' if args.base else 'no base'
    print(f'gate maps ({scope}): {len(errors)} error(s), {len(warnings)} warning(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
