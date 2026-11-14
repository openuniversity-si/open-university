# GX-05 plan — Pinned gate: the base tip's tooling judges

Implements B-09 and GA-PG1 (P-46), closes G-12 and the gate side of G-13. Decision: D-070. Audit: [audit.md](audit.md).

## Design

1. `scripts/gate-local --pr N | --sha S` (any mode), when `gate-pin.enabled` and `OU_GATE_PINNED` is unset and the run
   is not `--report-only`, calls `scripts/lib/gate_pin.py prepare` **before** the preflight, the flock and the slot:
   - base sha: `--pr` → `baseRefOid` of the one `pr view --json headRefOid,baseRefOid` REST call; the pair is handed to
     the child in `OU_GATE_PR_IDENTITY`, so the child makes no second call. `--sha` → the `base` of `--plan-file` when
     given (a batch), else the fetched tip of `gate.batch_base_ref`.
   - tool root: the caller itself when its HEAD is the base sha and its tracked tree is clean; otherwise the tool
     worktree `<gate.slot_dir>/<gate-pin.dir>/<clone id>/<base sha>` (one per base sha and clone), created under a
     directory lock (`flock`), reused while the base sha is the same. Each user holds a shared lock on it for the whole
     run; eviction keeps the `gate-pin.keep_worktrees` most recently used base shas and never removes one in use.
   - the tool worktree's `.toolchain` is a symlink to the caller's `.toolchain` (refreshed each run): the pinned
     `env.sh` resolves the caller's PATH, `OU_PYTHON` and PostgreSQL; the caller's `env.sh` exports are inherited
     (its `TEST_DATABASE_URL`, the caller's own test database, wins).
   (Plan-v2: this step runs in the `pin` hook, after the preflight and before the lock; see the plan change below.)
2. The caller prints `gate: pinned to <base sha>` and `gate: version <gate_version>` first, then runs
   `<tool root>/scripts/gate-local <same args>` with `OU_GATE_PINNED=<base sha>`, `OU_GATE_RECORD_ROOT=<caller>`,
   `GATE_RECORD_DIR`/`GATE_LOCK_FILE` of the caller (the base tooling before GX-05 honours both). The verdict, the
   events, `pr.ready`, the status comment and the record come from that run; the caller exits with its code.
3. When the diff `base...head` touches the gate (`commit_check.GATE_FILE`) and `gate-pin.report_only_on_gate_change`,
   the caller then runs the head's own tooling (a throwaway worktree of the head, or the caller when it is the clean
   head) with `--report-only`: no events, no record (own record dir), no status, no `pr.ready`. It prints
   `gate: advisory (head tooling, report-only): PASSED|FAILED` and, for `--pr`, upserts one advisory comment with its own
   marker line (`<gate.status_marker> sha=<head> mode=<mode>+advisory`) next to the status comment. Never changes the
   exit code.
4. `gate_version` = the git tree id of `scripts/` at the tooling commit (content-addressed: same tooling, same version).
   The record extras (`gate_version`) are GX-10's proof hook (plan-v2); this unit prints the version.
5. Rollback: `gate-pin.enabled=false` through `scripts/config` (one key); then `gate-local` is the pre-GX-05 driver.

Deviation recorded: D-A5 says one worktree per (base sha, gate slot); §3.3 says one per base sha guarded by a lock.
The pin is taken before the slot (the child must be a top-level gate, audit A5) and the tool tree is read-only, so
this unit follows §3.3: one per base sha per clone, shared under a shared lock.

## Commits (dependency graph)

