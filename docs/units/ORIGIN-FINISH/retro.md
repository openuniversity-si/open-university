# ORIGIN-FINISH — retro

The whole unit, from the brief (02/11 15:59 BRT) to the accepted gate. Facts with evidence. Times are commit times (UTC).

## 1. Brief quality
- **Stale leads.** "13 → 9 baseline calls" and "Origin at 17 of 18 operations" were already false on the base: the
  catalog listed 4 sites and `operation_demands.py` showed origin 23/23 proven (audit L1, L2). The real gap was
  elsewhere: 6 GitHub calls the detector could not see (F1), a hidden dual path in the Origin adapter's git remote (F5),
  the board and the config store selecting GitHub by name (F3, F4) and a preflight that only knew GitHub (F6).
- **An end-to-end proof that cannot run here.** "Prove it on the real thing" assumed the session reaches Origin. It
  does not: the egress answers `CONNECT 403` for `cursor.com`/`api.cursor.com`, there is no `origin` CLI and no
  Cursor credential (diary blocker, 19:06). The brief's item 4 (write the steps, stop) was the right fallback and is
  what this unit did. A brief that orders a live proof should name the environment that can reach the target.
- **Branch conflict, again.** The harness pinned `claude/origin-front-completion-oqv0pq`; the brief named
  `mod/origin-finish`. Took the brief's (one branch, one PR), recorded on the diary. Same decision as ORIGIN-PUSH-HISTORY
  and TRAIN-DEFINITIVE took (in opposite directions): it repeats, see section 6.
- **"Source of truth" is not defined for the forge.** Moving the repository's home to Origin and the config store off
  GitHub are source-of-truth moves the brief does not let the session take, yet "make Origin the forge the operation
  uses" requires both. Resolved by making the switch one checked operator step (plan, outside steps).

## 2. Audit and plan
- Held: R1 (detector blind to the Python argv form; measured 6 on the base with the new rule, 0 on the head), R2 (three
  selections outside the selector), R3 (preflight GitHub-only).
- Broke: the plan's premise that the touched suites were green on the base. Four were red on the base (commit-check,
  forge-events, defect-lifecycle, operation-relations); all four are fixed here (plan `## Base defects expected`).
- New during execution: the Origin fixtures use `openuniversity-si/open-university`, not `forge-events.repo`; the
  cut-over may need that key set too (plan outside step 4).
- The plan changed once (df1f2af2): R4 weighed with alternatives (a structure warning), the base defects and the slug step.

## 3. Execution (timeline)
| Time | Commit | What happened |
|---|---|---|
| 19:04 | 6f7cc58e | STEP 0: skeleton, draft PR #1087 via REST, start on the diary. |
| 19:06 | — | Blocker posted: Origin unreachable from this session. |
| 19:08–19:14 | d85a3cf9, b7959c68, baea592d | Intake/research, audit (two read sub-agents in parallel), plan. |
| 19:18 | 7ab936cb | Board takes the selected forge; dead `release_policy merge` leaves. First push **refused** (I-00f78cc7). |
| 19:21 | 4b80a544 | Origin git-host guard (worker 6a). Push **refused** again (I-85025d4c), pushed from a clean worktree. |
| 19:27 | beaa6ba5 | Preflight checks the selected forge. One local refusal first: an array under a `*_env` key (secret-name rule). |
| 19:37–19:38 | e7eafaeb, d1946395, 55b1c58e | Six shim calls behind the port (workers 5a, 5b), detector, stale pinned refusal. |
| 19:38–23:15 | — | Session quota ran out; resumed at 23:15. |
| 23:16–23:17 | bd337b29, df1f2af2 | Three base-red suites fixed; plan updated. |
| 23:20 | baacc756 | Retro draft; the two push-refusal incidents closed. |
| 23:2x | 4e7f3b81 | The running suite wrote two fake push-refusal incidents (`claude/z`, `claude/f`) into the real tree: push_guard recorded incidents in its own checkout. Fixed. |
| 23:15–23:27 | — | Full `scripts/test-suite` by hand: 145 ran, 7 failed; the 7 rerun on the base: all 7 red there too. |
| 23:4x–00:0x | 15de11b3, e6f9a0ff, f128dd58, 470dd29c, e5479471 | The 7 fixed in three classes (below). |

Failures and their class:
1. **Pushes refused by other workers' dirty files** (2 incidents). Class: mecanismo faltando — prepush judges the
   working tree, and the sub-agents shared it. Rework: a clean worktree per push.
2. **Literal census in new tests** (bare 40, 9, 3, 2, line numbers): three rounds across five test files. Class: regra
   faltando — no shared SHA/number fixture helper; the census counts test integers. Fixed by the existing
   `hashlib.sha1(label)` pattern and named counts; the second and third rounds were the same class reaching files the
   first sweep did not search (the brief's "a second failure from a cause already seen" — reported here).
3. **`*_env` key holding an array.** Class: regra faltando in the registry docs (the secret-name rule is only in
   `config.secret_findings`). Split into two string keys.
4. **Memory doubles without the consumer's surface** (merge_behind evidence test; defects fixture). Class: mecanismo
   faltando — the port checks the stack caller's whole demand, and test doubles do not inherit it. Fixed per double.
5. **Unit `requires` edges** for the new port imports (engine-gate-run, engine-gate-verdict, engine-env): found by
   prepush. Class: mecanismo faltando — the edge is only checked at push.

Where time went: audit ~10 min, plan ~5 min, code with 3 parallel workers ~20 min of wall, integration and
pre-push rounds ~10 min, base defects ~10 min. The quota stop cost ~3.5 h of wall and no work (every step was pushed).

6. **Seven suites red on the base, hidden by the gate's D-151 bypass** (it runs no suite). Three classes, each fixed
   for every instance found by searching the pattern, not the file:
   - forge doubles without their consumer's demanded surface (lessons, plan-tick, train-role, planner-role — the last
     one hung until the suite timeout): class mecanismo faltando; one helper, `scripts/tests/forge_doubles.py`.
   - journal not hermetic: since `log_adapter` became `control`, gate-forge-budget and forge-rate's
     `MeasuredOffComments` built the real control plane and published fixture verdicts to it, and still expected the
     journal on GitHub: class arquitetura/desenho (the switch to control never revisited the forge-budget tests).
   - library fixtures copying `scripts/lib/*.py` without `*.json` (gate-isolation, gate-local budget, gate-pin):
     class regra faltando.
   - push_guard incidents written into the engine's own checkout by tests: bug local, fixed with a test.

