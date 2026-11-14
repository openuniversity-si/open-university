# GX-20 plan — carry-over by delta (the RETRO case)

Base a698f542. Implements B-14, GA-P01 (P-42); D-B6, D-B7 (plan-v2). Audit: `audit.md`.

## Rule (what the gate does)
On a `--pr` dev run whose proof is bound (`OU_GATE_PROOF`), the plan hook looks in the PR's event log for the newest accepted v4 `gate.passed` (plan `dev`) on an **ancestor** head H0 with the **same** `base_sha`, `toolchain_id` and `gate_version`. When `gate-carry.carry_over_enabled` is true and every file of `delta(H0, H)` (`git diff --no-renames --name-only H0 H`, non-empty) is in an area of `gate-carry.carry_over_areas` (["docs"]):
- the plan is `plan_for(delta)`: the always-stages (structure check **executes** on H, D-B6) plus the script tests whose covers meet the delta (GX-18);
- every stage H0 passed and this plan does not run is recorded as a passed, `cached`, `carried` stage of this run with `carried_from {event_id, sha: H0, delta_files}` in `$logs/carry.json` (`gate_carry.carried_from(logs)`);
- the `base...H` plan must be covered by H0's passed stages plus the delta plan, else no carry.
Anything else (switch off, no bound proof, no such verdict, H0 not an ancestor, a non-docs file, an unreadable log or git error) is a normal gate with the reason printed (fails closed, GA-P10). A carried verdict chains to its origin (`carried_from.sha`), so the delta is always measured from a fully run head.

pr.ready (`pr_ready.py`): when the head's evidence is a carried proof, the carry is re-verified from git (H0 is an ancestor and `delta(H0, head)` equals `delta_files`), and the plan items ticked only by commits in `H0..head` (the RETRO item) are reported as satisfied by the carried proof; a mismatch refuses pr.ready.

## Commits (dependency graph)
1. `audit.md` (done, 8bf1389c).
2. `plan.md` (this file).
3. Registry `config/registry/gate-carry.json` + generated module; `scripts/lib/gate_carry.py` (candidate, delta, decide, record, carried_from); `scripts/tests/test_gate_carry.py` + `scripts/tests/gate-carry.test.sh` + covers sidecar; unit manifest + `scripts/generate` (CODEOWNERS). Depends on 2.
4. Plan source: `gate-hooks/plan.sh` calls `gate_carry.py decide`; `gate_policy.classify_pr` classifies the delta when the decision carries and records the carried stages; tests in `test_gate_carry.py` (fixture repo: RETRO after green, EVENTS.md runs event-contracts, every fail-closed case, switch off). Depends on 3 (real edge: uses the decision API).
5. `pr_ready.py` carried-proof rule + tests in `scripts/tests/test_pr_ready.py` (run by `plan-tick.test.sh`). Depends on 3 only (reads `carried_from` from the verdict); parallel with 4 (no shared file).
6. RETRO `docs/units/GX20/retro.md`. Depends on the gate.

Critical path: 2 (5 min) → 3 (25 min) → 4 (25 min) → gate (≈15 min wall) → 6 (10 min) ≈ 80 min; 5 (15 min) runs beside 4. Executed by the coordinator session alone: each step is one or two files and the hand-off cost of a sub-agent exceeds the step (recorded per "think before acting").

## Tests
- 3, 4: `scripts/run test gate-carry`; `scripts/run test gate-areas` (gate_policy is in its covers).
- 5: `scripts/run test plan-tick`.
- Final: pinned `scripts/gate-dev --pr 739` once.

## Premises
- P-42 (GA-P01) CRITICAL, decided: content-addressed proof; structure check always reruns; covers-matching script tests rerun on docs.
- P-29 no avoidable rework (high).
- GA-P10 fails closed (GA2 §8.1): every unknown is a normal gate.
- P-43 (GA-P02) strict: the carry reads only attested forge events, never box-local `.pass` markers.

## Seam not owned (recorded in the PR)
`gate_proof.proof_payload` must add `gate_carry.fields(logs)` to put `carried_from` into the v4 event (GX-28 owns the file now). Until then the record is `$logs/carry.json` and the carried stages show as `cached` in the verdict.

## Known base defects expected
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (pinned gate adjudicates); env tests claude-session/root-identity/config (GX-ENV).

## Rollback
`scripts/config set gate-carry.carry_over_enabled false` (one key), or revert the merge commit.
