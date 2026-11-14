"""The plan tick of a PR, derived from its commits (D-065 V4; amends D-022).

A PR's commit plan (D-022: numbered items in the body, with no maximum since D-307) is ticked by its commits, never by a checkbox the PR
writes: a commit ticks the items its trailer names (`Plan: 2` or `Plan: 2, 3`). The checkbox in the body is
only the plan's text. A commit that changes no file ticks nothing (GX-21), and a RETRO-only commit ticks only
the RETRO item. scripts/plan-tick prints the derived checklist; pr_ready.py refuses to emit pr.ready
while an item is unticked.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ITEM = re.compile(r'^\s*[-*] \[[ xX]\] (\d+)\.\s+(\S.*?)\s*$', re.M)
PLAN_TRAILER = re.compile(r'^Plan:[ \t]*(\d+(?:[ \t]*,[ \t]*\d+)*)[ \t]*$', re.M)
NUMBER = re.compile(r'\d+')
RETRO_DOC = re.compile(r'^docs/units/[^/]+/retro\.md$')
RETRO_ITEM = re.compile(r'\bretro\b', re.I)
RECORD_SEPARATOR = '\x1e'
FILES_SEPARATOR = '\x1f'


def plan_items(body):
    """(number, text) of each checklist item of the PR body, in order. The box state is not read."""
    return [(int(number), text) for number, text in ITEM.findall(body or '')]


def ticked_by(messages):
    """The plan item numbers named by the Plan trailers of the commit messages."""
    ticked = set()
    for message in messages:
        for group in PLAN_TRAILER.findall(message):
            ticked.update(int(number) for number in NUMBER.findall(group))
    return ticked


def ticked_by_commits(commits, items=()):
    """The item numbers ticked by real commits, GX-21. commits: [{message, files}] (commit_check.fetch shape).

    A commit that changes no file (`git commit --allow-empty`) ticks nothing; a commit whose files are all a unit's
    retro.md ticks only the items of `items` [(number, text)] whose text names the RETRO. A commit with no `files`
    key has no file list to judge and counts as before."""
    retro = {number for number, text in items if RETRO_ITEM.search(text)}
    ticked = set()
    for commit in commits:
        files = commit.get('files')
        if files is not None and not files:
            continue
        named = ticked_by([commit.get('message', '')])
        if files and all(RETRO_DOC.match(name) for name in files):
            named &= retro
        ticked |= named
    return ticked


def unticked(body, commits):
    """The plan item numbers of the body that no real commit ticks, in order (ticked_by_commits)."""
    items = plan_items(body)
    done = ticked_by_commits(commits, items)
    return [number for number, _ in items if number not in done]


def checklist(body, messages):
    """The plan as [(number, text, done)], done when a commit names the item."""
    done = ticked_by(messages)
    return [(number, text, number in done) for number, text in plan_items(body)]


def commit_messages(base, root=ROOT, head='HEAD'):
    """The full messages of base..head (head: a sha or ref of the checkout, HEAD by default), oldest first. Local git only."""
    out = subprocess.run(['git', '-C', str(root), 'log', '--reverse', f'--format=%B{RECORD_SEPARATOR}', f'{base}..{head}'],
                         capture_output=True, text=True, check=True).stdout
    return [message.strip() for message in out.split(RECORD_SEPARATOR) if message.strip()]


def commits_with_files(base, root=ROOT, head='HEAD'):
    """[{message, files}] of base..head, oldest first; files are the changes against the first parent (empty for an empty commit)."""
    out = subprocess.run(['git', '-C', str(root), 'log', '--reverse', '--diff-merges=first-parent', '--name-only',
                          f'--format={RECORD_SEPARATOR}%B{FILES_SEPARATOR}', f'{base}..{head}'],
                         capture_output=True, text=True, check=True).stdout
    records = [record.partition(FILES_SEPARATOR) for record in out.split(RECORD_SEPARATOR) if record.strip()]
    return [{'message': message.strip(), 'files': [name for name in names.splitlines() if name.strip()]}
            for message, _, names in records]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/plan-tick', description=__doc__.splitlines()[0])
    parser.add_argument('--body', type=Path, required=True, help='file with the PR body (the plan text)')
    parser.add_argument('--base', default=None, help='base ref of base..HEAD (default: plan-tick.base_ref)')
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout whose commits are read')
    parser.add_argument('--check', action='store_true', help='exit 1 while an item is not ticked by a commit')
    args = parser.parse_args(argv)
    base = args.base or config.get('plan-tick.base_ref')
    try:
        commits = commits_with_files(base, args.root.resolve())
    except subprocess.CalledProcessError as error:
        print(f'FAIL plan-tick: git log {base}..HEAD failed: {error.stderr.strip()}')
        return 1
    body = args.body.read_text(encoding='utf-8')
    items = plan_items(body)
    missing = unticked(body, commits)
    for number, text in items:
        print(f'[{" " if number in missing else "x"}] {number}. {text}')
    print(f'plan tick: {len(items) - len(missing)}/{len(items)} derived from {len(commits)} commit(s) of {base}..HEAD')
    return 1 if args.check and (missing or not items) else 0


if __name__ == '__main__':
    sys.exit(main())