## 4. Gate
- Run 1 (`gate-dev --pr 1087`, head 55b1c58e): PASSED under the D-151 bypass; it runs no suite.
- The suites were run by hand (counts in section 7). The defects the bypass hides were the four base-red suites.
- Final run: on the retro's head, below.

## 5. Lessons (each with the change that prevents it and its owner)
- Parallel workers need their own worktree, or prepush must judge the pushed commit, not the tree (engine-structure /
  push guard).
- A shared test fixture for SHAs and counts, so tests never write census integers (engine-events, census owner).
- The registry's secret-name rule belongs in the registry template (engine-config).
- The port's demand check should give tests a "double with this consumer's surface" helper (engine-operations).
- A brief that asks for a live proof names the environment that reaches the target (coordinator, brief template).

## 6. The step that should have descended
| Work done by an AI today | Same tomorrow? | Should descend to | Cost here | Owner |
|---|---|---|---|---|
| Choosing the brief's branch over the harness's | yes (3rd unit) | the launcher sets one branch name for both | 1 decision, 1 diary line | coordinator |
| Measuring vendor calls the detector missed | no longer: the detector now sees them | done (this unit) | ~10 min | — |
| Adding consumer demands, relation sites and unit edges by hand after a port migration | yes | a generator: `operation-relations --write` from `measured()` plus the unit edge from the import | ~10 min, 2 prepush rounds | engine-operations |
| Rewriting test literals after prepush names them | yes | a fixture helper and a lint at edit time | 3 rounds | engine-events |
| Finding base-red suites by hand because the gate bypass runs none | yes | the nightly gate opens the cleanup PR (gate-noite) — it did not for these four | ~10 min | engine-gate |
| Writing the cut-over steps | once | an `scripts/config` preflight for a pending switch (`--check-forge origin`) | ~5 min | engine-config |

## 7. Suites run by hand
- `scripts/test-suite` at 4e7f3b81: 145 script tests ran, 7 failed; the same 7 run on the base 98cf1db5: 7 red.
- `scripts/test-suite` at e5479471: 145 judged, 21 ran, 1 failed (forge-events: test_control read the checkout's
  real local log, an eighth base-hidden defect, fixed in 131cb4d6).
- `scripts/test-suite` at 131cb4d6: **145 judged, 141 by key (inputs unchanged since their pass), 4 ran, 0 failed.**
- Targeted on every code commit: gate-pin 20/20, gate-explain, gate-verdict, merge-behind, decision-next, lane-ship,
  lane-status, pr-creation-path, flow-check, operation-config, config-readers, config, commit-check, vendor-ports,
  preflight, credentials, release-policy, push-guard, units, structure-wiring — all exit 0.
- Checks: `vendor_check` 0 errors (base with the new detector: 6); `operation_demands.py` origin 23 proven, github 23
  proven, confrontation 0; `scripts/operation-relations` 0 findings; `scripts/generate --check` clean;
  `structure-check` 0 errors.

## 8. GitHub in the operation, before and after (counts)
| What | Base 98cf1db5 | This PR |
|---|---|---|
| GitHub baseline sites in the vendor catalog | 4 counted (+6 unseen = 10) | 2 (`setup.sh:gh` cli-version, `toolchain_manifest.py:github.com` artifact download; no forge operation) |
| GitHub calls outside the adapters the detector sees | 0 seen / 6 real | 0 seen / 0 real |
| Modules selecting GitHub without `forge-events.adapter` | 2 (board, Origin's git remote) + config store | 0 + config store (follow-up CONFIG-STORE-CONTROL) |
| Preflight credential checks hard-wired to GitHub | 1 | 0 (the selected forge's) |
| Port operations Origin implements | 23/23 (fakes only) | 23/23, fail-closed git remote, readiness check |
| GitHub-only ref namespace reads (`refs/pull/*`) | 3 | 3 (follow-up ORIGIN-HEAD-REF, TRAIN-DEFINITIVE's files) |
| Forge actually selected | github | github, until the coordinator's outside steps (plan) |

The end-to-end run on Origin did not happen: no environment of the operation reaches Origin (section 1). On this
session `forge_origin.credential_gaps` names exactly what is missing: the `origin` CLI, a Cursor credential, an Origin
git host.

## 9. Cut-over status (03/11)
Outside steps 1–6 of the plan are done (see I-ddaca17c, follow-up): every branch imported on Origin, the VM's remote on
Origin, the overrides set again in the store under the Origin slug, the preflight clean, `forge-events.adapter` =
`origin` in its registry file (#1093), GitHub archived. Step 7's first real run on Origin is this note's own PR, merged with
`origin pr merge`; the train's run waits for the runner (stopped on 03/11, I-ddaca17c).
