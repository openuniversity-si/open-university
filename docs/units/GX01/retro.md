# GX-01 retro (preflight first; classified driver aborts; machine class line)

PR #694, branch `mod/gx01`, base `mod/roadmap-integration` (54e05d45 at start, ef01174d after GX-04 #693 merged). Times are UTC on 27/10 (BRT = UTC−3). The final verdict numbers are in the PR's RETRO and MERGE-READY comments, because this file is committed before the final verdict run so that run judges the exact final head.

## 1. Brief quality
- Clear scope, files, keys and acceptance. Every cited line (`gate-local:75-159`, `:126-127`, `gate_report.py:233-234`, `gate-runner.sh:39`, `preflight.py:87-103`) matched the base.
- Missing: the brief did not say that the verdict-of-record (base-tip tooling, D-A3) runs the head's tests with the **base's** `config` module already imported by the hermetic `sitecustomize`. So a unit that adds a registry key and reads it in a test fails the base-tip gate with `not a registered parameter`. Every GX unit that adds a key (most of wave 0/1) hits this.
- Missing: the literal census (LT1) also judges tests. The brief's "no literals" was read as "config values". In practice it also means exit codes, argv positions and test fixtures (dates, PR numbers, `'a' * 40`).
- Ambiguous: the observable says "PostgreSQL stopped → exit 2". The reused `database_problems()` starts a stopped server, as setup and the old `pgtools_start` did. So the abort happens only when the server cannot start. Decided and recorded in the PR.
- Conflict: the harness named branch `claude/gx01-gate-preflight-oduv7e` and the brief named `mod/gx01`. Used the brief's branch.

## 2. Audit and plan
- Premises held. P-26 (hosts reachable) was not needed: the gate preflight probes no network. GA-PG5 (a preflight is not a loosening) held. P-42/P-46 were not exercised directly.
- The CRITICAL false-positive premise was mitigated as planned: the `gate.preflight_enabled` switch, plus a test that the real probe code passes on a healthy machine (leaf probes faked as on a healthy box). Measured on this container: all three probes return no gap, and `preflight.py gate` takes about 0.17 s.
- Plan changes:
  - The `--db` gate probes only the toolchain, because it needs no local database or browser.
  - Two throwaway-repo tests (`gate-db.test.sh`, `invoker-tooling.test.sh`) switch the preflight off in their copied registry.
  - A seventh code commit (literals and own-root config reads) was added after verdict run 1. It carries `Plan: 3, 4, 5, 6`.

## 3. Execution (timeline, UTC)
| Time | Commit | Note |
|---|---|---|
| 17:26 | 93eac8f3 audit, ca034050 plan | draft PR #694 opened after commit 1 |
| 17:27 | 4201dbfd class line + ENV strings | `gate-classify` 10/10 |
| 17:28 | 39cd1fdd preflight probe set | `preflight` 20/20 |
| 17:29 | 9a7ddb6c gate_report abort path | `gate-report-skips` 7/7 (forge fake) |
| 17:32 | 8d26c7b9 driver | gate-local 46/46, gate-db 22/22, invoker 7/7, isolation 46/46 |
| 17:32 | bd975a45 merge of base ef01174d | coordinator 14:31 BRT |
| 17:34–17:41 | verdict run 1 (red) | see §4 |
| 17:41 | e94e8a21 literals + own-root config | structure-check 0 errors locally; tests green with and without the base tip's hermetic path |

Failures and root-cause classes:
1. **Literal census (LT1).** New numbers in engine code and tests. The cause: before pushing I ran only the push guard's `structure_fast`, not the full `scripts/structure-check` (brief standard v2 rule 4). The fix covers the class in every file of the unit: one default for the driver's abort code, a shared `SETUP_EXIT`, argument unpacking, `.parent` chains instead of `parents[2]`, and a registered time budget instead of a bare 10. A second, smaller round was needed (`parents[2]` in the own-root fix). That was caught locally by the census before the push, not by a gate.
2. **Hermetic wall clock.** `time.monotonic()` in a Python unit test. The timing proof moved to the shell test of the real driver.
3. **Base-tip config module.** Described in §1. The fix is to pass the module's own checkout root to `config.get` in the two modules that read new keys. It was reproduced and verified cheaply by running the tests with `PYTHONPATH=<base-tip>/scripts/lib/hermetic`, with no extra gate.
4. **Pre-existing base defect.** `gate-db.test.sh` failed 7/22 on the base itself, because its hand-picked lib list lacked `gate_select`. It now copies the whole library, as `invoker-tooling` does (22/22). It is not in the known-defect registry.

Dead ends: none. Waits: verdict run 1, 6 m 39 s.

## 4. Gate
- Verdict run 1: tooling = clean base-tip checkout ef01174d, head bd975a45, `scripts/gate-dev --pr 694`, **FAILED**, 397.6 s. The structure check failed (census), and script tests failed (`gate-classify`, `gate-local`, `preflight`, `hermetic`, `literals`, `structure-check`), all from classes 1–3. The other five stages that ran passed. The run published `gate.failed` 9301004f3000.
- Final verdict run: on the head that carries this file. Numbers are in the RETRO comment.
- Known defects hit: none registered. One unregistered base defect was fixed (class 4).

## 5. Lessons (change → owner)
- **Base-tip verdict vs new registry keys.** Every lib module that reads a key added in the same PR must read its own checkout's registry. Better, the hermetic `sitecustomize` of the tooling should not pre-import `config` into the head's process, or `config` should resolve its root from `OU_SUBJECT_ROOT`. → GX-05 (pinned gate) owner. Until then, add one line to the GX brief template.
- **Run the full structure check before every push of code.** `structure_fast` does not include the literal census. Either add the census (≈ 1 s here) to `config/registry/local-checks.json` or make the brief template's rule 4 explicit: `scripts/structure-check --base <base> --pr <n>`. → engine-push-guard owner.
- **The brief template should say "no literals" includes exit codes, argv positions and test fixtures**, and name the census command `python3 scripts/lib/literal_census.py`. → brief/program owner (A Torre).
- **Throwaway-repo gate tests should copy the whole library**, never a hand-picked list. Done for `gate-db.test.sh`; any new such test should follow it. → engine-gate-run owner.
- **Test-only time bounds belong in shell tests of the real driver**, since Python unit tests are hermetic and have no wall clock. → note for GX units with timing acceptance.
