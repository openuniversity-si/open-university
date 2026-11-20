"""Incidents (D-231): every refusal and every stop is one record, docs/operations/incidents/I-<id>.md, with its case, class and
design fix. The id is a hash of the kind and the text plus the clock, so two lanes never write the same name.

`scripts/incident open KIND TEXT` writes a record; `list` prints the open ones (id, state, root cause); `show ID` prints one record; `close ID FIX` marks one closed with its fix; `snapshot` exports metadata-only entries (no prose) to config/validation/incidents.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FOLDER = 'docs/operations/incidents'
SNAPSHOT = 'config/validation/incidents.json'
STATUS = re.compile(r'^status: (\w+)$', re.M)
FRONT_FIELD = re.compile(r'^(id|kind|time|status): (\S+)$', re.M)


def new_id(kind, text, when):
    digest = hashlib.sha256(f'{kind}|{text}|{when}'.encode()).hexdigest()
    return 'I-' + digest[:len('abcdefgh')]


def record(identifier, kind, text, when, status='open', case='', cls='', design=''):
    return (f'---\nid: {identifier}\nkind: {kind}\ntime: {when}\nstatus: {status}\n---\n\n{text.strip()}\n\n'
            f'## Case\n{case or "(to be decided)"}\n\n## Class\n{cls or "(to be decided)"}\n\n## Design\n{design or "(to be decided)"}\n')


def open_incident(root, kind, text, when=None):
    when = when or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    identifier = new_id(kind, text, when)
    path = Path(root) / FOLDER / f'{identifier}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(record(identifier, kind, text, when))
    return identifier


def listing(root):
    out = []
    for path in sorted((Path(root) / FOLDER).glob('I-*.md')):
        text = path.read_text()
        found = STATUS.search(text)
        if found and found.group(1) == 'open':
            out.append(path.stem)
    return out


def section(text, name):
    found = re.search(rf'^## {name}\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    value = found.group(1).strip() if found else ''
    return '' if value == '(to be decided)' else value


def cause(text):
    return (section(text, 'Case') or section(text, 'Class') or '(none yet)').splitlines()[0]


def rows(root):
    out = []
    for identifier in listing(root):
        text = (Path(root) / FOLDER / f'{identifier}.md').read_text()
        out.append(f'{identifier}\topen\t{cause(text)}')
    return out


def show(root, identifier):
    return (Path(root) / FOLDER / f'{identifier}.md').read_text()


def close(root, identifier, fix):
    path = Path(root) / FOLDER / f'{identifier}.md'
    text = path.read_text().replace('status: open', 'status: closed', 1)
    path.write_text(text + f'\n## Fix\n{fix.strip()}\n')
    return path


def metadata(root):
    """Metadata-only [{id, kind, time, status}] of every local incident record; never reads body prose."""
    out = []
    for path in sorted((Path(root) / FOLDER).glob('I-*.md')):
        fields = dict(FRONT_FIELD.findall(path.read_text().split('\n---', 1)[0]))
        if fields.get('kind') and fields.get('time'):
            out.append({'id': fields.get('id', path.stem), 'kind': fields['kind'], 'time': fields['time'],
                        'status': fields.get('status', 'open')})
    return out


def write_snapshot(root, now=None):
    """Merge local incident metadata into config/validation/incidents.json (no prose; docs/operations/ stays ignored)."""
    target = Path(root) / SNAPSHOT
    existing = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text())
            for entry in loaded.get('incidents', []) if isinstance(loaded, dict) else ():
                if isinstance(entry, dict) and entry.get('id'):
                    existing[entry['id']] = entry
        except (OSError, ValueError):
            pass
    for entry in metadata(root):
        existing[entry['id']] = entry
    made = {
        'source': 'scripts/incident snapshot (metadata only: id, kind, time, status; docs/operations/ stays gitignored)',
        'at': now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'incidents': sorted(existing.values(), key=lambda item: (item.get('time', ''), item['id'])),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made, indent=1) + '\n')
    return target


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/incident', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='action', required=True)
    o = sub.add_parser('open'); o.add_argument('kind'); o.add_argument('text')
    sub.add_parser('list')
    w = sub.add_parser('show'); w.add_argument('id')
    c = sub.add_parser('close'); c.add_argument('id'); c.add_argument('fix')
    sub.add_parser('snapshot')
    args = parser.parse_args(argv)
    if args.action == 'open':
        print(open_incident(root, args.kind, args.text))
    elif args.action == 'list':
        for row in rows(root):
            print(row)
    elif args.action == 'show':
        try:
            print(show(root, args.id), end='')
        except FileNotFoundError:
            print(f'no incident {args.id}', file=sys.stderr)
            return 1
    elif args.action == 'snapshot':
        print(write_snapshot(root))
    else:
        print(close(root, args.id, args.fix))
    return 0


if __name__ == '__main__':
    sys.exit(main())
