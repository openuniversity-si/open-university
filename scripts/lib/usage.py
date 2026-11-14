"""What a session did, counted from its transcript (D-208): the tool calls by kind, the scripts run from the shell, and the git verbs.

Read only: a transcript is a JSON-lines file; each tool call is a content block of type tool_use. A count is of the calls, failed
ones included. It says nothing about the other sessions; each has its own transcript.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# A run is a name at the start of a shell segment (after ; && || | newline, a subshell ( or `, or $( ), with optional
# VAR=value prefixes and a wrapper (timeout 300, env, nice -n 5, exec). A name in an argument (rg "x" scripts/y) is not a run,
# and quoted text is data: `python3 -c "print('scripts/x')"` and `echo "scripts/x"` run nothing (D-208).
SEGMENT = re.compile(r'&&|\|\||;|\||\n|\$\(|`|\(')
WRAPPED = r'(?:exec|env|nice|time|timeout)(?:\s+-\S+|\s+\d+[smhd]?)*\s+'
PREFIX = r'(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+|' + WRAPPED + r')*'
SCRIPT = re.compile(r'^\s*' + PREFIX + r'(?:bash\s+|sh\s+)?(?:\./)?scripts/([a-z][a-z0-9_-]+)(?:[ \t]+([a-z][a-z-]*))?')
GIT = re.compile(r'^\s*' + PREFIX + r'git (commit|fetch|log|checkout|merge|push|ls-remote|worktree|branch|rebase)\b')
QUOTED = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")


def matches(command, pattern):
    """The matches of `pattern` at the start of each segment of a shell command, quoted text read as data."""
    return [found for part in SEGMENT.split(QUOTED.sub("''", command)) for found in [pattern.match(part)] if found]


def runs(command, pattern):
    """The names a shell command runs: each segment that starts with the pattern. A name in an argument (rg "x" scripts/y) is not a run."""
    return [found.group(1) for found in matches(command, pattern)]


def calls(lines):
    """Every tool_use block of a transcript, as (name, input)."""
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get('message') if isinstance(entry, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                yield block.get('name', '?'), block.get('input') or {}


EDITS = ('Edit', 'MultiEdit', 'Write', 'NotebookEdit')  # the tools that write a file; their file_path is counted per file


def count(lines):
    """{'tools': Counter by tool name, 'scripts': runs by script name, 'commands': runs by script and its first word
    ('service health', 'flow-metrics'), 'git': git verbs, 'files': Counter of the files written by Edit, Write and the like}.
    Only runs count (see SEGMENT)."""
    tools, scripts, commands, git, files = Counter(), Counter(), Counter(), Counter(), Counter()
    for name, args in calls(lines):
        tools[name] += 1
        if name in EDITS and args.get('file_path'):
            files[args['file_path']] += 1
        if name == 'Bash':
            command = args.get('command', '')
            for found in matches(command, SCRIPT):
                script, word = found.group(1), found.group(2)
                scripts[script] += 1
                commands[f'{script} {word}' if word else script] += 1
            git.update(runs(command, GIT))
    return {'tools': tools, 'scripts': scripts, 'commands': commands, 'git': git, 'files': files}


TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')


def tokens(lines):
    """{field: total} of the model usage a transcript records, one count per assistant message id (a message can span
    several entries), plus 'first' and 'last': the transcript's first and last timestamps (ISO strings, or None)."""
    seen, total, stamps = set(), Counter(), []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get('timestamp'):
            stamps.append(entry['timestamp'])
        message = entry.get('message')
        usage = message.get('usage') if isinstance(message, dict) else None
        if not isinstance(usage, dict) or message.get('id') in seen:
            continue
        seen.add(message.get('id'))
        for field in TOKEN_FIELDS:
            total[field] += usage.get(field) or 0
    found = {field: total[field] for field in TOKEN_FIELDS}
    found.update(first=min(stamps) if stamps else None, last=max(stamps) if stamps else None, messages=len(seen))
    return found


def merges_between(first, last, root=ROOT, base=None):
    """First-parent merges on the base between two ISO timestamps: the PRs the transcript's work delivered."""
    import config
    base = base or f"{config.get('push-guard.remote')}/{config.get('train.base_branch')}"
    done = subprocess.run(['git', '-C', str(root), 'log', base, '--first-parent', '--merges', '--format=%H',
                           f'--since={first}', f'--until={last}'], capture_output=True, text=True, check=False)
    return len(done.stdout.split())


