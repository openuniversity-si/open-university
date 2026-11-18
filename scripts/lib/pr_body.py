"""The PR body of a branch, built from its commits (D-208): the commit plan is read from the `Plan: N` trailers, and the trailers
and the attribution footer are added in the form the structure check accepts (the effort block left with D-328).

No GitHub call and no write: it prints the body or writes the file. Nothing a session has to type twice.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import plan_tick  # noqa: E402

import config  # noqa: E402

SESSION_ENV = 'CLAUDE_SESSION_URL'
# D-055: there is no review step, so the author's trailer is the one the lane contract names (docs/process/lane.md 4).
FIT_REVIEW = 'not reviewed (Daniel 2026-10-25: no review step)'


def footer():
    """The attribution footer; its link is the registry key forge-events.attribution_url (D-208)."""
    return ['', f"🤖 Generated with [Claude Code]({config.get('forge-events.attribution_url')})", '']


def plan_from_commits(subjects_and_messages):
    """The `### Commit plan` checklist a PR body needs, from the branch's commits: one line per `Plan: N` item with the subject
    of the first commit that names it. [(subject, message)] oldest first; items nothing names are absent (the body is the author's)."""
    first = {}
    for subject, message in subjects_and_messages:
        for number in sorted(plan_tick.ticked_by([message])):
            first.setdefault(number, subject)
    return ['### Commit plan'] + [f'- [x] {number}. {first[number]}' for number in sorted(first)]


def body(title, subjects_and_messages, session_url, fit_review=FIT_REVIEW, premises='none'):
    """The whole body as text: the title as its first line, then the plan and the trailers."""
    lines = [title, '']
    lines += plan_from_commits(subjects_and_messages)
    lines += ['', f'Fit-Review: {fit_review}', f'Premises: {premises}']
    lines += footer() + [f'Claude-Session: {session_url}']
    return '\n'.join(lines) + '\n'


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/pr-body', description=__doc__.split('\n\n')[0])
    parser.add_argument('--title', required=True, help='the first line of the body (the PR title is set separately)')
    parser.add_argument('--base', default='origin/mod/roadmap-integration')
    parser.add_argument('--session', default=os.environ.get(SESSION_ENV) or None,
                        help=f'the session URL of the Claude-Session: trailer (default: ${SESSION_ENV})')
    parser.add_argument('--out', help='write the body to this file instead of printing it')
    args = parser.parse_args(argv)
    if not args.session:
        print(f'pr-body: no session URL; pass --session URL or set {SESSION_ENV} (the "Claude-Session:" trailer, D-007)',
              file=sys.stderr)
        return 2
    messages = plan_tick.commit_messages(args.base, root)
    text = body(args.title, [(message.split('\n', 1)[0], message) for message in messages], args.session)
    if args.out:
        Path(args.out).write_text(text)
        print(args.out)
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
