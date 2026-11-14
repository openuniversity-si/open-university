# GX-23 RETRO — narrow web stage inputs (fail closed)

PR #728, branch `mod/gx23`, base `mod/roadmap-integration`. Launch 01:27 UTC 28/10, gate PASSED 01:45 (commit clock), RETRO 02:15. Inside the 120 min deadline.

## 1. Brief quality

- **Wrong premise id.** The brief says `Premises: P-10 narrowing fails closed (GA-P10)`, but register `P-10` is `aggregates-not-written-by-prs`. Citing it would have resolved the wrong premise, the exact failure D-A1 exists to stop. GA-P10 is not registered; cited P-20 and P-46 only (STATUS comment 1). *Fix:* the brief generator maps GA-* ids through `scripts/premises find` and refuses an id whose slug does not match (owner: A Torre / brief template).
- **Files already claimed.** The brief says to claim the two new files in the owning unit manifest; plan-v2 prep had already claimed both in `units/engine-gate-plan/unit.json` (CODEOWNERS already listed them). My first edit to `engine-gate-report` would have been a double claim; reverted before commit. *Fix:* brief says "claimed by <unit> on base" when it is so.
- **Acceptance assumed every web stage narrows.** "A base merge that touches only `scripts/**` hits the lint, typecheck, unit and integration caches" contradicts GA-P10 for unit tests: the trace shows it reads every tracked file. The brief rightly made the trace the first job; the acceptance should have been conditional on it.
- **Branch name conflict.** The harness named `claude/gx23-web-stage-inputs-9oew2p`; the brief named `mod/gx23` and "no second branch". Followed the brief.
- `scripts/run test gate-result-cache` does not exist as a name (`scripts/run: no such test`); the script is run directly (`bash scripts/tests/gate-result-cache.test.sh`), and the gate's script-test stage runs it.

## 2. Audit and plan

- Held: the narrowing fits entirely in `gate_result_cache.py` plus a new declaration file; `gate-stages.json`, `gate-fixed.sh`, `gate.json`, `gate_keys.py`, `gate_report.py`, `gate-local` untouched (`git diff --stat origin/mod/roadmap-integration...HEAD`).
- Held: `gate_stage_key` swallows errors and the lint/typecheck key calls end in `|| return 1`, so raising on a bad declaration is fail closed in both directions with no shell change.
- Changed by the trace: unit tests is not declared (stays `**`); integration declares `config/registry/**` (vitest reads the registry); lint and typecheck declare the architecture checker's `.d.mts` and `docs/catalog/schema.md`; every stage declares the root and `apps/` probe files (`package.json`, workspace and lockfile names, browserslist), because a file that appears there changes behaviour.
- Added beyond the brief: a `traced` list per stage (exact paths, always in the key even if the globs are later narrowed) and the `gate-inputs.enabled` rollback switch (§3.1: a unit that changes what runs ships a switch).
- No fan-out: item 3 is one consequence (key + declaration + reader + tests, ~250 lines); splitting it would have produced a registry key without a reader.

## 3. Execution (timeline, commit clock UTC)

