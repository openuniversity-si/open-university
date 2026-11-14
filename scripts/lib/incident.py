"""Incidents (D-231): every refusal and every stop is one record, docs/operations/incidents/I-<id>.md, with its case, class and
design fix. The id is a hash of the kind and the text plus the clock, so two lanes never write the same name.

`scripts/incident open KIND TEXT` writes a record; `list` prints the open ones (id, state, root cause); `show ID` prints one record; `close ID FIX` marks one closed with its fix.
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FOLDER = 'docs/operations/incidents'
STATUS = re.compile(r'^status: (\w+)$', re.M)


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


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/incident', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='action', required=True)
    o = sub.add_parser('open'); o.add_argument('kind'); o.add_argument('text')
    sub.add_parser('list')
    w = sub.add_parser('show'); w.add_argument('id')
    c = sub.add_parser('close'); c.add_argument('id'); c.add_argument('fix')
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
    else:
        print(close(root, args.id, args.fix))
    return 0


if __name__ == '__main__':
    sys.exit(main())
