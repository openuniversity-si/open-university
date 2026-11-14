# GX-05 RETRO — Pinned gate: the base tip's tooling judges (#697)

Times are UTC (BRT = UTC−3). Session: launched 17:55, halted 17:57 (launch hold) with no work done, resumed 18:04.

## 1. Brief quality
- Clear on scope, acceptance and the verdict of record. Gaps:
  - The branch: the harness named `claude/gx05-pinned-gate-ga3602`, the brief `mod/gx05`. Used the brief's (GX-01 precedent).
  - D-A5 says one tool worktree per (base sha, gate slot); §3.3 says one per base sha under a lock. They conflict: the pin
    must run before the slot, so the pinned run is a top-level gate. §3.3 followed; recorded in the plan.
  - The brief did not carry GX-01's retro finding (§5 there): the base tooling's hermetic `sitecustomize` imports the
    base's `config` into every head test process, so a head module that reads a key it adds fails the base-tip gate.
    GX-01 assigned that class to "GX-05 owner"; it cost one gate run here (§4, run 2).
  - The ownership change (plan-v2: `gate-local`, `unit.json`, `CODEOWNERS` → GX-38) arrived mid-execution. Absorbed
    without rework of `gate_pin.py`: only the driver call moved into `gate-hooks/pin.sh`. GX-38 did not pre-claim GX-05's
    new paths (only `gate-hooks/**`), so the manifest merge was a union, not a drop.

## 2. Audit and plan
- Premises held: P-46 (decided), P-13 (new paths in `engine-gate-run`), the pre-GX-05 driver honours `GATE_RECORD_DIR`
  and `GATE_LOCK_FILE` (A3). Pinning therefore works with the current base tooling, and this PR's own verdict-of-record
  run was a pinned run.
- Measurement (acceptance 1): `git worktree add` of the base tip 203–699 ms, 23 MB; removal ~60 ms.
- Plan changes: (a) plan-v2 hook placement (pin after the preflight, before the lock; the preflight now runs in the
  caller and in the pinned run, a few seconds); (b) the pinned record extras (`pinned=`, `gate_version=`) were dropped
  from `gate-local` because plan-v2 gives record extras to GX-10's proof hook; `gate_version` is printed.
- The advisory view is its own comment (status marker, `mode=<mode>+advisory`) published through
  `gate_status.Publisher`, so `gate_status.py` is untouched.

## 3. Execution (first-parent timeline)
| time | commit | what |
|---|---|---|
| 18:09 | 428eca82 | audit + measurement (Plan 1) |
| 18:10 | a8e0e41c | plan (Plan 2) |
| 18:16 | 29d45aa2 | registry + `gate_pin.py` + unit tests (Plan 3) |
| 18:25 | 03303d23 | `gate-local` wiring, `--report-only`, e2e fixture (Plan 4) |
| 18:25 | 0355797e | test map entry + operations doc (Plan 5) |
| 18:30 | f8f6e807 | base merged (GX-42, docs) |
| 18:32 | 1935f7fe | hand-off trusted only by the pinned tooling, consumed (Plan 4) |
| 18:41 | 6731bb79 | base merged (GX-38 hooks; manifest union, CODEOWNERS regenerated) |
| 18:48 | 32797c67 | pin moved into `gate-hooks/pin.sh`; keys from this checkout's registry (Plan 4) |
| 18:48 | 518cb8c8 | doc + plan follow the hook (Plan 5) |
| 18:49 | 483ec53a | base merged (live-planning #701) |
| 18:52 | d075dea4 | unit tests start from a fresh caller environment (Plan 4) |

Failures and their classes (all found by the gate or by a targeted test, each fixed as a class):
1. **Literal census** (structure check, before commit 4): new files spelled numbers (2, 3, 12, 40, 200, …) and `/bin/sh`.
   Class: every engine number is a registry entry or derived. Fixed by derivation (`removeprefix`, unpacking, sha1 hex,
   `compgen`, `-gt 1`) rather than new keys; caught locally by `scripts/structure-check` before any push of that code.
2. **Undeclared unit imports** (structure check): `forge_events` (engine-events) and `commit_check` (engine-commit-plan).
   Fixed by publishing through `gate_status` (already required) and declaring `engine-commit-plan`. Commit 3 had been
   pushed with this error (the structure check was not run before that push: brief rule v2 (4) missed once).
3. **Leaked pin hand-off** (gate run 1): fixture gates inside script tests inherited `OU_GATE_RECORD_ROOT` and
   `OU_GATE_PR_IDENTITY` from the pinned run and used PR #697's identity. Class: an environment hand-off must be trusted
   only by its addressee and consumed. Fixed in `gate_pin_handoff` (trust iff HEAD == `OU_GATE_PINNED`, then unset) and
   tested with a leaked hand-off.
4. **Base-tip `config` in head processes** (gate run 2): `gate-pin.enabled is not a registered parameter` in the
   fixtures, because the base's hermetic `sitecustomize` had imported the base's `config`. Head-side fix:
   `gate_pin.setting` reads with this checkout's root (GX-01's remedy). A tool-side fix (the `sitecustomize` drops the
   modules it loaded) was tried and **reverted**: `hermetic.install()` pins the config store inside the `config` module
   (`config.pin_store`), so a fresh module loses the pin (`test_hermetic` DeterminismTest went red). Routed (§5).
