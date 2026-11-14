# BASEFIX-shellcheck: plan

Branch `mod/basefix-shellcheck`, PR #769, base `mod/roadmap-integration` at `c003303d0`. Gate changes in this unit
(`scripts/gate-local`, `scripts/lib/gate-isolation.sh`) fall under D-070 (the gate-excellence program: the pinned gate
judges every PR, so the base must pass it) and D-027 (the environment is code).

## Commits
Revised after the root causes were found (items 4 and 5 name the real owners of the fix; see audit.md).

1. Audit skeleton (`docs/units/BASEFIX-shellcheck/audit.md`). Done, `f6f14e58a`.
2. Audit and plan (`audit.md`, `plan.md`). Done, `7f2fa5da2`; this revision too.
3. Shellcheck clean under 0.9.0 and 0.11.0. Files: the twelve of the brief, plus `scripts/gate-local`,
   `scripts/cloud/setup.sh`, `scripts/cloud/env.sh` (SC2119, 0.9 only) and `scripts/tests/gate-local/runner.test.sh`
   (SC2317, 0.9 only). Tests: the shellcheck command of `gate-local:373` under both versions, and every edited suite
   (budget, hook-pin, hooks, preflight, verdict, runner, gate-heavy-db, gate-result-cache, gate-worktree-resources,
   merge-phase, rest-fake-ready, gate-isolation, gate-db).
4. `gate-db.test.sh` deterministic: the root cause is the gate runner's watcher race. Files:
   `scripts/lib/gate-runner.sh`, `scripts/tests/gate-local/runner.test.sh`. Done, `d3b00f868`. Tests: runner.test.sh
   (the new no-signal check fails 3/3 on the old runner), the 300-stage reproduction (4/300 before, 0/300 after),
   gate-db.test.sh 5 runs in a row at one head under load.
5. `claude-session.test.sh` deterministic: its own stamp and database; the sweep class in the shared helper. Files:
   `scripts/tests/test_claude_session.py`, `scripts/lib/test_db.py`, `scripts/tests/test_test_db.py`. Done,
   `bcd56846`. Tests: test-db.test.sh, claude-session.test.sh 5 runs in a row at one head under load.
6. Retro (`retro.md`), after the gate on the head is green.

Graph: 1 -> 2 -> 3. Steps 4 and 5 depend only on 2. They own disjoint files and ran in parallel (5 in a sub-agent);
`runner.test.sh` is shared by 3 and 4 in sequence (3 was pushed first).
6 depends on the gate (after 3, 4 and 5).
Critical path: 3 (done, about 30 min) -> max(4, 5) (investigation under load, about 60 min) -> gate (about 20 min)
-> 6 (about 15 min).

## Premises
- P1: a reproduction of the two flaky suites needs the gate's load (script tests run concurrently). Radius: steps 4
  and 5. Checked by running each suite next to the rest of the script tests.
- P2: the unit timeout and the two 300 s kills of the base run were caused by my concurrent load, not the base.
  Radius: scope (if false, they are base defects this unit must also fix or route). Checked by the unloaded head gate.
  Not CRITICAL: no money, production or source of truth.
- P3: the gate's shellcheck is whatever is on `PATH`. Radius: every machine. Mitigated by being clean under both.

Premises: none

## Final proof
One `scripts/gate-local --sha <head>` with nothing else running on the machine.

## Known base defects expected
None registered for these suites in `config/registry/defects.json`; the brief's measurement lists the three above.
