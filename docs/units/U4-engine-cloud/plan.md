# U4 engine-cloud plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/U4-engine-cloud/audit.md`).
2. Plan (this file).
3. Registry `config/registry/cloud.json` and the Python literals of the unit (`postgres.py`, `toolchain.py`, `fonts.py`) read through `config.get`; hermetic tests for them.
4. The shell literals of the unit (`env.sh`, `setup.sh`) read through `python3 scripts/lib/config.py get`; tests.
5. Manifest: unit-owned tests and the registry file in `paths`, battery command, `scripts/generate` outputs (CODEOWNERS, aggregates), gate-script-tests mapping; `scripts/unit-battery engine-cloud` green.
6. Retro (`docs/units/U4-engine-cloud/retro.md`) and the RETRO comment.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 4 -> 5 -> 6`. Commits 3 and 4 touch disjoint files but 4 reads the registry file 3 creates, so they run in sequence; no parallel sub-agents are worth their context cost for a 872-line unit. The coordinator is the only committer.

| Commit | Files owned |
|---|---|
| 3 | `config/registry/cloud.json`, `scripts/cloud/{postgres,toolchain,fonts}.py`, `scripts/tests/{cloud.test.sh,test_cloud.py}`, generated config types |
| 4 | `scripts/cloud/{env.sh,setup.sh}`, the same tests |
| 5 | `units/engine-cloud/unit.json`, `scripts/lib/gate-script-tests.json`, `CODEOWNERS` and other generated outputs |

## Decisions (reported, reversible)
- **Physical form**: the files stay in `scripts/cloud/` (no `@ou` address form for non-TypeScript units outside `apps/web`; every caller uses the paths). Executables keep path and behaviour.
- **Contract**: the manifest `contract` slot is resolved through the unit's address, which this unit cannot have; the public surface (setup.sh, env.sh, preflight, root-session.sh, toolchain.py, postgres.py, fonts.py, toolchain.json, webkit.Dockerfile) is documented in `docs/architecture/UNITS.md` terms in the audit. Verified in commit 5 by trying the slot; if the battery refuses it, it stays unset and the reason is recorded in the PR.
- **Registry owner** `cloud` (file `config/registry/cloud.json`); values keep their current defaults, so behaviour is unchanged.

## Premises
Premises: P-03, P-04, P-05, P-07.
- P-03 (physical form logical for non-TS units; blast radius medium: if wrong, the files would move later in a follow-up, importers never change).
- P-05 (literals migrate with the unit; radius medium).
- P-07 (contract changes expand->contract; radius low, no breaking change here).
- **CRITICAL**: none (no production, money or source of truth; `setup.sh` runs at every session start, so a default that changed would break all sessions: defaults are the current literals, proven by tests).

## Targeted tests, then one final gate
3: `scripts/tests/cloud.test.sh`, `test-db.test.sh`, `scripts/structure-check`. 4: same plus `preflight.test.sh`, `cloud-tail.test.sh`, `shellcheck` on both scripts. 5: `scripts/unit-battery engine-cloud`, `scripts/generate --check`. Then one `gate-dev`.