| # | Commit | Files owned | Depends on |
|---|---|---|---|
| 1 | audit + worktree-add measurement | `docs/units/GX05/audit.md` | — |
| 2 | plan | `docs/units/GX05/plan.md` | 1 |
| 3 | registry + `gate_pin.py` library + unit tests | `config/registry/gate-pin.json`, `scripts/lib/generated/config_registry_gate_pin.py`, `scripts/lib/gate_pin.py`, `scripts/tests/test_gate_pin.py`, `scripts/tests/gate-pin.test.sh`, `units/engine-gate-run/unit.json`, `CODEOWNERS` (generated) | 2 (real: interfaces) |
| 4 | `gate-local` wiring: pin, `--report-only`, record fields; fixture e2e (pinned red, own green); fixture tests that test something else turn the switch off | `scripts/gate-local`, `scripts/tests/gate-pin.test.sh`, `scripts/tests/test_gate_pin.py`, `scripts/tests/gate-db.test.sh`, `scripts/tests/invoker-tooling.test.sh` | 3 (real: calls `gate_pin.py`) |
| 5 | base merged in, then test map entry + operations doc | `scripts/lib/gate-script-tests.json`, `docs/operations/local-gate.md` | 4 (collision only: late by design, brief) |
| 6 | retro | `docs/units/GX05/retro.md` | gate |

Critical path: 3 (~40 min) → 4 (~40 min) → 5 (~10 min) → base-tip gate (~5-10 min wall) → 6 (~15 min). Commits 3 and 4
share `gate_pin.py`'s interface, a real edge; no parallel commit is worth a second writer here, so the coordinator
writes them in order (max 2 sub-agents, used for read-only review only).

## Premises

| Premise | Blast radius | Status |
|---|---|---|
| P-46 (GA-PG1): the verdict comes from the pinned gate on the base tip | CRITICAL (source of truth of the verdict) | decided YES (§1.1), not re-opened |
| P-13 exclusive unit ownership | medium | new files go to `units/engine-gate-run/unit.json`; `CODEOWNERS` from `scripts/generate` |
| P-42 (GA-P01) content-addressed proof | low (indirect: `gate_version` is a tree id) | decided |
| The pre-GX-05 base tooling honours `GATE_RECORD_DIR` and `GATE_LOCK_FILE` (audit A3) | medium | verified on the base |

## Tests

- Commit 3: `python3 scripts/tests/test_gate_pin.py` (fixture git repo: resolve, ensure/reuse, lock, eviction,
  gate-change detection, version, toolchain symlink).
- Commit 4: `scripts/run test gate-pin` (fixture repo with a base and a head whose gate differs: pinned red, own
  report-only green, `gate: pinned to` first, `gate_version` printed, record root = caller), `scripts/run test
  gate-isolation`, `gate-local`, `gate-db`, `invoker-tooling`.
- Final: one `scripts/gate-dev --pr <n>` from a clean base-tip checkout (verdict of record, D-A3); the own-checkout run is
  report-only.

## Known base defects expected (owner GX-ENV)
`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (`RegistryMemo.test_a_rewritten_file_is_read_again`),
uid-65534 fs-encoding crash in cloud containers.

## Plan change (coordinator, plan-v2, 27/10)

Plan-v2 (`docs/programs/gate-excellence/plan-v2.md` on `mod/ga4`, §4 GX-05, §5.2) gives `scripts/gate-local`,
`units/engine-gate-run/unit.json` and `CODEOWNERS` to GX-38 (driver hooks `scripts/lib/gate-hooks/*.sh`). The
`gate-local` edit of commit 4 stays minimal; once GX-38 merges, the base is merged in (merge commit), the pin re-exec
moves into `scripts/lib/gate-hooks/pin.sh` (run after the preflight, before the lock), the manifest edits GX-38's
pre-claims cover are dropped, `scripts/generate` regenerates `CODEOWNERS`, and the head is gated again. If GX-38 has not
merged when this head is green, MERGE-READY is posted with that follow-up named.

Done after GX-38 #700 merged (`ffcf6397`): the re-exec is `gate_hook_pin`, the hand-off reader `gate_pin_handoff`, both
in `scripts/lib/gate-hooks/pin.sh`. GX-38 pre-claimed only `scripts/lib/gate-hooks/**`, so this unit's own new paths stay
in `units/engine-gate-run/unit.json` (merged as the union) and `CODEOWNERS` is regenerated by `scripts/generate`.
