"""The next free decision number: after the base's last one and after every number an open PR cites (D-183).

A lane writes its decision rows in docs/domain/DECISIONS.md at the next free number it sees. Parallel lanes see the same base,
so they pick the same number, and the second PR collides at its lap (D-179, D-181). This tool reserves what the open PRs already
cite: the next number is above the base's last row and above every `D-NNN` in an open PR's title or body (the PR itself excluded).
It reads the base file from git and the open PRs through the forge port (scripts/lib/forge_events.py): one list of the open
changes, then each change's title and body.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
DECISIONS = 'docs/domain/DECISIONS.md'
ROW = re.compile(r'^\| D-(\d+) ', re.MULTILINE)
CITE = re.compile(r'\bD-(\d+)\b')


def base_numbers(text):
    """The decision numbers that rows of a DECISIONS.md text hold."""
    return {int(number) for number in ROW.findall(text)}


def cited(texts):
    """The decision numbers that any of `texts` cites."""
    return {int(number) for text in texts for number in CITE.findall(text or '')}


def next_free(base_text, texts=()):
    """One above the largest number that the base holds or an open PR cites (0 + 1 when there is none)."""
    taken = base_numbers(base_text) | cited(texts)
    return max(taken, default=0) + 1


def forge():
    """The forge port this tool reads the open changes through (the configured adapter, D-069 item 7)."""
    import forge_events
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    'decision-next', 'decision-next', consumer='scripts/lib/decision_next.py')


def open_pulls(repo, port=None):
    """[{number, title, body}] of the open changes of `repo`, drafts included, through the forge port; [] when the forge
    cannot answer (the claim branch still decides). A port that refuses this consumer raises: that is configuration."""
    port = port or forge()
    try:
        found = []
        for item in port.open_pulls(repo):
            pull = port.pull(repo, item['number'])
            found.append({'number': item['number'], 'title': pull.get('title') or '', 'body': pull.get('body') or ''})
        return found
    except Exception:  # noqa: BLE001 - an unreadable forge reserves nothing; the claim push still refuses a taken number
        return []


def free_number(base_text, pulls, exclude=None):
    """next_free over the base and the open PRs other than `exclude` (a PR number)."""
    texts = [text for pull in pulls if pull.get('number') != exclude for text in (pull.get('title'), pull.get('body'))]
    return next_free(base_text, texts)


CLAIMS = 'claude/decision-claims'
CLAIM = re.compile(r'refs/heads/' + CLAIMS + r'/D-(\d+)$')


def claimed(root=ROOT, remote='origin'):
    """The decision numbers a claim branch holds on the remote (refs/heads/claude/decision-claims/D-NNN). A claim is never
    deleted: a number is never reused, so the set only grows. An unreadable remote claims nothing (the push decides)."""
    done = subprocess.run(['git', '-C', str(root), 'ls-remote', '--heads', remote, f'{CLAIMS}/*'], capture_output=True, text=True)
    if done.returncode != 0:
        return set()
    return {int(found.group(1)) for found in (CLAIM.search(line) for line in done.stdout.splitlines()) if found}


def brt(now=None):
    """The time as the Brazilian clock reads it (America/Sao_Paulo), from the machine's clock, never typed (D-207)."""
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m %H:%M BRT')


def claim_commit(root, parent, number, when=None):
    """A commit with HEAD's tree and the base as its only parent: one per number, so two claims are never descendants. The
    message carries the time of the claim, so the decision's time in the table can be checked against the claim (D-207)."""
    tree = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD^{tree}'], capture_output=True, text=True, check=True).stdout.strip()
    done = subprocess.run(['git', '-C', str(root), 'commit-tree', tree, '-p', parent, '-m', f'claim D-{number} {when or brt()}'],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def reserve(root=ROOT, remote='origin', base='mod/roadmap-integration', tries=None, run=subprocess.run, lifted=False):
    """Claim the next free number by a push that the remote refuses when someone holds it. Returns the number, or None
    after `tries` refusals. The base is fetched by the caller (scripts/decision-next --claim). In the exception regime
    (`lifted`, regime.lifted('decision-claim')) a refused claim takes the next free number without the remote claim: the
    number is then the next one that the base and the open pulls leave free, and the record takes it (D-260)."""
    parent = f'{remote}/{base}'
    if tries is None:
        tries = _claim_tries()
    for _attempt in range(tries):
        number = _next_number(root, remote, base)
        sha = claim_commit(root, parent, number)
        pushed = run(['git', '-C', str(root), 'push', '--quiet', remote, f'{sha}:refs/heads/{CLAIMS}/D-{number}'],
                     capture_output=True, text=True)
        if pushed.returncode == 0:
            return number
    if lifted:
        return _next_number(root, remote, base)
    return None


def _next_number(root, remote, base):
    pulls = open_pulls(_repo(root))
    return max(free_number(base_text(root, remote, base), pulls), max(claimed(root, remote), default=0) + 1)


def base_text(root=ROOT, remote='origin', base='mod/roadmap-integration'):
    """DECISIONS.md as the base holds it, read from the fetched remote ref ('' when the ref is unknown)."""
    done = subprocess.run(['git', '-C', str(root), 'show', f'{remote}/{base}:{DECISIONS}'], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ''


def suggest(root=ROOT, remote='origin', base='mod/roadmap-integration'):
    """The next free number now, for a lap that has to renumber (the repo comes from the registry)."""
    return free_number(base_text(root, remote, base), open_pulls(_repo(root)))


def _claim_tries():
    from config import get as config_get  # the registry key forge-events.claim_tries (D-189)
    return config_get('forge-events.claim_tries')


def _lifted(lock):
    """regime.lifted(lock) (scripts/lib/regime.py, lane 4): true while the exception regime holds and the lock is not kept.
    Without the module the regime cannot hold, so the lock stands as it does today (D-260)."""
    try:
        import regime
    except ImportError:
        return False
    return regime.lifted(lock)


def _repo(root):
    from config import get as config_get  # the repo's registry (scripts/lib/config.py)
    return config_get('forge-events.repo', root)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/decision-next', description=__doc__.split('\n\n')[0])
    parser.add_argument('--exclude', type=int, metavar='PR', help='the PR whose own citations do not count (the one being renumbered)')
    parser.add_argument('--remote', default='origin')
    parser.add_argument('--base', default='mod/roadmap-integration')
    parser.add_argument('--claim', action='store_true', help='reserve the number on the remote and print it (atomic: a refused push is taken)')
    args = parser.parse_args(argv)
    if args.claim:
        lifted = _lifted('decision-claim')
        number = reserve(root, args.remote, args.base, lifted=lifted)
        if number is None:
            print('decision-next: could not claim a number; the tries of forge-events.claim_tries are spent', file=sys.stderr)
            return 1
        if lifted:
            print(f'decision-next: regime decision-claim lifted, D-{number} is not claimed on the remote', file=sys.stderr)
        print(f'D-{number} claimed {brt()}')
        return 0
    taken = claimed(root, args.remote)
    number = max(free_number(base_text(root, args.remote, args.base), open_pulls(_repo(root)), exclude=args.exclude),
                 max(taken, default=0) + 1)
    print(f'D-{number}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
