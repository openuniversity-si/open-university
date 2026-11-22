"""The rows of the decision table, rendered from the decision records (D1, D-217).

A record is docs/domain/decisions/D-NNN.md: front matter (number, time, premises, proof) and the text. A row has the table's six
columns: Id, Date, Decision, Invariant, Proof (test), Status. The table itself is not written here: the step that writes it
replaces the hand-kept rows, so this module only renders and checks.
"""
import argparse
from pathlib import Path
import posixpath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
RECORDS = 'docs/domain/decisions'
FRONT = re.compile(r'^---\n(.*?)\n---\n', re.S)
ID = re.compile(r'^D-(\d+)$')
GRANDFATHERED = 'docs/domain/decisions/handwritten.txt'  # the rows written by hand before the records were the only path (one id per line)


STATUSES = ('proposed', 'accepted', 'recorded', 'deprecated', 'superseded')


def parse(text):
    """{number, time, premises, proof, body} of one record; raises ValueError when the front matter is incomplete."""
    found = FRONT.match(text)
    if not found:
        raise ValueError('a record starts with its front matter')
    fields = {}
    for line in found.group(1).splitlines():
        key, _sep, value = line.partition(': ')
        fields[key.strip()] = value.strip()
    for key in ('number', 'time', 'premises', 'proof'):
        if not fields.get(key):
            raise ValueError(f'the record has no {key}')
    if not ID.match(fields['number']):
        raise ValueError(f"the number {fields['number']} is not D-NNN")
    if fields.get('status') and fields['status'].lower() not in STATUSES:
        raise ValueError(f"the status {fields['status']} is not one of {', '.join(STATUSES)}")
    return dict(fields, body=text[found.end():].strip())


BARE_PATH = re.compile(r'scripts/[\w./-]+')


def cell(text):
    """One cell of a row: one line, and a pipe becomes a slash (the table reader splits on pipes, escaped or not, so an
    escape would add a column and the structure check refuses a row without six)."""
    return ' '.join(text.split()).replace('|', '/')


LINK = re.compile(r'\]\(([^)\s]+)\)')


def from_table(text):
    """The text with each relative link moved from the record's folder to the table's: a record in docs/domain/decisions
    links `../../units/X`, and the same file seen from docs/domain/DECISIONS.md is `../units/X`."""
    def move(found):
        target = found.group(1)
        if re.match(r'^([a-z][a-z0-9+.-]*:|#|/)', target, re.I):
            return found.group()
        return f']({posixpath.normpath(posixpath.join(posixpath.basename(RECORDS), target))})'
    return LINK.sub(move, text)


def proof_cell(proof):
    """The proof cell: a bare path that is not a `.test.` script is quoted, so the structure check's rite C5 reads it as the
    linked test (it finds a `.test.` file or a quoted `scripts/` path); a quoted path and a `.test.` script are kept as written."""
    parts = cell(proof).split('`')
    for index in range(0, len(parts), 2):
        parts[index] = BARE_PATH.sub(lambda found: found.group() if '.test.' in found.group() else f'`{found.group()}`', parts[index])
    return '`'.join(parts)


def row(record):
    """The table row of one record: every cell is one line with no pipe, and the proof names its test as the structure
    check reads it."""
    status = cell(record['status'].lower()) if record.get('status') else 'recorded'
    return (f"| {record['number']} | {cell(record['time'])} | {cell(from_table(record['body']))} | Premises: {cell(record['premises'])} "
            f"| {proof_cell(record['proof'])} | {status} |")


def render(records):
    """The rows of the records, in number order."""
    return [row(record) for record in sorted(records, key=lambda record: int(ID.match(record['number']).group(1)))]


def load(root=ROOT):
    """Every record of the folder, parsed; a record that does not parse is named in the error."""
    records = []
    for path in sorted((Path(root) / RECORDS).glob('D-*.md')):
        try:
            records.append(parse(path.read_text()))
        except ValueError as error:
            raise ValueError(f'{path.name}: {error}') from None
    return records


def missing(records, table_text):
    """The records whose row is not in the table text (their number has no row, or its row differs): the drift to fix."""
    rows = set(line.strip() for line in table_text.splitlines())
    return [record['number'] for record in records if row(record) not in rows]


def duplicates(table_text):
    """The ids written in two or more rows of the table, in number order: a row is a line that starts with its id (`| D-NNN |`)."""
    counts = {}
    for line in table_text.splitlines():
        found = re.match(r'^\| (D-\d+) \|', line)
        if found:
            counts[found.group(1)] = counts.get(found.group(1), 0) + 1
    return sorted((number for number, count in counts.items() if count > 1), key=lambda number: int(number.split('-')[1]))


def handwritten(table_text, records, allowed=()):
    """The ids of rows written by hand: a row of DECISIONS.md at or after the first record whose id has no record and is not
    one of the grandfathered rows. The records are the only path to a new decision (scripts/decision-record), so a new row
    typed into the table is refused; a row older than the first record predates the records and is not judged."""
    if not records:
        return []
    first = min(int(ID.match(record['number']).group(1)) for record in records)
    have = {record['number'] for record in records} | set(allowed)
    found = (re.match(r'^\| (D-\d+) \|', line) for line in table_text.splitlines())
    return sorted({match.group(1) for match in found if match and match.group(1) not in have
                   and int(match.group(1).split('-')[1]) >= first}, key=lambda number: int(number.split('-')[1]))