| Time | Event |
|---|---|
| 01:27 | branch, audit skeleton 1ee89cee, draft PR #728 (REST, no rate limit), STATUS |
| 01:28-01:36 | throwaway worktree, install, strace of the four stages (96 + 25 + 124 + 131 s) |
| 01:37 | trace 7a1351df |
| 01:38 | audit 24885039, plan 5f45a2a5 |
| 01:42 | code bb74abd5 |
| 01:42 | base moved 6 commits (GX-27 #725); first gate run stopped, base merged 14c4bd73 |
| 01:42-01:45 | pinned gate PASSED on 14c4bd73 |

Failures and rework, each with its class:
- *Test mocks with closed config dicts* (24 errors): existing tests mock `cache.get` with a fixed dict, so any new key read breaks them. Fixed once for the class with an `INPUT_KEYS` tuple added to the shared `pins()` helper and the stage-test values. Lesson: tests should mock `get` as "override these, fall through to the registry", which the new `DeclaredInputsTest.config` does.
- *Recursion in my own mock* (`self.config` called the patched `cache.get`): fixed with `REAL_GET` captured at import.
- *Literal check* (`number 2 written 2 times`, `number 4 written 2 times`): tuple indexing in the reader and a test fixture value; fixed by unpacking to names and a non-numeric fixture. Caught by `scripts/structure-check` before push (Brief Standard v2 (4)).
- *Self-inflicted kill*: `pkill -f gate-local` matched the shell running it (exit 144). No damage; use `TaskStop` only.
- *Wasted start*: the first gate run started before checking the base tip; stopped within a minute. Lesson: fetch the base immediately before every gate run.

## 4. Gate

- Runs: 1 complete (pinned), 1 aborted (head behind base).
- Pinned `scripts/gate-dev --pr 728` on 14c4bd73 (pinned to base fbc09f28): **PASSED**, 7 stages, 15 skipped by graph selection (scoped: engine-config, docs, delivery), script tests 86 PASS / 0 FAIL (`gate-result-cache.test.sh` and `gate-graph.test.sh` among them), `defect_decisions: []`, no KD hit, 164.1 s (ceiling 180 s). Advisory head-tooling run PASSED, 30.2 s.
- Re-gate after this RETRO commit to tick item 4 and emit `pr.ready`.

## 5. Evidence for the acceptance

- Targeted: `bash scripts/tests/gate-result-cache.test.sh` → `Ran 43 tests … OK`, `gate-result-cache: shell cases pass`; `bash scripts/tests/gate-graph.test.sh` → `Ran 21 tests … OK`.
- Cases: `test_a_scripts_or_docs_only_change_hits_every_web_stage`, `test_a_traced_file_outside_the_globs_misses` (traced-but-unglobbed change = miss), `test_an_undeclared_stage_keys_on_the_whole_tree`, `test_the_flag_off_gives_the_keys_from_before_gx23`, `test_a_malformed_declaration_fails_closed`; shell case through the real CLI and shipped file: a scripts-only change hits lint, typecheck and integration and misses unit (`**`).
- Real tree: keys of bb74abd5 vs 14c4bd73 (the GX-27 merge: 1 config, 3 docs, 1 scripts file): lint `b01c87446f80` = `b01c87446f80`, typecheck `4e8d7bbc29df` = `4e8d7bbc29df` (hits); integration `8dc8298c6abe` → `8de8bd5b6e46` (miss: `config/registry/merge.json` is a declared input); unit `20de32bec73a` → `88d9cfce2ac3` (miss: `**`).
- Done means running: the narrowed keys are read by every tier-1 gate run of the next PR that runs the web stages; the coordinator sees `PASS lint (cached: tier-1 result …)` on a base-merge-only rerun. Nothing to activate.
- Rollback: one JSON edit (remove a stage from `scripts/lib/gate-stage-inputs.json`, it returns to `**`) or `gate-inputs.enabled` false.

## 6. Lessons

| Problem | Change | Owner |
|---|---|---|
| unit tests cannot narrow: `countries.test.ts`, `no-legacy-email.test.ts` read every tracked file (`git ls-files -z`), `no-github-actions.test.ts` and `architecture-engine.test.ts` list scripts and workflows | move the whole-repo tests out of the vitest `unit` project into their own stage keyed on `**`, then declare `unit tests` from a fresh trace | GX program (new unit, after GX-23) |
| brief cited a wrong premise id | brief generator resolves GA ids through the register | A Torre |
| tests mock `config.get` with closed dicts | shared test helper "override + fall through" in `scripts/tests` | engine-test-support |
| gate started on a stale head | `gate-dev --pr` could print "head N behind base" before running | GX-05 owner (pin) |
| the trace is manual (strace + a parser) | a `scripts/gate-trace inputs <stage>` command that prints undeclared reads, run by the nightly to catch drift of the declaration | GX program |
