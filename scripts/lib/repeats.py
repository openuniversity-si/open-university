"""The repeated actions of the program (D-208): the open rows of docs/process/repeats.md, by count, most repeated first.

Read by default. With --transcript alone, the measured calls are printed and nothing is written. With --write and --transcript,
the counts of the rows that a session transcript measures are set from it, so no count is typed by hand. A measured count is the
latest measure over the named transcripts (D-254): it is set, up or down, and every measure is appended to
docs/process/repeats-measures.jsonl with the transcripts it names (the history).
A row is open when its status is not `systematised`; the count is the number of times the action was done by hand.
"""
from collections import Counter, namedtuple
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTER = 'docs/process/repeats.md'
LOG = 'docs/process/repeats-measures.jsonl'
COLUMNS = ('action', 'count', 'status', 'where')
COUNT, STATUS = COLUMNS.index('count'), COLUMNS.index('status')

# A row's action -> how a transcript measures it: ('tool', names) counts tool calls by name, ('git', verbs) counts git verbs in
# the shell, ('script', names) counts scripts run from the shell, ('command', names) counts runs of a script with its first
# word ('service health'). Rows not listed here are not measured.
MEASURED = {
    'Syncing a branch with the base (fetch, checkout, merge) by hand': ('git', ('fetch', 'checkout', 'merge')),
    'Running the structure check by hand after each edit': ('script', ('structure-check',)),
    'Running the status commands one by one (flow metrics, lane status, service, coordinator)': (
        'command', ('flow-metrics', 'lane-status', 'service health', 'gate-shadow latest', 'coordinator status', 'decision-next')),
    'Opening a pull request through the GitHub tool': ('tool', ('mcp__github__create_pull_request',)),
    'Messages to other sessions to nudge them': ('tool', ('SendMessage', 'mcp__claude-code-remote__send_message')),
    'Writing a decision row by hand (Edit or Write to DECISIONS.md)': ('file', ('docs/domain/DECISIONS.md',)),
}


def rows(text):
    """[(action, count, status, where)] of the register's table, in the order it is written."""
    out = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) == len(COLUMNS) and cells[1].isdigit():
            action, count, status, where = cells
            out.append((action, int(count), status, where))
    return out


def open_rows(found):
    """The rows that are not systematised, most repeated first."""
    open_ones = [row for row in found if row[STATUS] != 'systematised']
    return sorted(open_ones, key=lambda row: -row[COUNT])


SCRIPT_NAMED = re.compile(r'`(scripts/[a-z][a-z0-9_-]*)')


def unbuilt(found, root):
    """[(action, script)] of the systematised rows that name a script the tree does not have (D-211).

    A row claims its action is systematised by naming the script that does it; a claim whose script is absent is refused, so
    a status is read from the tree, not typed.
    """
    out = []
    for action, _count, status, where in found:
        if not status.startswith('systematised'):
            continue
        for script in sorted(set(SCRIPT_NAMED.findall(where))):
            if not (Path(root) / script).exists():
                out.append((action, script))
    return out


def tally(transcripts):
    """usage.count summed over several session transcripts (one per session, each a path)."""
    total = {'tools': Counter(), 'scripts': Counter(), 'commands': Counter(), 'git': Counter(), 'files': Counter()}
    for path in transcripts:
        with Path(path).open() as handle:
            found = usage.count(handle)
        for key in total:
            total[key].update(found[key])
    return total


def measured(usage_found, how):
    """The number of a transcript's calls that a MEASURED entry counts (usage.count's output)."""
    kind, names = how
    if kind == 'file':  # a file counts when its path ends with the name, so a relative or an absolute path both count
        return sum(number for path, number in usage_found['files'].items() if any(path.endswith(name) for name in names))
    counter = {'tool': usage_found['tools'], 'git': usage_found['git'], 'script': usage_found['scripts'],
               'command': usage_found['commands']}[kind]
    return sum(counter[name] for name in names)


SYNC = 'Syncing a branch with the base (fetch, checkout, merge) by hand'
TOOL = 'scripts/branch-start'
PENDING, ADOPTED = 'adoção pendente', 'adotada'

Round = namedtuple('Round', 'number transcript count calls on_base')


def rounds(text):
    """[Round] of the measures log (D-254): one JSON object a line, in the order they were measured.

    A round is one `--write` of a set of transcripts: its raw count of the sync by hand (not the running maximum of the table),
    the tool calls of those sessions (a count means little without the length of the session it counts in), and whether the
    tool was on the base when it was measured. The log is append-only: a round is never edited.
    """
    out = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if 'round' not in entry:  # a row measure (log_lines) shares the log; it is not a round
            continue
        out.append(Round(entry['round'], entry['transcript'], entry['sync_by_hand'], entry['tool_calls'], entry['on_base']))
    return out


