# GATE-FAST: plan (mirrored in the PR description)

Decision: D-076 (amends D-065 (5), P-43 and the `--cold` meaning of D-075). Findings: [audit.md](audit.md).
Premises: P-56, P-43, P-53.

Goal (Daniel, 29/10 15:51 BRT): the cold verdict goes from ~12 min to ~1-2 min, and verdicts of distinct PRs run at
the same time so the train can admit in parallel toward 1,000 PRs/day. Order: the largest measured slice first.

## Commits

- [ ] 1. Decision D-076 and this unit record.
- [ ] 2. Audit: measured per-stage time of the gate, the largest slice first.
- [ ] 3. Content-addressed cache safe for the train: key = relevant tree hash + toolchain + gate_version; `--cold`
  means "no result of another tree", not "no cache".
- [ ] 4. Incremental gate: only the tests of the touched units and their dependents, the full battery as the
  periodic net.
- [ ] 5. Parallel tests inside the gate (workers per vCPU).
- [ ] 6. Distinct PRs' verdicts run at the same time; admission stays serialized by the train.
- [ ] 7. Before/after measurement on this PR: retro, docs, issue #548.

Graph: `1 -> 2 -> {3, 4, 5} -> 6 -> 7`. One commit per push.

## Cheapest useful effort

Action: reuse the per-test and per-stage keys the gate already computes (GS1, GX-11, GX-23) as content addresses for
tier 2 and `--cold`, instead of a new cache; narrow the work where the audit measures the largest slice.
Cost: one cold gate run before and one after on this PR's head (~5-15 min wall each, 4 vCPUs).
Requirement: Daniel wants a cold verdict in ~1-2 min and verdicts of distinct PRs at once, toward 1,000 PRs/day.
Cheaper rejected: turning `--cold` back into a warm verdict (refused by D-075: a box-local marker by head, not by
content); raising `gate.script_tests_concurrency` alone (4 vCPUs are already saturated by the stages that overlap).
