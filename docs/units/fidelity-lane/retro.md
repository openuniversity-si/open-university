# U3b fidelity retro: imports to `@ou` addresses (PR #602)

Lane `fidelity-lane` (units `fidelity-references`, `fidelity-runner`). Covers the brief to the accepted gate.

## 1. Brief quality

- The brief said to create `mod/u3b-fidelity-addresses`; the session's designated branch was
  `claude/fidelity-ou-addresses-5450n8`. The designated branch was used. The brief should name one branch.
- The brief asked for `@ou/<target-unit>`. The address map only has `@ou/<unit>/*` keys, and a bare `@ou/<id>` is
  refused until U4 gives a contract entry. The real form is `@ou/<unit>/<path under home>`. The brief should state it.
- The brief's rule "rewrite every cross-unit import" did not mention that the fidelity scripts run lane files with
  `node <file>.ts`, and that Node cannot resolve `@ou/`. The precedent (commit 3c0ffb84) existed in the base but was not
  cited. Without the Node closure, the scope was 26 specifiers instead of 4.
- The brief asked for `gh pr create`; the session had only the GitHub MCP tools. The PR was opened with
  `mcp__github__create_pull_request` (draft).

## 2. Audit and plan

- Premises P-03 (confirmed, high) and P-13 (inferred, medium) held. Both are cited in the PR.
- Plan change: from "rewrite all cross-unit imports" to "rewrite only where Node does not load the file". The audit
  computed the Node closure of the seven fidelity entry points: 19 lane files, all non-test. This changed the scope from
  26 specifiers to 4 specifiers in 3 files.
- No CRITICAL premise came up. No production, secret or source-of-truth change.

## 3. Execution

Commit timeline (UTC, from pushes):

| Commit | Push | Content |
|---|---|---|
| 3c2aac77 | 1 | audit (`docs/units/fidelity-lane/audit.md`) |
| 41d5cafa | 2 | plan (`docs/units/fidelity-lane/plan.md`) |
| b8e19fde | 3 | references tests: 3 specifiers to `@ou/db-operations/...` |
| 4fd8b28b | 4 | runner test: `resolve.test.ts` to `@ou/fidelity-references/active.ts` |

Failures and rework:

- No code failure. Each code commit passed `scripts/units check` and its unit battery on the first run.
- A baseline battery was launched in a background command chained after a failing `git rev-parse`, so it never ran. It
  was re-run in the foreground. Cause: a `&&` chain behind a command that was not needed. Cost: one re-run (about 10 s).
- `scripts/premises` is bash, and `python3 scripts/premises` fails with a syntax error. Use `bash scripts/premises`.

Battery results (census, base vs head; identical counts):

| Unit | Step | Base | Head |
|---|---|---|---|
| fidelity-references | types (files) | 8 | 8 |
| fidelity-references | unit-tests (files) | 1 | 1 |
| fidelity-references | int-tests (files) | 1 | 1 |
| fidelity-runner | types (files) | 17 | 17 |
| fidelity-runner | unit-tests (files) | 3 | 3 |

## 4. Gate

- Run 1 on 4fd8b28b: PASS. Wall 310.5 s on this 4 vCPU cloud. Stage times: integration 158.7 s, lint 151.9 s, unit tests
  125.5 s, suite union 89.2 s, structure check 54.4 s, performance 46.2 s, typecheck 20.9 s. Vitest: 1763 unit tests,
  49 in the second project, 651 integration tests, 20 performance tests, 5 more; all passed.
- The gate printed "GATE CEILING EXCEEDED: 310.5 s > 180 s (D-064 f)". This is a warning, never a failure, per D-064 (f).
  It is not caused by this PR (the diff is 4 import lines and docs). Recorded here as a known environment limit.
- No known defect was hit (the timing-sensitive tests named in the brief did not fail).

## 5. Lessons

| Problem | Concrete change | Owner |
|---|---|---|
| Brief named a branch that differs from the session's designated branch | Brief template: one branch field, taken from the session | Maestro (brief template) |
| `@ou/<target-unit>` form not in the brief | Brief template: state the `@ou/<unit>/<path>` form and that bare `@ou/<id>` waits for U4 | Maestro, U4 |
| Node loader constraint not in the brief | Brief rule for U3b: "list the Node closure of entry points first; keep relative where Node loads the file" | U3b owner (this lane), via the audit template |
| Background command chained behind a failing command | Use separate calls for background launches | Session practice |
| `scripts/premises` run with python | Document the invocation in the premises help | Premises owner |
| Gate ceiling exceeded (310 s vs 180 s) | Already a warning under D-064 (f); the timing owner (O1, budgets) should track it. Not changed here (never loosen thresholds) | O1 |