5. **Fixture missing the hook files** (local, after the GX-38 merge): `invoker-tooling.test.sh` copies `scripts/lib/*.sh`
   but not `scripts/lib/gate-hooks/`; with no-op hooks the miss was silent, with a real `pin.sh` it is fatal. Fixed by
   copying the directory; GX-38's "every hook is a no-op" check now holds `pin` to its own contract.
6. **Unit test read the gate's own environment** (advisory run of gate 3): `GATE_RECORD_DIR` exported by the running gate
   reached the fixture. Same class as 3 (environment hand-off); the second hit is an incident: the class fix of 3
   covered the driver but not the unit-test fixture. Fixed by clearing every hand-off variable in the fixture.

Dead end: the tool-side `sitecustomize` change (≈10 min). Waits: three base moves (each a merge commit, no conflict
except the manifest).

## 4. Gate runs (`scripts/gate-dev --pr 697` from this checkout; the verdict is the pinned base-tip run, D-A3)
| run | head | pinned to (base tip) | verdict (pinned) | advisory (head, report-only) | failures |
|---|---|---|---|---|---|
| 1 | 0355797e | 4bc4dd04 | FAILED, 189.1 s | FAILED, 34.6 s | structure (5 behind), `gate-db`, `invoker-tooling` (class 3), `gate-graph` timing test once (not reproduced, 3/3 local passes) |
| 2 | 1935f7fe | 60392c0c | FAILED, 373.3 s | stopped (base moved: GX-38) | `gate-db`, `invoker-tooling` (class 4) |
| 3 | 483ec53a | 3c834942 | **PASSED, 102.7 s** (`gate.passed` a0fb80c1937d) | FAILED, 22.3 s | advisory only: `gate-pin.test.sh` (class 6) |
| 4 | final head | see the PR comment | see the PR comment | see the PR comment | |

Observed in run 3: the base tooling selects script tests from its **own** `gate-script-tests.json`, which has no
`gate-pin.test.sh` entry yet, so the pinned verdict did not run this unit's new test; the advisory run did. Known env
failures (claude-session, root-identity, config shared store, uid-65534) did not appear on this container.

## 5. Lessons
| problem | change that prevents it | owner |
|---|---|---|
| A head test of a new registry key fails under base tooling (class 4) | `hermetic.install()` should pin the store through the environment (e.g. export `OU_CONFIG_STORE`, which `config.store_kind` already honours) instead of module state, so the `sitecustomize` can drop its engine modules; then no head module needs `config.get(name, ROOT)`. Until then: one line in the GX brief template. | engine-hermetic-tests (GX-ENV or a wave-1 unit) |
| A pinned gate does not run a test the head adds (map read by the base tooling) | GX-08: covers declared in each test's header (head files), so the head's tests are selected by any tooling | GX-08 |
| Environment hand-offs leak into nested gates and fixtures (classes 3, 6) | A shared fixture helper (`scripts/tests/lib`) that starts every fixture from a scrubbed gate environment (`GATE_*`, `OU_GATE_*`), used by every test that runs `gate-local` | engine-test-support |
| Fixtures copy `scripts/lib/*.sh` and miss subdirectories (class 5) | Fixtures copy `scripts/lib/.` recursively (as `gate-db.test.sh` does); one helper for "copy the driver" | engine-test-support |
| The caller decides whether to pin (a PR can drop its own pin) | The train and `ship-verify` accept only evidence whose tooling is the base (GX-10 v4 `gate_version`/pinned fields), and the gate's own GitHub check (GX-17) runs from the train checkout | GX-10, GX-17 |
| A gate-touching commit pushed with a structure error (class 2) | The pre-push local checks (`structure_fast`) did not catch unit imports; add the unit import check to `local-checks.json` within its budget | engine-commit-plan |
