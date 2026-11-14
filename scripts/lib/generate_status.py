"""The status target of scripts/generate (D-067, D-069 item 1, plan v3 U1): the unit status report, on demand.

docs/process/roadmap/STATUS.md is the hand-written step log of the modularity roadmap (D-054) and stays as history.
What a status page should say now is derived: which units exist, who owns them, and how far each has come in the
migration (a contract version, a battery command, intents served). That is a pure function of the manifests, so it is
rendered here and never committed: `scripts/generate status` prints it, `--out DIR` writes it.
"""
from collections import Counter

import units

PATH = 'docs/process/roadmap/STATUS-UNITS.md'


def mark(value):
    return f'`{value}`' if value else '—'


def render(root, target):
    manifests = units.manifests(root)
    done = Counter()
    lines = ['# Unit status', '',
             'Generated from `units/<id>/unit.json` by `scripts/generate status`; nothing commits it (D-067, U1). '
             'The step log of the modularity roadmap stays in [STATUS.md](STATUS.md).', '',
             '| Unit | Cell | Owner | Paths | Contract | Battery | Intents |', '|---|---|---|---|---|---|---|']
    for name, manifest in sorted(manifests.items()):
        contract = (manifest.get('contract') or {}).get('version')
        battery = (manifest.get('battery') or {}).get('command')
        done['contract'] += bool(contract)
        done['battery'] += bool(battery)
        lines.append(f'| `{name}` | {manifest["cell"]} | {manifest["owner"]} | {len(manifest["paths"])} | '
                     f'{mark(contract)} | {mark(battery)} | {len(manifest.get("intents") or []) or "—"} |')
    lines += ['', f'{len(manifests)} units; {done["contract"]} with a contract, {done["battery"]} with a battery.']
    return {PATH: '\n'.join(lines) + '\n'}
