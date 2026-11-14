"""Tier policy of the gate, one place (GX-39 seam; GX-11, D-070).

The tier is explicit: gate-hooks/tier.sh derives it from the invocation with `derive` (D-B5, the keys
gate-tier.battery, per_pr, batch, working_tree: --tier3 3, --pr 1, --sha without --pr 2, the working tree 1) and
exports it as OU_GATE_TIER, bound to the tooling that derived it (`<tier>@<its scripts/lib>`): a process of another
checkout (the code under test of a pinned run, a nested test) ignores it, so the tier never leaks into the code it
judges. With a tier, the registry decides: gate-tier.cacheable_tiers
which tiers may use box-local markers (D-065 (5): tiers 2 and 3 never do), gate-tier.content_cacheable_tiers which
reuse a script-test or stage PASS by content (D-076: tiers 1 and 2; tier 3 never), forge-events.adjudicated_tiers which
adjudicate known base defects (KD1). Without one (a caller outside gate-local, a unit test) the mode-based behaviour
of GX-39 stays: the callers pass the modes in (the deprecated forge-events.tier1_gate_modes), so no reader breaks."""
import argparse
import os
import sys

import config

ENV = 'OU_GATE_TIER'
LIB = os.path.dirname(os.path.realpath(__file__))  # this tooling's scripts/lib, the binding of OU_GATE_TIER


def derive(pr, sha, tier3):
    """The tier of a gate-local invocation (its parsed `pr`, `sha` and `tier3` flag), first match wins."""
    if tier3:
        return config.get('gate-tier.battery')
    if pr:
        return config.get('gate-tier.per_pr')
    return config.get('gate-tier.batch' if sha else 'gate-tier.working_tree')


def bind(tier):
    """The OU_GATE_TIER value of a tier derived by this tooling."""
    return f'{tier}@{LIB}'


def explicit(environ=None):
    """The tier the hook derived (a positive integer: 1 per-PR, 2 batch, 3 battery) for this tooling, or None when no
    gate-local run set one, the value names another tooling's scripts/lib, or it is not a positive integer. An unknown
    tier is in no registry list: never cached or adjudicated."""
    value, _, lib = (os.environ if environ is None else environ).get(ENV, '').strip().partition('@')
    return int(value) if value.isdigit() and int(value) > 0 and lib == LIB else None


def current(mode, tier1_modes):
    """The verdict's `tier`: the explicit tier, else tier 1 for a mode the caller lists as tier 1, else None."""
    tier = explicit()
    if tier is not None:
        return tier
    return 1 if mode in tier1_modes else None


def content_cacheable(tier=None):
    """D-076 (P-56): True when the tier reuses results by content (gate-tier.content_cacheable_tiers, with
    gate.content_cache_enabled on). Tier 3, an unknown tier and the rollback never do."""
    tier = explicit() if tier is None else tier
    return (tier is not None and config.get('gate.content_cache_enabled')
            and tier in config.get('gate-tier.content_cacheable_tiers'))


def cacheable(mode, tier1_modes):
    """True when the run may reuse the stage/step result cache: a cacheable or content-cacheable tier and, as before,
    a listed mode. The mode test stays so no mode gains a cache; tier 3 never uses one (D-065 (5), D-076)."""
    tier = explicit()
    if tier is None:
        return mode in tier1_modes
    return (tier in config.get('gate-tier.cacheable_tiers') or content_cacheable(tier)) and mode in tier1_modes


def script_tests_cacheable():
    """True when the per-test script cache may read and write markers: a cacheable or content-cacheable tier, or no
    gate tier at all."""
    tier = explicit()
    return tier is None or tier in config.get('gate-tier.cacheable_tiers') or bool(content_cacheable(tier))


def adjudicated(mode, tier1_modes):
    """True when the run adjudicates known base defects and reports them (KD1): its tier is in
    forge-events.adjudicated_tiers; without an explicit tier, the mode is one the caller lists."""
    tier = explicit()
    if tier is None:
        return mode in tier1_modes
    return tier in config.get('forge-events.adjudicated_tiers')


def main(argv):
    """`gate_tier.py derive <pr> <sha> <tier3 flag>` prints the bound tier (the tier hook's one call)."""
    parser = argparse.ArgumentParser(prog='gate_tier', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    deriving = commands.add_parser('derive')
    for name in ('pr', 'sha', 'tier3'):
        deriving.add_argument(name)
    args = parser.parse_args(argv[1:])
    print(bind(derive(args.pr, args.sha, args.tier3 not in ('', '0'))))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
