# ORIGIN-PUSH-HISTORY — retro

Whole unit, from the brief to the gate. Facts with evidence. Gate state at writing: **not green** (class env, see 4).

## 1. Brief quality
- **Wrong branch name.** The brief said `feat/origin-push-history`; the session's designated branch was `claude/origin-push-history-8yzfcu`. Used the designated one; recorded in the PR.
- **`gh api` route not available.** The brief said open the PR via `gh api`. Session policy: `gh` only for search; PR and comments through the GitHub MCP tools. Used MCP; recorded.
- **Attribution conflict.** The attribution reminder asked for a `Co-Authored-By: Claude <model>` trailer; the model-identity rule forbids model identifiers in commits. Omitted the model line; kept `Plan:` and the session link.
- **Measured facts, partly unverifiable.** Fact 1 (no push route) could not be checked: the repo has no OpenAPI file. Facts 2–4 were confirmed in the repo (fixture and handler). Recorded as carried, not verified.
- **Premises line.** The brief asked for premises, but the registry lookup returned no output for the webhook query, so the PR says `Premises: none`. The lookup's silence was not investigated.
- **The brief's own rules were right.** The "no fix-up", "push every commit", "claim new files" rules each mattered and were followed; none was ambiguous except the points above.

## 2. Audit and plan
- Held: fact 2 (refUpdates carries before/after/forced/created), fact 3 (head_ref.pushed carries only the sha), fact 4 (the handler keeps two refs). The control plane's `EventLog` is capped and its `complete` flag is whole-log, so a windowed read cannot prove a branch's completeness on a busy log. Held as found.
- Plan changed in one place from the brief's shape: the completeness rule is "creation record in window, or untruncated window", not just "untruncated". Reason: `complete` is `false` on any log over 2000 records, so the untruncated branch alone would refuse almost everything.
- Premises A1–A3 stayed CRITICAL and unverified against the vendor. Premise A3 (the redeploy) is the coordinator's step after merge.

## 3. Execution (timeline, commit times 2026-11-02 UTC)
| Time | Commit | What happened |
|---|---|---|
| 13:22 | 5c4b95e4 | STEP 0: branch, skeleton, pushed. Draft PR #1081 and the first STATUS followed. |
| 13:24 | b56d0103 | Audit. Root causes written in a non-template form (see 5, class 1). |
| 13:26 | a0d1556a | Plan with alternatives and the commit graph. |
| 13:30 | 21d640ca | Structure check (27 warnings): causes reformatted, intake and research added. |
| 13:31 | c7b39c22 | Contract. `schemas.lock` refused `format`; then refused missing subject fields; reverted the lock twice (see 5). |
| 13:33 | ecb99135 | Control plane. One existing test expected 0 records on a base push; updated to 1, with the reason in the commit. |
| (no commit) | — | Adapter work, before its commit. Four suites failed on pinned refusals (see 5, class 5). Fixed in the same commit as the adapter. |
| 13:39 | 0c942a0f | Refused by the pre-push check: `scripts/lib/forge_origin_history.py` claimed by no unit. |
| 13:40 | 0dbff03a | Same commit amended (unpushed) with the unit claim; pushed by the guard. |
| — | gate | `gate-dev` exit 1: class env, `TOWER_EVENTS_TOKEN` missing. |

Dead ends: `node --test <dir>` ran one bogus entry (1 test, 1 failure, a runner-argument problem); the three files were then run explicitly. No other dead end.

Time and quota: not measured in this session. The commits show the spread: the audit and plan took 13:22–13:30, the code commits 13:31–13:40.

## 4. Gate
- Runs: 1 `gate-dev` (background), exit 1, class **env**: `FAIL gate evidence: forge_events could not record the verdict: no events token: set $TOWER_EVENTS_TOKEN`. The session has no such token; I did not create one. Blocker posted on the PR with the remedy and the retry command.
- Local verdicts (not the gate): operation check origin 0/0, github 0/0; forge-events suite exit 0; control-plane 38/38; contract tests 55 OK; `schema-compat` 0 errors; `structure-check` 0 errors.
- Known base defects hit: none in the base. The creation-push judgement in `commit_check.push_errors` (plan A5) is pre-existing and not changed.
- **Mismatch I made:** the background notice said exit 0. My wrapper's last command was `tail`, so its status was reported, not the gate's. The file showed `EXIT=1`. The notice was wrong for the reason I gave above; the gate was red.

