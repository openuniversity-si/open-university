# TX32 plan

## Design

`apps/web/tsconfig.paths.json` (generated, committed, drift-checked) holds the whole `compilerOptions.paths`: the
hand-written keys (`@/*`, `@tower/*`) kept as written by the renderer, the `@ou/` keys regenerated from the manifests.
`apps/web/tsconfig.json` `extends` it and keeps no `paths`. tsc, Next and ESLint follow `extends`; every script reader
finds the file through the registry (`generate.targets` › addresses `output`, `units.tsconfig_files`,
`gate-areas.db_tsconfig`). No renderer code changes: `unit_addresses.render` already rewrites only the `@ou/` keys of
whatever file the target names, and the project directory (`dirname`) stays `apps/web`.

## Commits (dependency graph)

```
E (engine-lane PR, mod/tx-aliases-engine) ──▶ 3 ──▶ 4 ──▶ 5
1 ──▶ 2 ──▶ 3                                        6 (retro, last)
```

| # | Commit | Files | Targeted tests |
|---|---|---|---|
| 1 | audit skeleton | `docs/units/TX32/audit.md` | none |
| 2 | audit + plan | `docs/units/TX32/{audit,plan}.md` | none |
| E | engine prerequisite (separate engine-lane PR): the battery types project extends the project tsconfig (new key `battery.project_tsconfig`), engine tests read the registry instead of a literal path | `scripts/lib/unit_battery.py`, `config/registry/battery.json`, `scripts/tests/test_{unit_battery,aggregates,gate_areas}.py`, `scripts/lib/generated/config_registry_battery.py` | the three test modules |
| 3+4 | the move: generated `tsconfig.paths.json`, `tsconfig.json` extends it, registry readers point at it, vitest / ou-addresses / test fixtures read it (one commit: the move is green only whole) | `apps/web/tsconfig{,.paths}.json`, `config/registry/{generate,units,gate-areas,gate}.json`, `apps/web/vitest.config.ts`, `apps/web/scripts/lib/{ou-addresses.mjs,*.test.ts}` | `scripts/tests/generate.test.sh`, `pnpm typecheck`, the vitest files touched |
| 5 | drift proof: a test that a new web unit leaves `tsconfig.paths.json` stale and `scripts/generate --check` names `run scripts/generate addresses`, never `tsconfig.json` | test under the tooling lane | that test |
| 6 | retro | `docs/units/TX32/retro.md` | none |

Single final gate: the pinned gate (`OU_CONFIG_STORE=file`, `scripts/gate-dev --pr 750`).

## Premises

| Premise | Blast radius | Note |
|---|---|---|
| P-46 (verdict from the pinned gate on the base tip) | this PR | the pinned gate runs the base's engine code; this PR's head is code under test |
| tsc / Next 16 / typescript-eslint resolve `paths` through `extends` relative to the file that declares them | **CRITICAL**: every import of the web app | proved by `pnpm typecheck` and `pnpm build` in the gate |
| E merges before this PR | **CRITICAL** for the order: without E the battery types step would extend a paths-only file | this PR is not MERGE-READY until E is in its base |

## Pending PRs

Each of the 26 open U4 PRs (#588 #591 #592 #596 #620 #625 #626 #633 #635 #641 #643 #645 #649 #659 #670 #672 #673
#674 #675 #676 #678 #679 #681 #684 #685 #686) resolves its `apps/web/tsconfig.json` hunk at its next base merge by
taking the base side and running `scripts/generate addresses` (which now writes `apps/web/tsconfig.paths.json`).
