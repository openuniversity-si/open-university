# GX-15 RETRO — structure tree part cached; `pr metadata` stage; `pr.checked`; local checks

PR #732, branch `mod/gx15`, base `fbc09f28`. Launched 01:49 UTC 28/10 (22:5x BRT 27/10).

## 1. Brief quality
- Clear on goal, files and closed files. Two things it could not know, both found by reading the base:
  - The call site `gate-local:365` passes `--pr` to the structure check and `gate-local` is closed: the split had to be
    driven from `prereq.sh` (sourced at `:44`, before the launch). The brief named `prereq.sh` for the prerequisite list
    but not this constraint.
  - "Declare the tree stage `deterministic`" conflicts with GX-23's `test_gate_result_cache.py:202` (asserts it is not)
    and with the generic stage key, which lacks the base tree. Declaring it would be unsafe under `step_cached`.
- The brief's "24 tree modules" (GA2 Q2) counts `threshold_check`, which reads the PR body and commit messages: not tree.
- A new stage name ripples into files the brief did not list (`gate_policy.PREREQUISITES`, `gate-areas.json`, the
  `test_gate_report_skips.py` verdict digest, `gate-local.test.sh` no-op loop, the `engine-gate-run` requires).

## 2. Audit and plan
- Premises held: P-42 (metadata always reruns: by construction, `--metadata` never touches the cache; tested), P-46
  (pinned verdict). Unit premise corrected (A3): 23 cached modules, threshold moved to metadata; merge-base tree added
  to the key (A5).
- Plan change: `structure check` kept `deterministic: false` (decision 1 in the STATUS comment); the determinism is
  implemented in `structure.py` with the correct key.

## 3. Execution (UTC)
| Time | Event |
|---|---|
| 01:50 | branch, skeleton, draft PR #732, STATUS |
| 01:56 | config store read refused: session GitHub budget `gh: exit 429 … wait 502 s`; `setup.sh` exited 2 "missing host tool: python3" (same cause). Setup ran with `OU_CONFIG_STORE=file`; pushes waited until 02:16 |
| 01:55-02:01 | audit (24 modules timed, 8.26 s), plan; local-checks sub-agent in parallel (own 3 files) |
| 02:02 | commit 3 tree cache (literal census caught slice and test literals before commit: fixed by printing the full key and deriving counts) |
| 02:03 | commit 5 local checks (sub-agent: one shared helper, budgets ≥ 2× measured) |
| 02:10 | commit 4 pr metadata + pr.checked; 3 consequences found by targeted tests before push (gate-local no-op loop, gate-areas plan, verdict digest) |
| 02:12 | real run: `structure-check --pr 732 --metadata` published pr.checked on GitHub (event cb95a112…) |
| 02:13 | pinned gate #1 on 0453babc: FAILED, 1 test (`push-guard.test.sh`, class code, mine); advisory head run same failure, its `pr metadata` stage PASS (3.2 s) |
| 02:25-02:40 | root cause: push_guard pushes from a fixture's post-commit hook, which exports `GIT_INDEX_FILE`/`GIT_DIR`; the new local checks ran `git -C <engine>` and read the fixture's index ("the code writes it 0"). Passed outside the hermetic wrapper; reproduced with the tooling's `scripts/lib/hermetic` on PYTHONPATH |
| 02:40 | class fix in the shared helper: a structure-module check skips when a git variable names another repository (`local_checks.other_repository`), test added; push-guard and local-checks green under the hermetic wrapper |

Failures by class: (a) literal census on own code and tests (registered-literal rule applies to tests too; caught locally
by the census, never by the gate); (b) a new stage name ripples into plan lists and golden digests (found by running
the covers-selected tests, not the gate); (c) **the gate found one** (incident): a check added to the pre-push set runs
inside other repositories' hooks; my targeted tests ran `local-checks` but not `push-guard.test.sh`, which runs the pre-push
hook yet did not cover `local_checks.py` or `local-checks.json` (added to `covers/push-guard.json` now), and I ran tests outside the hermetic wrapper, where the
symptom did not show.

## 4. Gate
See the MERGE-READY comment for the verdict of record (pinned `scripts/gate-dev --pr 732`) with numbers and KD ids.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| A brief asks for `deterministic` on a stage whose generic key cannot be right | Plan rows that say "declare deterministic" name the key's inputs (base? merge base?) | planner (A Torre) |
| A new gate stage needs edits in 5 places (policy list, areas, stages, report digest, hook test) | One registry of stage names that `gate_policy`, `gate-areas.json` and `gate-stages.json` derive from (`scripts/generate`) | GX-23 / gate-plan owner |
| A pre-push check passed by hand and failed in the gate | Run targeted tests through the gate's hermetic wrapper (`scripts/run test` should set `PYTHONPATH=scripts/lib/hermetic` like `gate_test_cache.run`), and select them from covers (`gate_script_tests.py select` on the diff) instead of by name | gate owner (GX-23 / GX-ENV) |
| A check run from a git hook inherits the hook's `GIT_*` variables | Any engine helper that runs `git -C <root>` from a hook clears or checks `GIT_DIR`/`GIT_INDEX_FILE` (`local_checks.other_repository` is the first) | engine-commit-plan |
| The session's GitHub budget block fails every config read, even of defaults | Registry-default reads that never touch the store (setup bootstrap) and a preflight line naming the block | GX-ENV |
| `pr.checked` v1 natural key excludes the result: a flipped verdict on the same head is deduplicated | `pr.checked.v2` with a result digest in the key | contract owner (CANDIDATE posted) |