## 5. Failures, root cause classes, and the change that would prevent each
1. **Audit form.** The root causes were written as bullets, not the `### R<n>` / `Cadeia de porquês:` / `Classe:` form the structure check reads; intake, research and two audit sections were missing. Class: **regra faltando** in the brief template (the brief did not name the form). Fix that prevents it: STEP 0's skeleton is generated from the templates, so every required heading is present from the first commit. Owner: process (templates), coordinator.
2. **Contract `format` keyword unsupported.** `event_contracts._event_subset` refuses `format`. Discovered at `lock`, after the file existed. Class: **mecanismo faltando** (the subset is documented nowhere a contract author reads). Fix: a schema lint at edit time that names the unsupported keywords, or a contract template listing the subset. Owner: engine-events.
3. **Subject fields.** Every event payload must carry `repo`, `pr`, `sha`, `unit`, `premises` (`forge-events.subject_fields`). Found at `lock`; cost one lock revert and two retries. Class: **regra faltando** in the contract template. Fix: the template generates the subject fields. Owner: engine-events.
4. **Refused pushes: unclaimed new file.** `scripts/lib/forge_origin_history.py` was a production file of no unit; the pre-push check refused the push, not the commit. Class: **mecanismo faltando** — the claim is checked only at push, not when a file is created. Fix: the local commit check (5 s budget) flags an unclaimed production file. Cost: one refused push, one amend of an unpushed commit. Owner: engine-structure / push guard.
5. **Pinned refusals in four suites.** The refusal text and the missing-name expectation were asserted in `test_forge_contract.py` (which I searched), and also in `test_forge_events.py` (3 tests) and `test_operation_integration.py` (1 test), which I did not search. Class: **mecanismo faltando** (R3 in the audit: nothing shows a pinned refusal is stale). The audit's search was too narrow: it grepped for the symbol in one file, not for the pattern across the tests. Fix (one commit): all four assert the new state; the routing test asserts the call reaches the main adapter; the proof test keeps an `unimplemented-proof` case. Owner: engine-operations. Descent: the operation check should list every test that pins a refusal of a demand.
6. **Gate exit reporting.** My wrapper printed `tail`'s status; the notice reported exit 0 for a red gate. Class: **bug local** (my command). Fix: the last command of a wrapper is the one whose status I report. Owner: me (session habit); the background-task runner could report the wrapped command's status.
7. **Base test expectation.** `services/control-plane/test/origin.test.mjs` expected 0 `recorded` for a base push. This is a deliberate change of behaviour, so the expectation moved to 1 with the reason in the commit. Not a failure; recorded because the same count is an easy trap.

8. **Literal census warnings (not errors).** The new test file adds literals the engine-events census counts: the number 40 in SHA fixtures (27 written, 20 allowed at the base), the numbers 2 and 3 in length asserts (39 and 6 written, 37 and 5 allowed), and a URL prefix (1 written, 0 allowed). `structure-check` went from 0 errors / 17 warnings to 0 errors / 21 warnings. The acceptance was "no new errors", which holds. Not fixed here: the census baseline is the census owner's to regenerate (D-063), and a fix-up commit only to shave literals would churn the history. Class: **regra faltando** for test fixtures (no shared SHA helper and no rule that a fixture's literals count). Fix: a shared test helper for SHA fixtures, owned by engine-events. Owner: engine-events.

## 6. The step that should have descended
Cost ladder: deterministic script < rule in the engine < AI session < Daniel's attention. Each item: the step it should descend to, what it cost here, and the owner.