def render_tokens(found, prs=None):
    spent = found['input_tokens'] + found['output_tokens'] + found['cache_creation_input_tokens']
    lines = [f"model usage: {found['messages']} messages, {found['output_tokens']} output, {found['input_tokens']} input, "
             f"{found['cache_creation_input_tokens']} cache write, {found['cache_read_input_tokens']} cache read tokens"]
    if prs is not None:
        lines.append(f"merged PRs from {found['first']} to {found['last']}: {prs}; "
                     f"{(spent / prs) if prs else 0:.0f} non-cached tokens and "
                     f"{(found['output_tokens'] / prs) if prs else 0:.0f} output tokens per PR")
    return '\n'.join(lines)


def render(found, top=None):
    lines = [f"tool calls: {sum(found['tools'].values())}"]
    lines += [f'  {number:5d}  {name}' for name, number in found['tools'].most_common(top)]
    lines.append('scripts run from the shell:')
    lines += [f'  {number:5d}  scripts/{name}' for name, number in found['scripts'].most_common(top)]
    lines.append('git verbs in the shell:')
    lines += [f'  {number:5d}  git {name}' for name, number in found['git'].most_common(top)]
    return '\n'.join(lines)


KINDS = {'input': 'input_tokens', 'cache_read': 'cache_read_input_tokens', 'cache_write': 'cache_creation_input_tokens',
         'output': 'output_tokens'}  # the ledger's token kind -> the transcript's usage field
UNIT = re.compile(r'\b(?:queue )?row (F\d{2,3})\b|\bUnit:?\s[^\n]*?\b(F\d{2,3})\b')
DIR = re.compile(r'\bWorktree dir:\s*([A-Za-z0-9_.-]+?)\.?(?:\s|$)')
DELIVERED = re.compile(r'^\s*' + PREFIX + r'(?:\./)?scripts/deliver\b[^\n]*?--pr[ =](\d+)|^\s*origin pr ready (\d+)')
DELIVERED_BRANCH = re.compile(r'^\s*' + PREFIX + r'(?:\./)?scripts/deliver\b[^\n]*?--branch[ =](?:units/)?([A-Za-z0-9_.-]+)')
REPORTED = re.compile(r'\bPR\s*#?(\d+)\b')
MERGE = re.compile(r'\(#(\d+)\)$')


def texts(content):
    """The text of a message's content: the string itself, or its text blocks joined."""
    if isinstance(content, str):
        return content
    return '\n'.join(block.get('text', '') for block in content or [] if isinstance(block, dict) and block.get('type') == 'text')


def identify(lines):
    """{'unit', 'dir', 'pr'} of a lane transcript, read and never printed: the unit and the worktree dir from the brief (the
    first user message; a brief without a `Worktree dir:` line gives the dir of the last `scripts/deliver --branch [units/]D`
    the lane ran), the PR from the last `scripts/deliver --pr N` or `origin pr ready N` the lane ran, else from the
    last `PR #N` of its final report. Each is None when not found."""
    brief, report, pr, delivered = None, '', None, None
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get('message') if isinstance(entry, dict) else None
        if not isinstance(message, dict):
            continue
        if message.get('role') == 'user' and brief is None and texts(message.get('content')).strip():
            brief = texts(message.get('content'))
        if message.get('role') == 'assistant':
            report = texts(message.get('content')) or report
            for block in message.get('content') or []:
                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                    command = (block.get('input') or {}).get('command', '')
                    for found in matches(command, DELIVERED):
                        pr = int(found.group(1) or found.group(2))
                    for found in matches(command, DELIVERED_BRANCH):
                        delivered = found.group(1)
    unit = next((a or b for a, b in UNIT.findall(brief or '')), None)
    folder = DIR.search(brief or '')
    reported = REPORTED.findall(report)
    return {'unit': unit, 'dir': folder.group(1) if folder else delivered,
            'pr': pr if pr is not None else (int(reported[-1]) if reported else None)}


def weigh(found, weights):
    """The weighted tokens of a tokens() result: each kind times its weight (flow.token_weight_<kind>), in input-token
    equivalents."""
    return round(sum(found[field] * weights.get(kind, 0) for kind, field in KINDS.items()))


def _time(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc)


def seconds(first, last):
    """The wall time between two ISO timestamps, in whole seconds (0 when one is missing)."""
    return round((_time(last) - _time(first)).total_seconds()) if first and last else 0


