# U4 engine-cloud: audit (read-only findings)

Unit `engine-cloud` (`units/engine-cloud/unit.json`): owner `engine-lane`, cell `engine`, ring 2, paths `scripts/cloud/**`
(872 lines in 9 files, 793 production lines by `scripts/units measure`, under `units.size_ceiling`; no `unit.oversize`).

## Files and who uses them (the import graph)

| File | Used by (outside the unit) |
|---|---|
| `setup.sh` | SessionStart hook, `.cursor/environment.json`, docs (`AGENTS.md`, `CLAUDE.md`) |
| `env.sh` | sourced by `scripts/ship-*`, `gate-*`, `neon-*`, `merge-phase`, `production-check`, tests |
| `preflight` | `scripts/ship-tail`, `scripts/tests/preflight.test.sh` |
| `root-session.sh` | `scripts/lib/session_identity.py` exports, `scripts/tests/root-identity.test.sh` |
| `toolchain.py` | `scripts/tower-catalog` (install), `setup.sh` |
| `postgres.py` | `env.sh` (`pgtools_start`), `setup.sh`, `scripts/tests/test-db.test.sh` |
| `fonts.py` | `apps/web/e2e/fixtures/approved-font.ts` |
| `toolchain.json` | `scripts/lib/toolchain_manifest.py`, `scripts/lib/env_manifest.py`, `scripts/lib/toolchain_check.py` |
| `webkit.Dockerfile` | `scripts/cloud-webkit` (unit `engine-capture`) |

Every one of these is an executable or a data file that is called by path. Nothing imports a module of the unit by a
Python or TypeScript import statement (`postgres.py` and `toolchain.py` are only run, never imported), so the contract
surface is the set of entry paths in the table, not an export list.

## Physical form (P-03, S1, U3a)

`@ou/<id>` addresses exist only for units whose home lies inside the TypeScript project (`unit_addresses.py`: "a unit
whose home lies outside the project has no address yet"). `scripts/cloud` is outside `apps/web`, so the unit has no
address form, and `AGENTS.md`, the SessionStart hook and `.cursor/environment.json` all call `scripts/cloud/*` by path. Per
the brief, the files stay in place; the rest of the definition of done is delivered.

## Contract slot

The manifest `contract` slot is checked by the battery through the unit's address home (`unit_battery.plan`): a unit
without an address cannot state one, and a contract entry on it would turn the battery red. Verified in the plan.

## Literals

No registered parameter is spelled as a literal here today (`config_check.check` returns no errors), but the unit holds
tunables that are not registered at all (D-068, D-069 item 3):

- `postgres.py`: `HOST`, `DATABASE`, `ROLE`, default port 54322, `-t 30` pg_ctl wait, `timeout=15` psql, 200-char log
  tail, lock path `/tmp/open-university-postgres.lock`, `initdb` flags (encoding, locale), socket mode.
- `env.sh`: default port `54322`, loopback host list for `NO_PROXY`, uid-0 gate checkout root.
- `setup.sh`: setup lock path, log path, the `54322` in the failure message, log tail 30, minimum bootstrap Python (3.9).
- `toolchain.py`: download timeout 300 s, chunk 1 MiB, user agent, postgres binary list.
- `fonts.py`: the pip package spec.

## Tests

The unit owns no test file: `scripts/tests/{preflight,test-db,root-identity,cloud-tail,toolchain-*}.test.sh` belong to
`engine-env`, `engine-test-support` and others. `scripts/unit-battery engine-cloud` is green in 0 s because it runs
nothing. The unit needs tests of its own for the registered values.

## Lessons and known defects

`scripts/lessons for-area scripts/cloud`: none applied. Known base defects expected: tower-catalog cover concurrency and
read-latency timing tests on 4 vCPU (not touched).