| Work done by an AI today | Would be identical tomorrow | Should descend to | Cost here | Owner |
|---|---|---|---|---|
| Writing audit causes, intake and research to the structure check's form (2 rounds) | yes | a skeleton generated from `docs/process/templates/` at STEP 0 | ~5 min, 1 structure-check round | process / coordinator |
| Finding the event subset and subject fields by failing `lock` | yes | a contract lint and a generated contract template | 1 lock revert, 2 retries | engine-events |
| Claiming a new production file in a unit manifest after a refused push | yes | the local commit check flags an unclaimed new production file | 1 refused push, 1 amend | engine-structure |
| Searching tests for a pinned refusal by symbol in one file | yes | the operation check lists every test that pins a refusal of a demand | 1 failed suite (18 s), 3 edits | engine-operations |
| Writing the PR body's commit checklist and verdict by hand | yes | generated from commit trailers (`Plan:`) and the verdict's own output | ~3 edits of the body | engine-delivery |
| Deciding the branch name, the `gh` route and the model-line attribution | yes (standing conflicts) | the brief launcher carries the session's branch and tool route; attribution rule stated once | 3 decisions, each recorded in a comment | coordinator |

Decisions that repeat an earlier unit's decision: the designated branch versus the brief's branch, and the `gh` versus MCP route. Both should be fixed in the launch brief, not decided per session.

## 7. Lessons (summary)
- Generate the unit's skeleton from the templates at STEP 0 (owner: process).
- Lint contracts at edit time, and generate the subject fields (owner: engine-events).
- Check unit claims for new files at commit time, not at push (owner: engine-structure).
- When a refusal changes to a behaviour, search the whole test tree for the pattern and let the operation check list the pinned tests (owner: engine-operations).
- The wrapper's last command must be the gate (owner: session habit).
- The brief launcher sets the branch and the tool route (owner: coordinator).

## Verdict to date
- Operation check origin: 3 refusals -> 0 refusals; github 0 -> 0.
- Gate: not green (env class, `TOWER_EVENTS_TOKEN`). The unit is not ready and not merged.

## 8. Continuation (this session, after 13:46 UTC)

Written from the branch and the PR body after the session that wrote sections 1–7 went idle (its record: gate blocked on
`TOWER_EVENTS_TOKEN`). Its sections stay as written; this one adds what was measured here and what it changes.

### 8.1 Verified here (head `2ef6df47a` plus this section)