def merged(root=ROOT, base=None):
    """{pr: (merge sha, ISO commit time)} of the first-parent commits on the base whose subject ends with (#N)."""
    import config
    base = base or f"{config.get('push-guard.remote')}/{config.get('train.base_branch')}"
    done = subprocess.run(['git', '-C', str(root), 'log', base, '--first-parent', '--format=%H %cI %s'],
                          capture_output=True, text=True, check=False)
    found = {}
    for line in done.stdout.splitlines():
        sha, stamp, subject = (line.split(' ', 2) + ['', ''])[:3]
        number = MERGE.search(subject)
        if number:
            found.setdefault(int(number.group(1)), (sha, stamp))
    return found


CUT = re.compile(r'^\s*' + PREFIX + r'(?:\./)?scripts/deliver\b[^\n]*?--pr[ =](\d+)')  # one delivery: a cut of the transcript
READY = re.compile(r'^\s*origin pr ready #?(\d+)\b')  # a PR the lane marked ready
WORK = re.compile(r'^\s*' + PREFIX + r'git (?:commit|push)\b')  # authoring: a commit or a push
BRANCH = re.compile(r'--branch[ =](?:units/)?([A-Za-z0-9_.-]+)')  # the unit's worktree dir: the branch delivered,
WORKTREE = re.compile(r'/wt/([A-Za-z0-9_.-]+)')  # else the worktree the command runs in
UNIT_DIR = re.compile(r'f(\d{2,3})(?:-\d+)?')


