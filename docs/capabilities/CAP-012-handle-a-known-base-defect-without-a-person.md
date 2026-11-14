# CAP-012 — Handle a known base defect without a person
requested: 2026-10-26T23:50-03:00
requested-by: Daniel (chat, 23:50-23:54; recorded by A Torre), D-069
status: requested
visual: no

## Concepts
No new visitor concept. Four structural words:
- **base defect**: a test that fails on the integration base. Whoever opens a PR meets it; the PR did not cause it.
- **signature**: the normalized first error line of a failing test (`gate_failures.normalize`). With the test id it is the dedup key.
- **registry**: `docs/process/defects/<slug>.yml`, one record per defect, shaped by `contracts/defects/defect.v2.json`, changed only through `scripts/defects`, with a hash-chained audit trail.
- **queue impact**: how many queued or open units touch the defect's area, how many units require its unit, and how many tests cover it. It is the only priority; there is no deadline.

## Contract
Input: a failing test on a PR gate run.
Output: the gate re-runs that test on the integration base (cached per base sha and test id). Failing there with the same
signature: the verdict lists it as a known defect and does not block the PR. Failing only on the PR: the PR's own, it
blocks. Every test still runs; nothing is loosened.
The registry opens the defect (owner derived from the unit ownership map), the router opens a fix unit for the owner
(`work.assigned`) and makes the units touching the area depend on it when the priority reaches a registered threshold.
Lifecycle: open, fixing, resolved (the fix merged), verified (the gate saw the test pass on the base; closed by the gate).
Errors: an unknown stage, an unresolvable base, a re-run that times out, or a different signature is the PR's own failure.
Invariants: D-025 (no skipped or quarantined test hides a failure), D-065 (events, not a clock), D-068 (every weight and
threshold is a registry entry), D-069 items 4, 8 and 9.

## Out of scope
Fixing the defects (their owners' fix units). Production and Vercel. Browser and vitest base re-runs (a failure in a
stage outside `defects.stages` is always the PR's own).

## PRs
1. Capability design, registry config, record schema, events.
2. Registry library and `scripts/defects` (list, show, record, resolve, check), audit trail, owner from the map.
3. Detection in the gate: base re-run, signature match, verdict `known_defects`.
4. Router: queue-impact priority, fix unit, dependents.
5. Lifecycle: fixing, resolved, verified by the gate.
6. Seed (data only) and the gate check.
7. Docs.

## Target
idea-to-prod: one PR (KD1); production is frozen (D-054)
fixed-cost: 7 commits
marginal: a new base defect is detected, registered, owned, routed and closed with no manual step; a new weight is one registry key