| Check | Result | Command |
|---|---|---|
| Operation check, origin | 0 findings, 0 refusals (base `018ecf6`: 3 refusals — stall_report pushes, commit_check pushes, commit_check force_pushes) | `OU_CONFIG_STORE=file PYTHONPATH=scripts/lib python3 -m scripts.lib.unit_check --operations --adapter origin` |
| Operation check, github | 0 findings, 0 refusals (base: 0) | `… --adapter github` |
| `test_origin_history` | 10 OK | `python3 -m unittest scripts.tests.forge_events.test_origin_history` |
| `test_forge_contract` | 73 OK — must run from `scripts/tests/forge_events` (imports `test_control`) | `cd scripts/tests/forge_events && python3 -m unittest test_forge_contract` |
| `forge-events.test.sh` | 8 OK, exit 0 | `PYTHONPATH=. OU_CONFIG_STORE=file bash scripts/tests/forge-events.test.sh` |
| control plane | 38 pass, 0 fail (`core`, `events`, `origin`, named explicitly) | `node --test services/control-plane/test/core.test.mjs …events… …origin…` |
| `structure-check` | 0 errors. Warnings: 807 head vs 803 base (the PR body's "27 → 18" is not reproduced). The +4 are literal-census warnings from `test_origin_history.py` (numbers 2, 3, 40 and one URL), lifted by the exception regime, not errors | `OU_CONFIG_STORE=file scripts/structure-check` |
| PR body structure check | 0 errors, 27 warnings: `Fit-Review` line not in the required form; `## Cheapest useful effort` lacks `Action:`, `Cost:`, `Cheaper rejected:` | `scripts/structure-check --pr-body <file>` |
| `gate-dev --pr 1081` | not reached: exit 2 at preflight (env) — three runs | `OU_CONFIG_STORE=file bash scripts/gate-dev --pr 1081` |

### 8.2 The env failures of this session, in order

1. `missing toolchain: node, pnpm, gh, gitleaks, vercel, postgres`: setup had not run. Class env. Ran `scripts/cloud/setup.sh`.
2. Setup exited 1 on a GitHub 429 from the shared config store. Class env. Rerun with `OU_CONFIG_STORE=file`: exit 0.
3. Preflight then `missing toolchain: python`, with `.toolchain/bin/python3` = pinned 3.12.15. Class env. Cause: `.toolchain/attest.json`
   kept `python: absent` from the failed first run and was not invalidated. Deleted that gitignored cache; the next preflight
   passed that gap. Descent: setup clears the memo when it links a binary (section 5 of this retro's owners).
4. Preflight then `GitHub REST is not reachable`. Class env. Cause: the engine's GitHub client refuses with `ForgeRateError`
   (`gh: exit 429 … asks to wait N s`, N above `github-client.max_wait_s` = 120). N counted 756 → 562 → 554 → 401 s over ~25 min.
   The same endpoints answer 200 through the egress proxy (`GET /user`, `GET /repos/openuniversity-si/open-university`, `GET /rate_limit`
   with 14,902 of 15,000 core left). So the wait is the client's budget, not the credential or the network. Open at writing.
5. The commit's pre-commit hook regenerates derived files through the same config store: refused until `OU_CONFIG_STORE=file`.
6. The push guard refused the push because the remote had moved (`2ef6df47a`, the other session's two commits). Resolved by
   rebasing my unpushed commit onto that tip, not by force. A backup of the original commit is kept as the local branch
   `backup-retro-mine`.

### 8.3 Decisions taken here (and why)

- Status went to `docs/units/ORIGIN-PUSH-HISTORY/retro.md` (this section), not the event channel: `forge_events emit`
  accepts only contracted kinds and none records a session's status. A new kind would be a contract change (out of scope).
- The `python` memo was cleared, not the check changed: the check is right, the cache was stale. A cache reset is reversible
  and touches no source.
- No `TOWER_EVENTS_TOKEN` was set or invented; the other session's blocker is noted as its own, not this one's.
- The Fit-Review and effort fields of the PR body are corrected to the required form, and the verdict numbers to the
  measured ones. The body's claims are the author's to fix; nothing was merged or marked ready until the gate is green.

### 8.4 Open at writing

- `gate-dev --pr 1081` has not run to a verdict (blocked by 8.2.4). Next: wait out the client's wait, run preflight, run the
  gate; mark #1081 ready only if green, and say so in the STATUS record.
- Armed step (section 6 of this retro): deploy the control plane after the merge and read `ref.updated` on the next push.
- Literal-census warnings (+4) in `test_origin_history.py`: not fixed here (warnings, not errors); owner engine-events.

### 8.5 Gate result after the GitHub wait cleared

- Preflight: ok (the toolchain from `scripts/cloud/setup.sh`, with `source scripts/cloud/env.sh`).
- `OU_CONFIG_STORE=file bash scripts/gate-dev --pr 1081`: exit 1, `GATE: FAILED`. The only recorded line:
  `FAIL gate evidence: forge_events could not record the verdict: no events token: set $TOWER_EVENTS_TOKEN (class env)`,
  preceded by `gate proof: v3 verdict (the run has no proof binding ...)`. No stage result is printed, so the gate
  gives no verdict on the head.
- The missing credential is `TOWER_EVENTS_TOKEN` (unset in this session). `docs/units/CONTROL-CHANNEL/intake.md` names it as
  an operator step. A session cannot create it, so this unit is not ready: the PR stays draft, and nothing is marked ready
  or merged. Owner: the operator who provisions the sessions' token (Daniel).
- The operation checks (8.1) and the hand battery are unaffected by this: they ran on the same head and are green.