def adoption(found):
    """(state, reason): adotada when the sync by hand per tool call, in the latest round made with the tool on the base, is below
    the rate of the round before it. Rounds made before the tool was on the base say nothing about it and are left out.
    Fewer than two such rounds, or a round with no tool calls, is pending.
    """
    on_base = [row for row in found if row.on_base]
    try:
        *_, before, last = on_base
    except ValueError:
        return PENDING, f'{len(on_base)} round(s) with {TOOL} on the base; two are needed'
    if not before.calls or not last.calls:
        return PENDING, 'a round with no tool calls says nothing about the rate'
    detail = f'{before.count} in {before.calls} tool calls, then {last.count} in {last.calls}'
    # the rates compared without division: last.count / last.calls < before.count / before.calls
    if last.count * before.calls < before.count * last.calls:
        return ADOPTED, f'the sync by hand fell per tool call once {TOOL} was on the base: {detail}'
    return PENDING, f'the sync by hand per tool call did not fall: {detail}'


def add_round(text, transcript, count, calls, on_base):
    """The log text with one round appended: (text, number). Refuses a transcript already measured (ValueError)."""
    found = rounds(text)
    if any(row.transcript == transcript for row in found):
        raise ValueError(f'the transcript {transcript} is already a round')
    number = (found[-1].number if found else 0) + 1
    entry = {'round': number, 'transcript': transcript, 'sync_by_hand': count, 'tool_calls': calls, 'on_base': on_base}
    prefix = text if not text or text.endswith('\n') else text + '\n'
    return prefix + json.dumps(entry, ensure_ascii=False) + '\n', number


def sources(paths):
    """The transcripts a measure names: each by its session id (the file's stem) and the day it was last written."""
    out = []
    for path in paths:
        path = Path(path)
        day = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()
        out.append({'transcript': path.stem, 'modified': day})
    return out


def log_lines(text, named):
    """One JSON line per measured row of the register text: its count and the transcripts (`named`) it was measured from."""
    return [json.dumps({'row': action, 'count': count, 'sources': named}, ensure_ascii=False) + '\n'
            for action, count, _status, _where in rows(text) if action in MEASURED]


def write(text, usage_found):
    """The register text with each measured row's count set to the transcripts' measure, up or down (D-254); other lines unchanged.

    Returns (new text, [(action, old, new)] of the rows that changed).
    """
    changes, out = [], []
    for line in text.splitlines(keepends=True):
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) == len(COLUMNS) and cells[1].isdigit() and cells[0] in MEASURED:
            old = int(cells[1])
            new = measured(usage_found, MEASURED[cells[0]])
            if new != old:
                changes.append((cells[0], old, new))
                cells[1] = str(new)
                line = '| ' + ' | '.join(cells) + ' |' + ('\n' if line.endswith('\n') else '')
        out.append(line)
    return ''.join(out), changes


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/repeats', description=__doc__.split('\n\n')[0])
    parser.add_argument('--write', action='store_true', help='set the measured counts in the register from --transcript')
    parser.add_argument('--transcript', type=Path, action='append', default=[],
                        help='a session transcript (.jsonl) that is measured (printed, or written with --write); repeat it for each session, counts are summed')
    args = parser.parse_args(argv)
    path = Path(root) / REGISTER
    if args.write:
        if not args.transcript:
            parser.error('--write needs --transcript')
        found_now = tally(args.transcript)
        name = '+'.join(p.stem for p in args.transcript)
        log = Path(root) / LOG
        try:
            log_text, number = add_round(log.read_text() if log.exists() else '', name,
                                         measured(found_now, MEASURED[SYNC]), sum(found_now['tools'].values()),
                                         on_base=(Path(root) / TOOL).exists())
        except ValueError as error:
            print(f'refused: {error}')
            return 1
        text, changes = write(path.read_text(), found_now)
        path.write_text(text)
        log.write_text(log_text)
        with log.open('a') as appended:
            appended.writelines(log_lines(text, sources(args.transcript)))
        for action, old, new in changes:
            print(f'{old} -> {new}: {action}')
        print(f'{len(changes)} count(s) written to {REGISTER}; round {number} recorded in {LOG}')
        return 0
    text = path.read_text()
    found = rows(text)
    left = open_rows(found)
    print(f'{len(left)} repeated action(s) still by hand, of {len(found)}:')
    for action, count, status, where in left:
        print(f'- {count}x {action} ({status}); {where}')
    log = Path(root) / LOG
    state, reason = adoption(rounds(log.read_text() if log.exists() else ''))
    print(f'adoption of {TOOL} (D-211): {state}; {reason}')
    missing = unbuilt(found, root)
    for action, script in missing:
        print(f'refused: "{action}" is systematised, but {script} is not in the tree')
    if args.transcript:
        # Read mode measures too: the calls the transcripts hold, per measured row, without touching the register.
        measure = tally(args.transcript)
        print(f'measured in {len(args.transcript)} transcript(s), not written:')
        for action, _, _, _ in found:
            if action in MEASURED:
                print(f'- {measured(measure, MEASURED[action])}x {action}')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
