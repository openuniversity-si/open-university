"""The PR body of a branch, built from its commits (D-208): the commit plan is read from the `Plan: N` trailers, the effort block
from four fields given once, and the trailers and the attribution footer are added in the form the structure check accepts.

No GitHub call and no write: it prints the body or writes the file. Nothing a session has to type twice.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import plan_tick  # noqa: E402

import config  # noqa: E402
import effort  # noqa: E402

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


def effort_block(action, cost, requirement, cheaper):
    """The `## Cheapest useful effort` block; the requirement must name its owner (scripts/lib/effort.py)."""
    return ['## Cheapest useful effort', f'- Action: {action}', f'- Cost: {cost}', f'- Requirement: {requirement}',
            f'- Cheaper rejected: {cheaper}']


def unit_owners(root=None):
    """{unit id: owner} of every registered unit (units/<name>/unit.json); a unit is not an owner, its owner lane is."""
    owners = {}
    for path in sorted((Path(root or ROOT) / 'units').glob('*/unit.json')):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        owners[data.get('id') or path.parent.name] = data.get('owner') or ''
    return owners


def requirement_problem(requirement, values=None, root=None):
    """None when the requirement names an owner the gate accepts (scripts/lib/effort.py: a word of effort.owners or a
    lane of the effort.owner_registry list); otherwise the refusal, with the valid owners and concrete requirements
    listed (VAZÃO F75). A registered unit name is not accepted, as the gate refuses it too: the refusal names its owner lane."""
    values = values or effort.settings(root)
    if effort._names(requirement, values['owners']):
        return None
    lanes = [owner for owner in values['owners'] if owner not in values['effort.owners']]
    lane = 'engine-lane' if 'engine-lane' in lanes else (lanes[0] if lanes else 'engine-lane')
    person = values['effort.owners'][0] if values['effort.owners'] else 'Daniel'
    units = [(unit, owner) for unit, owner in unit_owners(root).items()
             if re.search(r'(?<![\w-])' + re.escape(unit) + r'(?![\w-])', requirement)]
    named = ''.join(f' "{unit}" is a unit, not an owner: name its owner lane {owner or "(none in its unit.json)"}.'
                    for unit, owner in units)
    examples = '; '.join(f'--requirement "{text}"' for text in (
        f'{units[0][1] if units and units[0][1] else lane} needs one body per PR', f'{person} needs the report before the review',
        'the coordinator needs the closed rows'))
    return (f'pr-body: --requirement "{requirement}" names no owner.{named} Say who needs the result with one of: '
            f'{", ".join(values["effort.owners"])}, or one of the {len(lanes)} lanes of {values["effort.owner_registry"]} '
            f'({", ".join(lanes)}). For example: {examples} ({values["effort.rule_doc"]})')


def body(title, subjects_and_messages, action, cost, requirement, cheaper, session_url, fit_review=FIT_REVIEW, premises='none'):
    """The whole body as text: the title as its first line, then the plan, the effort block and the trailers."""
    lines = [title, '']
    lines += plan_from_commits(subjects_and_messages)
    lines += [''] + effort_block(action, cost, requirement, cheaper)
    lines += ['', f'Fit-Review: {fit_review}', f'Premises: {premises}']
    lines += footer() + [f'Claude-Session: {session_url}']
    return '\n'.join(lines) + '\n'


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/pr-body', description=__doc__.split('\n\n')[0])
    parser.add_argument('--title', required=True, help='the first line of the body (the PR title is set separately)')
    parser.add_argument('--action', required=True)
    parser.add_argument('--cost', required=True)
    parser.add_argument('--requirement', required=True, help='names its owner: a person, a role or a lane (scripts/lib/effort.py)')
    parser.add_argument('--cheaper', required=True)
    parser.add_argument('--base', default='origin/mod/roadmap-integration')
    parser.add_argument('--session', default=os.environ.get(SESSION_ENV) or None,
                        help=f'the session URL of the Claude-Session: trailer (default: ${SESSION_ENV})')
    parser.add_argument('--out', help='write the body to this file instead of printing it')
    args = parser.parse_args(argv)
    problem = (None if args.session else f'pr-body: no session URL; pass --session URL or set {SESSION_ENV} '
               '(the "Claude-Session:" trailer, D-007)') or requirement_problem(args.requirement, root=root)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    messages = plan_tick.commit_messages(args.base, root)
    text = body(args.title, [(message.split('\n', 1)[0], message) for message in messages], args.action, args.cost,
                args.requirement, args.cheaper, args.session)
    if args.out:
        Path(args.out).write_text(text)
        print(args.out)
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
