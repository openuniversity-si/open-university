"""The real gate's newest result for the base tip, read by the train before it merges (unit R1, docs/units/R1/plan.md).

`gate-shadow run` writes `.gate/shadow/<sha>.json` in the checkout it gates. The train reads the same file in its own
checkout, so a train host that runs the shadow there sees the result (plan.md, R2 A1). A tip with no result, or a result
for another sha, is 'unknown': it is reported and never held, so a host without a shadow cannot stall the train. A red
result holds the queue until the tip is released by name (train.base_hold_release, set with scripts/config set, recorded
in its history) or the base moves to a tip whose result is green.
"""
import json
from pathlib import Path

RED, GREEN, UNKNOWN, RELEASED = 'red', 'green', 'unknown', 'released'


def result_path(root, tip):
    """Where `gate-shadow` writes the real result of `tip` in the checkout at `root`."""
    return Path(root) / '.gate' / 'shadow' / f'{tip}.json'


def verdict(root, tip, release=''):
    """(state, failing stages) of the newest real result of `tip` on this host. A tip named by `release` is released:
    it runs whatever its result says."""
    if release and release == tip:
        return RELEASED, []
    try:
        result = json.loads(result_path(root, tip).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return UNKNOWN, []
    if not isinstance(result, dict) or result.get('sha') != tip:
        return UNKNOWN, []
    if result.get('passed') is True:
        return GREEN, []
    return RED, [str(name) for name in result.get('failing') or []]
