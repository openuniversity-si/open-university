"""Rule-challenge records (D-138): `scripts/rule-challenge list|check` over docs/process/rule-challenges/RC-NNN.md.

A record is a title line `# RC-NNN — title` followed by `- Key: value` lines (README.md lists them). `check` returns the
problems as strings, empty when every record is sound.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
FOLDER = 'docs/process/rule-challenges'
KEYS = ('Grade', 'Status', 'Rule', 'Evidence', 'Harm', 'Proposal', 'Impact', 'Decision', 'D')
GRADES = ('1', '2', '3')
STATUSES = ('open', 'changed', 'lifted', 'upheld', 'escalated')
TITLE = re.compile(r'^# RC-(?P<number>\d+) — \S')
LINE = re.compile(r'^- (?P<key>\w+):[ ]?(?P<value>.*)$')
DECISION = re.compile(r'D-\d+')


def records(root):
    """[(path, number or None, {key: value})] in file-name order."""
    found = []
    for path in sorted((Path(root) / FOLDER).glob('RC-*.md')):
        lines = path.read_text().splitlines()
        title = TITLE.match(lines[0]) if lines else None
        fields = {}
        for line in lines[1:]:
            match = LINE.match(line)
            if match:
                fields.setdefault(match['key'], match['value'].strip())
        found.append((path, int(title['number']) if title else None, fields))
    return found


def check(root):
    problems = []
    expected = 1
    for path, number, fields in records(root):
        name = path.name
        if number is None or path.stem != f'RC-{number:03d}':
            problems.append(f'{name}: the title line must be `# RC-NNN — title` matching the file name')
        elif number != expected:
            problems.append(f'{name}: the number is not the next free one ({expected:03d})')
        expected += 1
        missing = [key for key in KEYS if key not in fields]
        if missing:
            problems.append(f'{name}: missing line(s): {", ".join(missing)}')
            continue
        if fields['Grade'] not in GRADES:
            problems.append(f'{name}: Grade must be one of {", ".join(GRADES)}')
        if fields['Status'] not in STATUSES:
            problems.append(f'{name}: Status must be one of {", ".join(STATUSES)}')
        if fields['Status'] != 'open' and not fields['Decision']:
            problems.append(f'{name}: a record that is not open needs a Decision')
        if fields['Grade'] == '1' and not DECISION.search(fields['D']):
            problems.append(f'{name}: a grade 1 change records a D-NNN')
        if fields['Grade'] == '3' and fields['Status'] in ('changed', 'lifted') and 'Daniel' not in fields['Decision']:
            problems.append(f'{name}: a grade 3 rule changes only by Daniel')
    return problems


def listing(root):
    rows = []
    for path, _number, fields in records(root):
        waiting = fields.get('Status') == 'open' and fields.get('Grade') in GRADES[1:]
        title = path.read_text().splitlines()[0]
        rows.append((not waiting, f"{title}  [grade {fields.get('Grade', '?')}, {fields.get('Status', '?')}]"))
    return [text for _, text in sorted(rows)]


def main(argv=None):
    command = (argv if argv is not None else sys.argv[1:])[:1]
    if command == ['list']:
        rows = listing(ROOT)
        print('\n'.join(rows) if rows else 'no rule challenges')
        return 0
    if command == ['check']:
        problems = check(ROOT)
        print('\n'.join(problems) if problems else f'rule-challenge: {len(records(ROOT))} record(s) sound')
        return 1 if problems else 0
    raise SystemExit('Usage: scripts/rule-challenge list|check')


if __name__ == '__main__':
    sys.exit(main())