def _bash(entry):
    """The shell commands of one transcript entry's assistant tool calls."""
    message = entry.get('message') if isinstance(entry, dict) else None
    if not isinstance(message, dict) or message.get('role') != 'assistant' or not isinstance(message.get('content'), list):
        return []
    return [(block.get('input') or {}).get('command', '') for block in message['content']
            if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Bash']


def deliveries(lines):
    """The parts of a lane transcript, one per PR it delivered (F59): [(pr, dir, [line indexes])]. Each `scripts/deliver
    --pr N` run cuts the transcript, and the lines from the previous cut to it are that PR's (a rerun of the same PR after
    a red gate adds to it). The lines after the last cut are the last delivery's (its result read, its report written),
    unless the lane authored another unit there (a commit or a push from another worktree, or `origin pr ready N` for a PR
    it never delivered): that unit in flight is its own part, with its PR when known. [] with no run."""
    cuts, ready, work = [], [], []
    for index, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        for command in _bash(entry):
            where = BRANCH.search(command) or WORKTREE.search(command)
            folder = where.group(1) if where else None
            cuts += [(index, int(found.group(1)), folder) for found in matches(command, CUT)]
            ready += [(index, int(found.group(1))) for found in matches(command, READY)]
            work += [(index, folder) for _ in matches(command, WORK)[:1] if folder]
    if not cuts:
        return []
    parts, start = {}, 0
    for index, pr, folder in cuts:
        part = parts.setdefault(pr, [pr, folder, []])
        part[1] = part[1] or folder
        part[2].extend(range(start, index + 1))
        start = index + 1
    last = parts[cuts[-1][1]]
    pr = next((pr for index, pr in reversed(ready) if index >= start and pr not in parts), None)
    folder = next((folder for index, folder in reversed(work) if index >= start and folder != last[1]), None)
    tail = parts.setdefault(pr or ('open', folder), [pr, folder, []]) if pr or folder else last
    tail[2].extend(range(start, len(lines)))
    return [tuple(part) for part in parts.values()]


def _part(lines, indexes, seen):
    """tokens() of the given lines of a transcript, a message counted in the first part that holds it (`seen`)."""
    total, stamps, messages = Counter(), [], 0
    for index in indexes:
        try:
            entry = json.loads(lines[index])
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get('timestamp'):
            stamps.append(entry['timestamp'])
        message = entry.get('message')
        usage = message.get('usage') if isinstance(message, dict) else None
        if not isinstance(usage, dict) or message.get('id') in seen:
            continue
        seen.add(message.get('id'))
        messages += 1
        for field in TOKEN_FIELDS:
            total[field] += usage.get(field) or 0
    found = {field: total[field] for field in TOKEN_FIELDS}
    found.update(first=min(stamps) if stamps else None, last=max(stamps) if stamps else None, messages=messages)
    return found


def _wall(lines, indexes):
    """The wall seconds of a part: each run of consecutive lines from the end of the run before it (the previous delivery)
    to its own last line, summed."""
    def stamp(index):
        try:
            entry = json.loads(lines[index])
        except ValueError:
            return None
        return entry.get('timestamp') if isinstance(entry, dict) else None

    def last_stamp(span):
        return next((found for index in reversed(span) for found in [stamp(index)] if found), None)

    runs, total = [], 0
    for index in indexes:
        if runs and runs[-1][-1] == index - 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    for span in runs:
        before = last_stamp(range(0, span[0]))
        first = before or next((found for index in span for found in [stamp(index)] if found), None)
        total += seconds(first, last_stamp(span))
    return total


def ledger_rows(path, role, weights, prs):
    """The ledger lines of a transcript: its role (lane, subagent or coordinator), the unit and PR (lane), the tokens by kind
    and weighted, the span and the tool calls. A lane that delivered several PRs gives one line per PR (deliveries(), F59
    per PR). A coordinator's PRs are those merged in its span, and its weighted tokens are divided among them. Nothing of
    the transcript's text is kept."""
    with Path(path).open() as handle:
        lines = handle.readlines()
    found = tokens(lines)
    row = {'transcript': Path(path).name, 'session': None, 'role': role, 'unit': None, 'dir': None, 'pr': None, 'merged': None,
           'start': found['first'], 'end': found['last'], 'wall_s': seconds(found['first'], found['last']),
           'tool_calls': sum(count(lines)['tools'].values()), 'messages': found['messages'],
           'tokens': {kind: found[field] for kind, field in KINDS.items()}}
    row['tokens']['weighted'] = weigh(found, weights)
    for line in lines[:5]:
        try:
            row['session'] = row['session'] or json.loads(line).get('sessionId')
        except (ValueError, AttributeError):
            continue
    if role != 'lane':
        span = (_time(found['first']), _time(found['last'])) if found['first'] else None
        row['prs'] = sorted(pr for pr, (_, stamp) in prs.items() if span and span[0] <= _time(stamp) <= span[1])
        row['weighted_per_pr'] = round(row['tokens']['weighted'] / len(row['prs'])) if row['prs'] else None
        return [row]
    row.update(identify(lines))
    parts = deliveries(lines)
    if not (row['unit'] or row['dir'] or parts):  # a brief that names no unit and no worktree, and no delivery: a helper,
        row.update(role='subagent', pr=None)  # not a lane, and a PR its report names is someone else's
        return [row]
    if len(parts) <= 1:
        row['merged'] = prs[row['pr']][0] if row['pr'] in prs else None
        return [row]
    rows, seen = [], set()
    for number, (pr, folder, indexes) in enumerate(parts, 1):
        part = _part(lines, indexes, seen)
        unit = UNIT_DIR.fullmatch(folder or '')
        rows.append(dict(row, unit=f'F{unit.group(1)}' if unit else (row['unit'] if number == 1 else None),
                         dir=folder or (row['dir'] if number == 1 else None), pr=pr,
                         merged=prs[pr][0] if pr in prs else None, start=part['first'], end=part['last'],
                         wall_s=_wall(lines, indexes), messages=part['messages'], part=f'{number}/{len(parts)}',
                         tool_calls=sum(count(lines[index] for index in indexes)['tools'].values()),
                         tokens=dict({kind: part[field] for kind, field in KINDS.items()}, weighted=weigh(part, weights))))
    return rows


def transcripts(folder):
    """The lane transcripts of a subagents directory and the coordinator's: the session transcript the directory belongs to
    (<session>/subagents -> <session>.jsonl), when it exists."""
    folder = Path(folder)
    coordinator = folder.parent.with_suffix('.jsonl') if folder.name == 'subagents' else None
    return sorted(folder.glob('agent-*.jsonl')), coordinator if coordinator and coordinator.exists() else None


def newest_transcripts(pattern):
    """The most recently changed directory the pattern matches (flow.transcripts_glob), or None."""
    found = [Path(path) for path in glob.glob(os.path.expanduser(pattern)) if Path(path).is_dir()]
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def newest_session(pattern):
    """The subagents directory of the most recently changed session transcript, beside the directories the pattern
    names (<projects>/*/<session>/subagents -> <projects>/*/<session>.jsonl), whether it exists or not: a session that
    ran no lane has none, and its coordinator still has its rows. None when no transcript matches."""
    if not pattern.endswith('/subagents'):
        return None
    found = [Path(path) for path in glob.glob(os.path.expanduser(pattern[:-len('/subagents')] + '.jsonl'))
             if Path(path).is_file()]
    return max(found, key=lambda path: path.stat().st_mtime).with_suffix('') / 'subagents' if found else None


def lanes(folder, weights, prs):
    """The ledger rows of a subagents directory: each lane (one row per PR it delivered), then the coordinator."""
    found, coordinator = transcripts(folder)
    rows = [row for path in found for row in ledger_rows(path, 'lane', weights, prs)]
    return rows + (ledger_rows(coordinator, 'coordinator', weights, prs) if coordinator else [])


def write_ledger(rows, ledger):
    """Merge rows into the ledger: the rows of a transcript replace every line of the same session and transcript (a
    transcript gives one line per delivery, F59), the other lines stay."""
    ledger = Path(ledger).expanduser()
    key = lambda row: (row.get('session'), row.get('transcript'))  # noqa: E731
    fresh, kept = {key(row) for row in rows}, []
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            try:
                old = json.loads(line)
            except ValueError:
                continue
            if isinstance(old, dict) and key(old) not in fresh:
                kept.append(old)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in kept + rows))
    return ledger


