"""Commit discipline of a PR (D-022, enforced by D-025).

scripts/commit-check --pr N [--sha S] reads the PR through the GitHub REST client the tail uses, judged on the gated
commit S (structure-check passes its checkout's HEAD), and refuses:
  plan       the body has no D-022 commit plan checklist (at least one item; no maximum unless the registry sets one, D-307);
  fixup      a commit only fixes the previous commit of the same PR (every commit must be green on its own);
  push       one push brought several commits of the PR at the same instant (push them one by one; the
             .githooks push each commit alone, and scripts/replay-branch N is the remedy of a batched push);
  force-push the PR head ref has force_push activity: pushed history was rewritten (merge commits only; FP1). Branch
             protection is unavailable, so the gate refuses it; scripts/replay-branch N builds a new branch;
  rebase     the head is behind its base by more than the registry allows and no PR commit merges the base (a rebased
             or never-updated branch; limit 0 while merge.tier1_requires_base_merge is on, else merge.max_behind_base):
             bring the base in with `git merge <push-guard.remote>/<base>`, a merge commit, never a rebase (FP1);
  gate       the PR changes the gate without citing an approved D-NNN of docs/domain/DECISIONS.md;
  decision   the PR body or a PR comment waits on an owner decision and no later line records a "Decision:" line
             (DECIDE, THEN REPORT, Daniel 2026-10-26 21:29; scripts/lib/decision_wait.py). Only comments created up to
             the gated head's push are judged (GX-14): a comment during the gate does not change its verdict.
  plan-done  (--pr) a plan item no real commit ticks (GX-21; a draft's is a warning, D-083: plan_verdict);
  lane       (--pr) the change touches the units of several lanes (GX-21, LANE-OWN: lane_errors).
plan-done and lane left the structure check (planning) for this check (delivery): D-322. --pr-body FILE judges a body
file's plan, and with --base the plan completeness against base..HEAD and the lanes of base...HEAD.
--fixture FILE checks the same shape from JSON (tests, no network). Exit 1 on a refusal.
--local runs the fast registry-driven local checks (scripts/lib/local_checks.py, LR1): one push per commit, the gate cites a
decision, a diff secret scan, no registered literal, the cheap structure checks. --body-file gives the PR body, --stdin-refs
reads the pre-push lines (.githooks/pre-push). A check over its budget moves to the gate; one that cannot run is skipped.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import plan_tick
from gate_pin import GATE_FILE  # noqa: F401 - the gate's files live with the gate (D-322); re-exported for its callers
# The PR reading lives under planning and delivery both (forge_pr, the events layer, D-322); re-exported for its callers.
from forge_pr import REPO, fetch, gated_commits, git, local_commits, local_files  # noqa: F401
# The PR discipline is the gate's (gate_discipline, D-322, D-329): the gate judges a PR with it and reads no delivery
# module; re-exported for this command and its callers.
from gate_discipline import (  # noqa: F401
    DECISION, FIXUP_PREFIX, FIXUP_SUBJECT, PLAN_ITEM, PLAN_MAX, PLAN_MIN, carried_by_merge, check, decisions,
    fixup_errors, force_push_errors, gate_errors, gated_push_time, lane_errors, lift, lifted, plan_completeness_errors,
    plan_errors, plan_verdict, pr_errors, push_errors, reach, rebase_errors)

ROOT = Path(__file__).resolve().parents[2]


def body_errors(body, root, base=None):
    """(errors, warnings) of a PR body file as `--pr-body` judges it: its commit plan (plan_errors), and with a base the
    plan completeness against the commits of base..HEAD and the lanes of base...HEAD (GX-21), which the structure check
    judged before D-322."""
    errors, warnings = list(plan_errors(body)), []
    if not base:
        return errors, warnings
    try:
        errors += lift(plan_completeness_errors(body, plan_tick.commits_with_files(base, root)), 'structure')
        merge_base = git(root, 'merge-base', base, 'HEAD')
        if merge_base:
            changed = (git(root, 'diff', '--name-only', f'{base}...HEAD') or '').split()
            errors += lift(lane_errors(root, merge_base.strip(), changed), 'structure')
    except subprocess.CalledProcessError as error:
        warnings.append(f'plan: commits of {base}..HEAD not readable ({error.stderr.strip()})')
    return errors, warnings


def checkout_head(root):
    """This checkout's HEAD, else None: the gated sha when it is a commit of the PR (GX-14, the gate's checkout)."""
    head = (git(root, 'rev-parse', 'HEAD') or '').strip()
    return head or None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/commit-check', description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--local', action='store_true', help='the fast local checks of local-checks.checks (no network)')
    source.add_argument('--pr', type=int, help='PR number, read through the forge port, judged on the checkout\'s HEAD '
                        'when it is a PR commit (the gated sha), else the live head')
    parser.add_argument('--sha', help='--pr: the gated commit to judge instead')
    source.add_argument('--fixture', type=Path, help='JSON with body, commits, files, pushes, force_pushes, base and comments (tests)')
    source.add_argument('--pr-body', type=Path, help='a PR body file: its commit plan; with --base, the plan completeness '
                        'and the lanes of base...HEAD (GX-21)')
    parser.add_argument('--base', help='--pr-body: the base whose commits tick the plan and whose diff names the lanes; '
                        '--pr: accepted and unused (the PR names its base)')
    parser.add_argument('--observation', type=Path,
                        help='--pr: judge what the live service read of the PR (PR-OBSERVATION), not the forge')
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout whose DECISIONS.md is cited (--local: the checkout checked)')
    parser.add_argument('--body-file', type=Path, help='--local: file with the PR body')
    parser.add_argument('--stdin-refs', action='store_true', help='--local: read the pre-push lines from stdin')
    parser.add_argument('--only', metavar='NAME', help='--local: run only the local check of that id (D-236)')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.local:
        import local_checks  # not at import: local_checks reaches structure, which imports this module
        return local_checks.main(root, args.body_file, args.stdin_refs, only=args.only)
    if args.pr_body:
        errors, warnings = body_errors(args.pr_body.read_text(), root, args.base)
        for line in errors:
            print('FAIL ' + line)
        for line in warnings:
            print('WARN ' + line)
        print(f'commit-check (body): {len(errors)} refusal(s)')
        return 1 if errors else 0
    try:
        if args.fixture:
            pr = json.loads(args.fixture.read_text())
        else:
            observed = json.loads(args.observation.read_text()) if args.observation else None
            pr = fetch(args.pr, args.sha, root, head=checkout_head(root), observation=observed)  # PR-OBSERVATION
    except (RuntimeError, OSError, KeyError) as error:  # any forge read error: blind, never liftable (GC)
        print(f'FAIL commit-check: PR #{args.pr} not readable ({error})')
        return 1
    errors, warnings = pr_errors(pr, root) if not args.fixture else (check(pr, decisions(root)), [])
    for line in errors:
        print('FAIL ' + line)
    for line in warnings:
        print('WARN ' + line)
    print(f'commit-check: {len(pr.get("commits", []))} commit(s); {len(errors)} refusal(s)')
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