def grandfathered(root=ROOT):
    """The ids of the rows written by hand before the records were the only path: one id per line, # for comments."""
    path = Path(root) / GRANDFATHERED
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]


def ids(table_text):
    """The numbers of the rows of the table, one per row: a row is a line that starts with its id (`| D-NNN |`)."""
    return set(int(found.group(1)) for found in (re.match(r'^\| D-(\d+) \|', line) for line in table_text.splitlines()) if found)


def lost(previous_text, table_text):
    """The numbers the previous table had and this one has not: a renumbered row leaves its old number empty, a gap no
    decision ever closes. Ids are never removed from the register, so any number here is refused."""
    gone = sorted(ids(previous_text) - ids(table_text))
    return [f'D-{number}' for number in gone]


def previous_table(base, root=ROOT):
    """The register as the base has it (git show base:docs/domain/DECISIONS.md), or None when the base cannot be read."""
    try:
        return subprocess.run(['git', '-C', str(root), 'show', f'{base}:docs/domain/DECISIONS.md'], capture_output=True, text=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def with_missing(table_text, records):
    """The table text with the row of every record it lacks, appended after its last row; the rows already there are never
    touched, so a write adds and never rewrites. Idempotent: a second write adds nothing."""
    lines = table_text.split('\n')
    have = set(line.strip() for line in lines)
    adding = [row(record) for record in sorted(records, key=lambda record: int(ID.match(record['number']).group(1)))
              if row(record) not in have]
    if not adding:
        return table_text
    last = max(index for index, line in enumerate(lines) if line.startswith('| '))
    return '\n'.join(lines[:last + 1] + adding + lines[last + 1:])


TABLE = 'docs/domain/DECISIONS.md'


def typed_rows(root, records):
    """The refusals of rows written by hand in the table (an id with no record, after the first record, not grandfathered)."""
    table = (Path(root) / TABLE).read_text()
    return [f'{number}: a row written by hand in DECISIONS.md with no record; write the decision with scripts/decision-record'
            for number in handwritten(table, records, grandfathered(root))]


def drift(root, records, before=None):
    """Every refusal of --check: a row by hand, an id written twice, an id the previous register had and this one lost (only
    when `before` is given), and a record with no matching row. Empty when the table is in step with the records. One call
    with no output: the pre-push local check `decision_table` (local_checks.decision_table_in_step) runs it on a push
    that changes a record or the table."""
    table = (Path(root) / TABLE).read_text()
    found = typed_rows(root, records)
    found += [f'{number}: written twice in DECISIONS.md, the id must have one row' for number in duplicates(table)]
    if before is not None:
        found += [f'{number}: the register had it and this one does not; a renumbered id leaves a gap, and ids are never removed'
                  for number in lost(before, table)]
    found += [f'{number}: its record has no matching row in DECISIONS.md; add it with scripts/decision-table --write'
              for number in missing(records, table)]
    return found


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/decision-table', description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='exit 1 when a record has no row in docs/domain/DECISIONS.md, or a different one, or an id is written twice there')
    parser.add_argument('--handwritten', action='store_true', help='exit 1 when DECISIONS.md has a row written by hand: an id after the first record with no record and not grandfathered (use scripts/decision-record)')
    parser.add_argument('--write', action='store_true', help='add the missing rows to docs/domain/DECISIONS.md; never rewrites a row')
    parser.add_argument('--base', default='mod/roadmap-integration', help='the ref whose register --check compares with, so a renumbered id is refused')
    parser.add_argument('--previous', help='the register to compare with, as a file (instead of --base)')
    args = parser.parse_args(argv)
    records = load(root)
    if args.write:
        target = Path(root) / 'docs/domain/DECISIONS.md'
        before = target.read_text()
        taken = ids(before)
        clashes = [record['number'] for record in records
                   if int(ID.match(record['number']).group(1)) in taken and row(record) not in set(line.strip() for line in before.splitlines())]
        if clashes:
            for number in clashes:
                print(f'{number}: the register has another row under this number; the write adds nothing (claim a free number)')
            return 1
        after = with_missing(before, records)
        target.write_text(after)
        print(f'{after.count('\n') - before.count('\n')} row(s) added')
        return 0
    if args.handwritten:
        typed = typed_rows(root, records)
        for line in typed:
            print(line)
        return 1 if typed else 0
    if args.check:
        before = Path(args.previous).read_text() if args.previous else previous_table(args.base, root)
        found = drift(root, records, before)
        for line in found:
            print(line)
        if before is None:
            print(f'the register of {args.base} cannot be read; pass --previous FILE to compare')
            return 1
        gone = missing(records, (Path(root) / TABLE).read_text())
        print(f'{len(records) - len(gone)} of {len(records)} record(s) have their row')
        return 1 if found else 0
    for line in render(records):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
