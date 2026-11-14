# GX-05 audit (read-only, base `mod/roadmap-integration` at `4bc4dd04`)

Brief: GX-05 "Pinned gate: the base tip's tooling judges" (plan §3.3, B-09, GA-PG1 = P-46, D-070). The base tip is
`4bc4dd04` (GX-00 #692, GX-04 #693, GX-01 #694 and GX-07 #677 merged). Every cited source was checked on the base.

## Measurement (D-A5, acceptance 1)

`git worktree add -q --detach <pin dir>/<base sha> <base sha>` of the base tip `4bc4dd04` on this container
(4 vCPUs, 166 MiB pack, 2613 tracked files), three runs in a throwaway directory, removed after each run:

| run | add | worktree size | `worktree remove --force` |
|---|---|---|---|
| 1 | 626 ms | 23 MB | 57 ms |
| 2 | 203 ms | 23 MB | 59 ms |
| 3 | 699 ms | 23 MB | 66 ms |

Cost: under 0.7 s and 23 MB per base sha (no `node_modules`, no `.toolchain/`). A reused worktree costs nothing; two
kept base shas (`gate-pin.keep_worktrees`) hold about 46 MB. A throwaway worktree of the head for the report-only run
costs the same, so it is affordable on every gate-touching PR.

## Findings

| # | Where (base) | Finding |
|---|---|---|
| A1 | `scripts/gate-local:69-71` | `tool_root` is the checkout that contains the script and `src_root="$tool_root"`: the tooling is whoever invokes it. A PR's own checkout grades itself (G-12); the D-A3 interim is a manual base-tip checkout. |
| A2 | `scripts/gate-local:132-145` | `--pr` reads `headRefOid,baseRefOid` in one REST call (`github_cli.py pr view`, `github_api.py:176`), after the preflight, the flock and the slot. The base sha is therefore known only late; resolving it again early is the same call, so the pinned child must reuse it (`OU_GATE_PR_IDENTITY`) instead of a second call. |
| A3 | `scripts/gate-local:72-80,113` | `record_dir`, the lock and `github_cli` all hang off `src_root`; the old (pre-GX-05) driver already honours `GATE_RECORD_DIR` and `GATE_LOCK_FILE`. Setting both from the caller makes even the current base tooling write its record into the caller's checkout, so pinning works before GX-05 merges. `github_cli` should come from `tool_root` (it is tooling). |
| A4 | `scripts/cloud/env.sh:8-41,112-116` | `env.sh` prepends `<its root>/.toolchain/bin` and sets `OU_PYTHON` from it unconditionally; `pgtools_start` runs `<its root>/scripts/cloud/postgres.py`. A fresh tool worktree has no `.toolchain/`, so its `env.sh` would fall back to `/usr/bin/python3` and a missing postgres. `TEST_DATABASE_URL` is kept when already set (`:112`), so the caller's per-checkout database survives. Fix: the tool worktree's `.toolchain` is a symlink to the caller's (refreshed each run), and the caller's environment is exported to the child. |
| A5 | `scripts/lib/gate-isolation.sh:51-80,113-116` | A gate that inherits `OU_GATE_SLOT` shares its parent's slot and gets no slot checkout dir. The pin therefore runs before the slot and the flock, so the pinned child is a top-level gate. |
| A6 | `scripts/lib/commit_check.py:35` | `GATE_FILE` is the gate-change pattern (D-025); importable. |
| A7 | `scripts/lib/gate_report.py:259-272` | Events (`gate.passed/failed`), `pr.ready` and the final status are produced only when `pr` is passed; with `pr=''` it writes `stages.json` only. A report-only run passes no `pr` to the report and skips `gate_status begin`; the runner's stage hooks are no-ops without a state file (`gate_status.py:230-235`). |
| A8 | `scripts/lib/gate_status.py:38,160-176` | The status comment is found by `marker_line(sha, mode)`; `forge_events.upsert_comment` (`forge_events.py:288`) edits in place. An advisory comment with its own marker line (`mode=<mode>+advisory`) is idempotent per head without touching `gate_status.py` (engine-gate-report). |
| A9 | `scripts/gate-local:166,176,230` | `rm -f "$record_dir/$sha.$suffix"` at checkout and on failure: a report-only run must use its own record dir or it would delete the pinned run's pass record. |
| A10 | `config/registry/gate.json:64,383` | `gate.slot_dir` (`/tmp`) and `gate.batch_base_ref` (`origin/mod/roadmap-integration`) exist; no `gate-pin.*` key exists. `config/registry/gate-pin.json` is new (owner `gate-pin`), generated module `scripts/lib/generated/config_registry_gate_pin.py`. |
| A11 | `scripts/tests/gate-db.test.sh`, `invoker-tooling.test.sh` | Both run the real `gate-local --pr` in a throwaway repo; GX-01 turned its preflight off there through the registered switch. Pinning would resolve and add a worktree there; same treatment (`gate-pin.enabled=false` in the copied registry), since they test the DB stages and the invoker tooling, not the pin. |
| A12 | `scripts/lib/gate-script-tests.json:2-7` | `scripts/gate-local` is a fallback path: a change to it runs the whole script suite. The new tests need entries (`gate-pin.test.sh`); GX-07 #677 is merged, GX-08 not yet, so the entry goes into this file. |
| A13 | Self-grading residue | The caller decides whether to pin, so a PR that removes the pin from its own `gate-local` is not pinned when run from its own checkout. The pinned run writes `pinned=<base sha>` and `gate_version=<tree>` into the record so a consumer (train, ship-verify, GX-10 v4) can require it; the verdict of record runs from the coordinator/train checkout. |

## Tests that cover the diff
`gate-local.test.sh`, `gate-isolation.test.sh`, `gate-db.test.sh`, `invoker-tooling.test.sh`, `gate-batch.test.sh`; plus the whole suite (fallback path).

## Known defects / collisions
Known base env failures (A Torre 14:45): `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh`
(`RegistryMemo.test_a_rewritten_file_is_read_again`), uid-65534 fs-encoding crash; owner GX-ENV. GX-02/GX-03 files
are disjoint from this unit.

## Branch
The session harness named `claude/gx05-pinned-gate-ga3602`; the brief names `mod/gx05` (brief standard v2 rule 1,
GX-01 precedent). Decision: `mod/gx05`.
