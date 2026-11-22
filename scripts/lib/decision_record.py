"""One decision as one record (D1, D-217): `scripts/decision-record --text T --premises P --proof PATH` takes the next free number
of this checkout (the table and the records, D-292: no remote claim), takes its time from the machine's clock (BRT), and writes docs/domain/decisions/D-NNN.md. The record is the decision; the table
of docs/domain/DECISIONS.md is to be generated from the records (the next step of D1), so two decisions never edit one file.

Front matter, one key per line, then the text. Then it runs `scripts/decision-table --write`, so the record's row is in
DECISIONS.md in the same step (VAZÃO F75: a record without its row is a decision no PR can cite, and the push is refused).
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import decision_next  # noqa: E402  (brt)
import decision_table  # noqa: E402

RECORDS = 'docs/domain/decisions'


def next_number(root):
    """One past the highest D-NNN in the decisions table and the records of this checkout (D-292: the remote claim
    branch is retired; one session writes the decisions, and a clash is a merge conflict on the same file name)."""
    root = Path(root)
    texts = [(root / 'docs/domain/DECISIONS.md').read_text()] if (root / 'docs/domain/DECISIONS.md').is_file() else []
    texts += [path.name for path in (root / RECORDS).glob('D-*.md')]
    found = [int(n) for text in texts for n in re.findall(r'\bD-(\d{3})\b', text)]
    return max(found, default=0) + 1


def record_text(number, when, text, premises, proof, supersedes='', status=''):
    """The record of one decision as text; `supersedes` (D-NNN, comma separated) names the decisions it replaces, the only
    way an accepted record changes state, since a record is never edited (D-335; scripts/lib/model.py reads it). Optional
    `status` (e.g. `proposed`) marks a record awaiting owner approval without recording it as accepted."""
    head = ['---', f'number: {number}', f'time: {when}', f'premises: {premises}',
            *([f'status: {status}'] if status else []),
            *([f'supersedes: {supersedes}'] if supersedes else []), f'proof: {proof}', '---', '']
    return '\n'.join(head) + text.strip() + '\n'


def write(root, number, when, text, premises, proof, supersedes='', status=''):
    """Write the record; refuses a number that already has one (a decision is never rewritten by a second command)."""
    folder = Path(root) / RECORDS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{number}.md'
    if path.exists():
        raise FileExistsError(f'{path} exists; a decision is written once')
    path.write_text(record_text(number, when, text, premises, proof, supersedes, status))
    return path


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/decision-record', description=__doc__.split('\n\n')[0])
    parser.add_argument('--text', required=True, help='the decision: the rule, the evidence, the consequence')
    parser.add_argument('--premises', default='none')
    parser.add_argument('--proof', required=True, help='a test file that proves the decision')
    parser.add_argument('--supersedes', default='', help='the decisions this one supersedes, D-NNN comma separated (D-335)')
    parser.add_argument('--status', default='', choices=('', 'proposed', 'recorded'),
                        help='optional status front matter (`proposed` when awaiting owner decision)')
    args = parser.parse_args(argv)
    number = next_number(root)
    when = decision_next.brt()
    if args.supersedes and not re.fullmatch(r'D-[0-9]+(?:, ?D-[0-9]+)*', args.supersedes.strip()):
        parser.error(f'--supersedes takes D-NNN, comma separated, not {args.supersedes!r}')
    path = write(root, f'D-{number}', when, args.text, args.premises, args.proof, args.supersedes.strip(), args.status)
    print(path)
    if not (Path(root) / decision_table.TABLE).is_file():
        print(f'{decision_table.TABLE} is missing; no row written (run scripts/decision-table --write)', file=sys.stderr)
        return 1
    return decision_table.main(['--write'], root=root)


if __name__ == '__main__':
    sys.exit(main())
