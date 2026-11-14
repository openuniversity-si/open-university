# EFFORT-STEP retro

From the brief (2026-10-28, launched 17:08 UTC) to the gated head. Times are commit times (UTC).

## 1. Brief quality
- **Two cited sources did not exist here.** The motor's `rules/effort.md` and `tools/effort-check.py` live on the box (`/workspace/torre/motor/v3/`). This cloud session has no `/workspace`. The brief told me to copy the rule and match the 16 checks, but the session could not read either. The check was rebuilt from the brief's four fields and two refused shapes. Because the motor's 16 checks could not be compared one by one, field-by-field agreement is proven against the repo's own copy of the rule (`docs/padrao/v4/effort.md`), not the motor's.
- **"Exactly as the language baseline does" names nothing in the repo.** No list is called that. The closest is `tests.unhermetic_sites` (a registry list, shrink-only against the base), and that pattern is what I followed.
- **"The unit checklist" was ambiguous.** It turned out to mean the Padrão's `audit-and-plan.md`. The Padrão is versioned and never edited in place, and the active version is `v1` even though `v3` exists. The brief did not say which version, or whether to activate it.
- **The branch name conflicted with the session's default branch** (`claude/effort-step-gate-t500xy`). The brief's `mod/effort-step` won (brief standard v2 item 1).

## 2. Audit and plan
- Premise "the motor files are readable": broke at once. The plan was written from the brief instead, with no rework.
- Premise "refusing every body is safe for the queue": held. A body edit does not move the head, so `pr.ready` stays valid.
- Plan change: item 5 dropped the `coordinator.padrao_version` flip after the audit found the active version is `v1`. Flipping it would have installed v2 and v3 as a side effect.
- Plan change: the code went into a new unit `engine-effort` instead of `engine-structure`. The structure check showed `engine-structure` already above its ceiling on the base (1519 of 1500 lines, warning only).

## 3. Execution (timeline)
| Time | Commit | Note |
|---|---|---|
| 17:09 | 3a34b051 audit skeleton | draft PR #770 and STATUS within about 2 minutes of launch |
| 17:12 | f03fae4e audit | |
| 17:14 | 002d6184 plan | PR body mirrors plan.md; the plan carries its own effort block |
| 17:16 | cd508400 Padrão v4 | written by one sub-agent in parallel with commit 3 (separate files) |
| 17:22 | 38e15b05 effort.py | |
| 17:29 | 697f60d6 wiring | |

Failures, each with its class:
1. **Slow test (13 s), class env/harness.** Run outside the hermetic harness, `config.get` read the shared change store over GitHub (11 s in one fixture). The gate pins the file store (`PYTHONPATH=scripts/lib/hermetic`). Rerun the way the gate does, the suite takes 0.46 s. Lesson: always run script tests with `PYTHONPATH=scripts/lib/hermetic`.
2. **Real cost, class code.** 532 `config.get` calls over 130 plans took about 1 s. Fixed by reading every `effort.*` value once per check (`effort.settings`).
3. **Literal census, class code, twice** (38e15b05, then again in 697f60d6). Test numbers (`parents[2]`, `len(...) == 2`, a date tuple, a PR number) were refused as engine literals. The second time was the same cause. The census runs only in `structure-check`, and I ran that after writing the tests rather than before. That is a repeated cause, so the class fix was incomplete; see lessons.
4. **CODEOWNERS drift, class code.** A new unit manifest changes the generated CODEOWNERS. My `scripts/generate --check all` ran before the manifest existed, so it could not see the drift; `prepush` refused it. The unpushed commit was amended (never a pushed one).
5. **12 structure tests red, class code, one cause.** The shared fixture body had no block. Fixed once, in the shared `PLAN` constant.
6. **Crash on a checkout without the effort registry, class code.** `config.get` raises for an unregistered name. The body check now falls back to the tool's registry, matching how the plan check skips such a checkout.

## 4. Gate
- **Run 1** (`gate-dev --pr 770`, head 697f60d6, 17:31 to about 17:39). Both the pinned run (base-tip tooling) and the report-only run (head tooling) pass every stage but one: no GitHub Actions workflows, generated drift, schema compat, both secret scans, structure check (16.7 s), install, unit tests (104.6 s) and script tests (111.9 s). The one red stage is `pr metadata`: `plan: item(s) 6 not ticked`, class code. The retro is plan item 6, and the plan put it after the gate. So the gate refuses a head whose last plan item is, by design, written after the gate. The plan order was wrong, not the gate: a retro that waits for the gate is the one item no gated head can tick. Fix: commit the retro, with the run-1 facts, as item 6, then gate that head.
- **Run 2** is on the head that carries this file. Its verdict is in the PR's RETRO and MERGE-READY comments, so recording it here does not move the head again.
- No known defect was hit. The new refusal turned no other stage red, and the effort check passes on this PR's own body over REST.

## 5. Lessons
| Problem | Change that prevents it | Owner |
|---|---|---|
| Brief cites box-only paths to a cloud session | The brief renderer checks every cited path in the target environment, or inlines the file | coordinator (A Torre) |
| "The language baseline" names nothing | Brief template: cite a file or a registry name, never a nickname | coordinator |
| A plan that orders the retro after the gate can never be gated green (`plan_completeness_errors` needs every item ticked on the gated head) | Padrão: the retro is committed before the final gate, and the gate verdict goes in the RETRO comment; or `plan-tick` exempts the retro item | Padrão owner / engine-lane |
| Literal census found after the code was written | Run `scripts/commit-check --local` (prepush) after each new test file, not only at push; or put the census in `local-checks.json` for test files too | engine-lane |
| A drift check run before the last file of the commit existed | Run `scripts/generate --check all` as the last step before commit (prepush already does: it worked as designed) | session rule (Padrão) |
| Fixture bodies built by hand in test files | One shared "valid PR body" fixture for the structure, premises and ship-verify tests, so a new body rule changes one constant | engine-lane |

## 6. The step that should have descended
- **The paragraph "think before acting" became a check.** This unit is that descent: a rule quoted in every brief (an AI-session step, followed and still bypassed on 28/10) became a deterministic stage refusal. Cost this time: about 25 minutes of one session. Owner: engine-lane (done).
- **Finding the active Padrão version and how to add a rule.** Every unit that touches the Padrão repeats it. It should descend to a script: `scripts/padrao new <rule>` copies the active version, adds the rule and prints the activation step. Cost this time: 3 minutes, 4 tool calls. Owner: the Padrão owner.
- **Building a shrink-only baseline list** (registry list, base comparison, stale and gained refusals). The same decision was made for `tests.unhermetic_sites`, `db-package-baseline.json`, the absolute-literals baseline and now `effort.plan_baseline`. It should descend to one shared helper, `baseline.shrink_only(root, base, registry, name, current)`. Cost this time: about 5 minutes and one test class. Owner: engine-lane.
- **Avoiding numeric literals in tests.** It was found by trial twice. It should descend to the prepush local checks (a rule in the engine). Cost: 2 extra structure-check runs (about 40 s) and 2 turns. Owner: engine-lane.
- **The open PRs' bodies need the block.** Each body edit is the same edit. It should descend to the brief template: the Padrão v4 PLAN item (e) asks for the block at plan time, so it arrives with the PR body. Owner: coordinator (activate v4).
