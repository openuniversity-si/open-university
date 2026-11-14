"""Idea-to-production report (docs/process/STRUCTURE.md D5). Computed on each run; nothing is stored.

The clock starts at a capability's `requested:` and stops at the verified production deploy of the PR
that completes it: the tail's `ship-tail ship-verify: pass` comment, else the merge time.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import config  # noqa: I001 - one line, so the declared operation sites keep their lines
from structure import default_root, header, parse_time, trailers

REPO = config.get('forge-events.repo')
PAGE_SIZE = 100  # Historical report window, shared by the list and comment reads.
LOCAL = timezone(timedelta(hours=-3))  # America/Sao_Paulo has no DST since 2019
COLUMNS = ('capability', 'requested(-03:00)', 'live(-03:00)', 'idea→prod', 'PRs', 'fixed-cost', 'marginal', 'verdict')
WIDTHS = (13, 21, 21, 11, 5, 12, 10, 0)
UNITS = {'d': 86400, 'h': 3600, 'min': 60, 'm': 60, 's': 1}
SPAN = r'(\d+(?:\.\d+)?)\s*(d|h|min|m|s)\b'


class GitHub:
    """Merged PRs whose body carries a `Capability:` trailer, through the forge port."""

    def prs(self):
        import forge_events
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        'idea-to-prod', 'closed-changes', consumer='scripts/lib/idea_to_prod.py')
        return [{'number': item['number'], 'body': item['body'], 'mergedAt': item['merged_at']}
                for item in port.closed_changes(REPO) if 'Capability:' in item['body']]

    def live_at(self, pr):
        import forge_events
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        'idea-to-prod', f'pr-{pr["number"]}', consumer='scripts/lib/idea_to_prod.py')
        # Preserve this report's historical first-100-comment window.
        comments = port.comments(REPO, pr['number'])[:PAGE_SIZE]
        passed = [item['created_at'] for item in comments if str(item.get('body', '')).startswith('ship-tail ship-verify: pass')]
        return passed[-1] if passed else None


class Fixture:
    """A JSON list of {number, body, mergedAt, liveAt?}; tests use it so no network is needed."""

    def __init__(self, path):
        self.items = json.loads(Path(path).read_text())

    def prs(self):
        return self.items

    def live_at(self, pr):
        return pr.get('liveAt')


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def span(text):
    match = re.search(SPAN, text or '')
    return timedelta(seconds=float(match.group(1)) * UNITS[match.group(2)]) if match else None


def compact(delta):
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h{minutes:02d}m' if hours and minutes else f'{hours}h' if hours else f'{minutes}m'


def target(text):
    """Target lines `idea-to-prod:`, `fixed-cost:`, `marginal:`; marginal falls back to the first `< N h` bound."""
    section = text.split('\n## Target', 1)[1].split('\n## ', 1)[0] if '\n## Target' in text else ''
    lines = dict.fromkeys(('idea-to-prod', 'fixed-cost', 'marginal'))
    lines.update((key, span(value)) for key, value in re.findall(r'^(idea-to-prod|fixed-cost|marginal):(.*)$', section, re.M))
    if not lines['marginal']:
        bound = re.search(r'[<≤]\s*' + SPAN, section)
        lines['marginal'] = span(bound.group(0)[1:]) if bound else None
    return lines


def investigation(root, cap, name, opened):
    folder = root / 'docs/capabilities'
    existing = sorted(folder.glob('INV-*.md'))
    for path in existing:
        if cap in path.read_text():
            return f'investigation {path.name} is open'
    numbers = [int(match.group(1)) for path in existing if (match := re.match(r'INV-(\d{3})', path.name))]
    number = max(numbers + [0]) + 1 + opened
    return (f'open docs/capabilities/INV-{number:03d}-{name}.md: the question, then causes and the definitive '
            'structural solution in five instances, and the PRs that follow from it (STRUCTURE.md D5)')


def report(root, source, since=None, now=None):
    now = now or datetime.now(timezone.utc)
    prs = source.prs()
    lines = [''.join(c.ljust(w) for c, w in zip(COLUMNS, WIDTHS)).rstrip()]
    notes, opened = [], 0
    for path in sorted((root / 'docs/capabilities').glob('CAP-*.md')):
        cap = path.name[:7]
        text = path.read_text()
        fields = header(text)
        requested = parse_time(fields.get('requested', ''))
        if requested is None:
            notes.append(f'{cap}: no valid "requested:" line; run scripts/structure-check')
            continue
        mine = sorted((pr for pr in prs if pr.get('mergedAt')
                       and cap in re.findall(r'CAP-\d{3}', trailers(pr.get('body')).get('Capability', ''))),
                      key=lambda pr: pr['mergedAt'])
        done = fields.get('status', '').startswith('done')
        live = None
        if done and mine:
            live = instant(source.live_at(mine[-1]) or mine[-1]['mergedAt'])
        if since and (live or now) < since:
            continue
        goal = target(text)
        elapsed = (live or now) - requested
        if done and not mine:
            verdict = 'no PR'
        elif goal['idea-to-prod'] and elapsed > 2 * goal['idea-to-prod']:
            verdict = 'slow'
            action = investigation(root, cap, path.stem[8:], opened)
            opened += action.startswith('open ')
            notes.append(f'{cap}: slow ({compact(elapsed)} > 2 × {compact(goal["idea-to-prod"])}); {action}')
        else:
            verdict = 'ok' if done and goal['idea-to-prod'] else 'open' if not done else '—'
        cells = (cap, requested.astimezone(LOCAL).strftime('%Y-%m-%d %H:%M'),
                 live.astimezone(LOCAL).strftime('%Y-%m-%d %H:%M') if live else '—',
                 compact(elapsed), str(len(mine)),
                 compact(goal['fixed-cost']) if goal['fixed-cost'] else '—',
                 '≤' + compact(goal['marginal']) if goal['marginal'] else '—', verdict)
        lines.append(''.join(c.ljust(w) for c, w in zip(cells, WIDTHS)).rstrip())
    return lines + notes


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/idea-to-prod', description=__doc__.splitlines()[0])
    parser.add_argument('--since', help='YYYY-MM-DD (-03:00); deliveries live, or still open, from that day')
    parser.add_argument('--root', type=Path, help='repository with docs/capabilities (default: the current checkout)')
    parser.add_argument('--prs', help='JSON fixture of merged PRs instead of GitHub')
    parser.add_argument('--now', help='ISO time used as "now" for open deliveries')
    parser.add_argument('--no-env-check', action='store_true', help='skip the D-027 environment check (fixtures)')
    args = parser.parse_args(argv)
    if not args.no_env_check:
        # D-027: a broken environment stops the PR before it starts; the env-fix PR comes first.
        env = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'env_manifest.py'),
                              '--root', str((args.root or default_root()).resolve())], capture_output=True, text=True)
        if env.returncode != 0:
            print(env.stdout.rstrip())
            print('idea-to-prod: stopped before the PR starts; do the env-fix PR first (D-027)', file=sys.stderr)
            return 3
    since = datetime.fromisoformat(args.since).replace(tzinfo=LOCAL) if args.since else None
    source = Fixture(args.prs) if args.prs else GitHub()
    try:
        lines = report((args.root or default_root()).resolve(), source, since, instant(args.now))
    except RuntimeError as error:
        print(f'idea-to-prod: {error}', file=sys.stderr)
        return 1
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