def render_lanes(rows):
    """A table of ledger rows: numbers, the unit and the PR only."""
    lines = ['role         unit  dir     pr    merged    wall_s  tools   input  cache_read  cache_write  output  weighted']
    for row in rows:
        t = row['tokens']
        lines.append(f"{row['role']:<11}  {row.get('unit') or '-':<4}  {row.get('dir') or '-':<6}  {str(row.get('pr') or '-'):<4}  "
                     f"{(row.get('merged') or '-')[:8]:<8}  {row['wall_s']:>6}  {row['tool_calls']:>5}  {t['input']:>6}  "
                     f"{t['cache_read']:>10}  {t['cache_write']:>11}  {t['output']:>6}  {t['weighted']:>8}")
        if row['role'] == 'coordinator':
            per_pr = row['weighted_per_pr'] if row['weighted_per_pr'] is not None else '-'
            lines.append(f"  coordinator: {len(row['prs'])} PRs merged in its span, {per_pr} weighted tokens per PR")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/usage', description=__doc__.split('\n\n')[0])
    parser.add_argument('transcript', type=Path, nargs='?', help='a session transcript (.jsonl)')
    parser.add_argument('--top', type=int, default=None, help='the most common of each list (all by default)')
    parser.add_argument('--tokens', action='store_true', help='the model usage the transcript records')
    parser.add_argument('--per-pr', action='store_true', help='with --tokens: divided by the PRs merged on the base in its span')
    parser.add_argument('--lanes', metavar='DIR', nargs='?', const='', help='a subagents directory '
                        '(<session>/subagents; with no DIR the newest session\'s under flow.transcripts_glob, even when it '
                        'ran no lane): one ledger row per '
                        'delivery of each lane transcript and one for the coordinator (<session>.jsonl), never their text (F59)')
    parser.add_argument('--write', action='store_true', help='with --lanes: merge the rows into the ledger (flow.lanes_ledger)')
    parser.add_argument('--json', action='store_true', help='with --lanes: the rows as JSON lines')
    args = parser.parse_args(argv)
    if args.lanes is not None:
        import config
        pattern = config.get('flow.transcripts_glob')
        folder = Path(args.lanes) if args.lanes else newest_session(pattern) or newest_transcripts(pattern)
        if not folder or not (Path(folder).is_dir() or transcripts(folder)[1]):  # nor lanes nor their coordinator
            print(f'usage: no subagents directory ({args.lanes or config.get("flow.transcripts_glob")}); nothing read')
            return 1
        weights = {'input': config.get('flow.token_weight_input'), 'cache_read': config.get('flow.token_weight_cache_read'),
                   'cache_write': config.get('flow.token_weight_cache_write'), 'output': config.get('flow.token_weight_output')}
        rows = lanes(folder, weights, merged())
        if args.write:
            write_ledger(rows, config.get('flow.lanes_ledger'))
        print('\n'.join(json.dumps(row, sort_keys=True) for row in rows) if args.json else render_lanes(rows))
        return 0
    if not args.transcript:
        parser.error('a transcript or --lanes DIR')
    with args.transcript.open() as handle:
        if args.tokens:
            found = tokens(handle)
            prs = merges_between(found['first'], found['last']) if args.per_pr and found['first'] else None
            print(render_tokens(found, prs))
        else:
            print(render(count(handle), args.top))
    return 0


if __name__ == '__main__':
    sys.exit(main())
