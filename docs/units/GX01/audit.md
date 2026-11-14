# GX-01 audit (read-only, base `mod/roadmap-integration` at `54e05d45`)

Brief: GX-01 "Preflight first; classified driver aborts; machine class line" (plan §3.3, D-070). Every cited source was checked on the base; each exists.

## Findings

| # | Where (base) | Finding |
|---|---|---|
| A1 | `scripts/gate-local:75-88` | The flock (`:82`) and the slot (`:87`) are taken before any environment check; the worktree is added at `:159`. A machine gap is found only at `:177-191`, after both, so a broken box queues and holds a slot first. |
| A2 | `scripts/gate-local:179,182,188,191` | The four database aborts print `FAIL local postgres did not start`, `FAIL could not create the local test database`, `FAIL missing TEST_DATABASE_URL` (stderr) and `FAIL could not reset the local test database`. None prints a class; `gate_classify.ENV` (`gate_classify.py:19-22`) matches none of them, so a consumer reading the log calls them `code` (the 27/10 tier-2 eject). |
| A3 | `scripts/gate-local:126-127` | The exit trap calls `gate_report.py "$logs" "$sha" "$rc"` with three arguments, so `gate_report.py:234` (`len(sys.argv) > 5`) never publishes evidence for an aborted gate: an abort with `--pr` leaves no `gate.failed`. |
| A4 | `scripts/gate_report.py:224-231` | With five arguments and `rc != 0`, `apply_coverage(..., check_missing=False)` leaves `missingStages` empty, and `adjudicate_known_defects` runs. An abort needs the opposite: the mode's expected stages as missing and no adjudication. |
| A5 | `scripts/lib/gate-runner.sh:39` | A red stage prints `class: <kind> — <action>` (human line). No fixed-format machine line exists; GX-02 would have to parse the human line. |
| A6 | `scripts/lib/preflight.py:87-103,116-117,58-76` | `database_problems()` (starts the server when the binary matches, like setup), `browser_problems()` and `missing_tools()` exist and are reusable; `problems()` also probes credentials and GitHub REST (network), which a gate does not need. |
| A7 | `config/registry/gate.json`, `env.json` | No `gate.class_line_prefix`, `gate.preflight_enabled`, `env.gate_preflight_probes`. Generated modules: `scripts/lib/generated/config_registry_{gate,env}.py` (`scripts/generate`). |
| A8 | `scripts/lib/config.py:235-246` | The registry default store is `github` (network). The driver exports `OU_CONFIG_STORE=file` only at `gate-local:171`; a config read in the preflight must set it itself, or the preflight reaches the network. |
| A9 | `scripts/tests/gate-db.test.sh`, `invoker-tooling.test.sh` | Both run the real `gate-local` in a throwaway repo without a toolchain or PostgreSQL. A preflight would abort them; they need the registered switch off in their copied registry (the documented rollback path, not a bypass of the real gate). |
| A10 | Healthy container | `preflight.browser_problems()`, `missing_tools()`, `database_problems()` all return `[]` here: the default probe set passes on a healthy container. |

## Tests that cover the diff (`scripts/lib/gate-script-tests.json`)
`preflight.test.sh` (`test_preflight.py`), `gate-classify.test.sh` (`test_gate_classify.py`), `gate-report-skips.test.sh` (`test_gate_report_skips.py`), `gate-local.test.sh`, `gate-db.test.sh`, `invoker-tooling.test.sh`, `gate-isolation.test.sh`, `test_gate_failures.py` (forge fake pattern: `forge_events.MemoryAdapter`).

## Known defects / collisions
GX-04 runs in the same slot on `pr_ready.py`, `plan_tick.py`, `test_pr_ready.py`: disjoint from this unit. `gate_report.py` and `gate-local` are single-writer in S2 (plan §4.4).

## Branch
The session harness named `claude/gx01-gate-preflight-oduv7e`; the brief names `mod/gx01` (brief standard v2 rule 1). Decision: `mod/gx01`, the brief's explicit branch, since one unit has one branch.
