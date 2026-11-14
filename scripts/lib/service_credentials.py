"""Which runner holds which secret (D-291 (5), TRAIN-DEFINITIVE R6): the inventory service.token_holders, read here.

Each entry names an environment variable, what it must equal (the control-plane secret it mirrors, or the account it
is a token of), the runner kinds that need it (OU_RUNNER_KIND), the file that holds it on the runner and what it is
used for. A rotation updates every holder the inventory lists, then restarts the runner. Nothing here reads a value:
only whether a variable is set, so no sentence can carry a secret.

Library: entries(root), entry(variable, root), missing(environ, kind, entries), refused_sentence(variable, status,
by, entries), inventory_lines(entries). `python3 scripts/lib/service_credentials.py [--kind KIND]` prints the
inventory and, with --kind, every variable this environment lacks for that kind (exit 1 when one is missing).
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
KEY = 'service.token_holders'


def entries(root=ROOT):
    """The inventory: one dict per variable (variable, equals, kinds, holder, used_for, optional aliases)."""
    return config.get(KEY, root)


def entry(variable, root=ROOT, items=None):
    """The inventory's entry for `variable` (or one of its aliases), else None."""
    for item in entries(root) if items is None else items:
        if variable == item['variable'] or variable in item.get('aliases', ()):
            return item
    return None


def _names(item):
    return [item['variable'], *item.get('aliases', ())]


def absent_sentence(item):
    """The sentence for an entry whose variable is not set."""
    also = ''.join(f' (or {alias})' for alias in item.get('aliases', ()))
    return (f'{item["variable"]}{also} is not set: it must be {item["equals"]}, held in {item["holder"]}; '
            f'it is used for {item["used_for"]} ({KEY})')


def missing(environ, kind, entries=None):
    """One sentence per inventory variable the runner kind `kind` needs and `environ` does not hold (an empty value is
    absent). `kind` None judges every entry given."""
    items = globals()['entries']() if entries is None else entries
    return [absent_sentence(item) for item in items
            if (kind is None or kind in item['kinds']) and not any(environ.get(name) for name in _names(item))]


def refused_sentence(variable, status, by='the control plane', entries=None):
    """The sentence for a token `by` refused with HTTP `status`: the secret it must equal was rotated or its holder is
    stale, and where to update it. Never the value."""
    item = entry(variable, items=entries)
    if item is None:
        return (f'{by} refused {variable} ({status}): it is not in the inventory {KEY}; add it there, then update '
                f'its holder and restart the runner')
    return (f'{by} refused {variable} ({status}): it is not {item["equals"]}; the secret was rotated or the holder '
            f'is stale: update {item["holder"]} and restart the runner')


def inventory_lines(entries=None):
    """The inventory as printable lines, one per variable."""
    items = globals()['entries']() if entries is None else entries
    return [f'{" or ".join(_names(item))} = {item["equals"]}; kinds {", ".join(item["kinds"])}; '
            f'holder {item["holder"]}; used for {item["used_for"]}' for item in items]


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description='The inventory of a runner\'s secrets (service.token_holders).')
    parser.add_argument('--kind', help='also name every variable this environment lacks for this runner kind')
    args = parser.parse_args(argv)
    for line in inventory_lines():
        print(line)
    if args.kind is None:
        return 0
    absent = missing(os.environ if environ is None else environ, args.kind)
    for sentence in absent:
        print(f'missing: {sentence}', file=sys.stderr)
    return 1 if absent else 0


if __name__ == '__main__':
    sys.exit(main())
