"""The verifier thread's gate (the migration to GitHub, 14/11/2026): judge one exact commit and publish the verdict as its
commit status `tower/gate` on GitHub, the check the merge queue of `main` requires.

    scripts/verify-commit --sha <commit> --base <base commit> [--repo owner/name] [--no-post]

The commit must be the checkout's HEAD (the verifier checks out what it judges: a pull request's head, or the merge
queue's `gh-readonly-queue/main/...` commit, which is main plus the pull requests ahead of it). The plan is the gate's
own (scripts/gate-check plan checks: the stages and only the script tests whose covers the diff base...HEAD touches);
every stage of it runs but `pr metadata`, which reads the pull request on Origin, and the tests run in one
`gate-check tests` batch. The status is `pending` while it runs, then `success` or `failure` with what was red. No
GitHub Actions and no runner of its own: the verifier is a Claude Code thread, the session that publishes is the one
that ran the checks. Standard library and the `gh` CLI (the session's GitHub credential) only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT = 'tower/gate'
SKIPPED = ('pr metadata',)  # reads the pull request on Origin; the GitHub pull request is judged by its own reviewers


def run(args, cwd=ROOT, env=None):
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def plan(base, run=run):
    """The gate's plan of base...HEAD: {stages, tests, ...}."""
    with tempfile.TemporaryDirectory() as tmp:
        answer = Path(tmp) / 'plan.json'
        code, said = run(['scripts/gate-check', 'plan', 'checks', '--base', base],
                         env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)})
        if code != 0 or not answer.is_file():
            raise RuntimeError(f'no plan: {said.strip()[-300:]}')
        return json.loads(answer.read_text())['plan']


def judge(base, run=run, clock=time.monotonic):
    """(green, red names, the plan, seconds): every stage of the plan but SKIPPED, then its tests in one batch."""
    began = clock()
    planned = plan(base, run)
    red = []
    for stage in planned.get('stages') or []:
        if stage in SKIPPED:
            continue
        code, _ = run(['scripts/gate-check', 'stage', stage, '--base', base])
        if code != 0:
            red.append(stage)
    tests = planned.get('tests') or []
    if tests:
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'tests.json'
            code, _ = run(['scripts/gate-check', 'tests', ','.join(tests)],
                          env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)})
            said = json.loads(answer.read_text()).get('tests', {}) if answer.is_file() else {}
            red += [test for test in tests if said.get(test) != 'PASS']
            if code != 0 and not red:
                red.append('script tests')
    return not red, red, planned, clock() - began


def post(repo, sha, state, description, run=run):
    """The commit status, through the session's `gh` (repository-scoped)."""
    code, said = run(['gh', 'api', '-X', 'POST', f'repos/{repo}/statuses/{sha}', '-f', f'state={state}',
                      '-f', f'context={CONTEXT}', '-f', f'description={description[:140]}'])
    if code != 0:
        raise RuntimeError(f'status not posted: {said.strip()[-300:]}')


def repo_of(run=run):
    code, url = run(['git', 'remote', 'get-url', 'origin'])
    url = url.strip().removesuffix('.git')
    if code != 0 or 'github.com/' not in url:
        raise RuntimeError('origin is not a GitHub repository: pass --repo')
    return url.split('github.com/', 1)[1]


def main(argv=None, run=run):
    parser = argparse.ArgumentParser(prog='verify-commit', description=__doc__.splitlines()[0])
    parser.add_argument('--sha', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--repo')
    parser.add_argument('--no-post', action='store_true', help='judge and print; publish nothing')
    args = parser.parse_args(argv)
    code, head = run(['git', 'rev-parse', 'HEAD'])
    if code != 0 or head.strip() != args.sha:
        print(f'verify-commit: HEAD is {head.strip()[:12]}, not {args.sha[:12]}: check out the commit it judges',
              file=sys.stderr)
        return 2
    repo = args.repo or repo_of(run)
    if not args.no_post:
        post(repo, args.sha, 'pending', 'the verifier is judging this commit', run)
    try:
        green, red, planned, seconds = judge(args.base, run)
    except Exception as error:  # noqa: BLE001 - a verifier that could not judge says so on the commit
        if not args.no_post:
            post(repo, args.sha, 'error', f'not judged: {error}', run)
        print(f'verify-commit: not judged: {error}', file=sys.stderr)
        return 1
    checks = len([stage for stage in planned.get('stages') or [] if stage not in SKIPPED]) + len(planned.get('tests') or [])
    description = (f'green: {checks} check(s) in {seconds:.0f} s' if green
                   else f'red: {", ".join(red)}'[:140])
    if not args.no_post:
        post(repo, args.sha, 'success' if green else 'failure', description, run)
    print(f'verify-commit: {args.sha[:12]} {description}')
    return 0 if green else 1


if __name__ == '__main__':
    sys.exit(main())
