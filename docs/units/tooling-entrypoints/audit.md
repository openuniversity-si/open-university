# U4 tooling-entrypoints: audit

Read-only findings, base `3df754d4` (mod/roadmap-integration). Premises: P-03, P-04, P-05, P-07.

- **Physical form.** Units stay logical (S1, P-03): the files keep `apps/web/scripts/**`, no path moves, so D-029 leaves no old path behind. The
  `@ou/tooling-entrypoints/*` alias already existed and is generated; `scripts/generate addresses` added the bare `@ou/tooling-entrypoints`.
- **Consumers.** Two files of other units import it, both through the alias and not edited: `src/catalog/domain/cover-resolve.test.ts`
  (`jsonText`) and `scripts/lib/catalog-cli/sync.test.ts` (`jsonbKeyOrder`, `snapshotFiles`).
- **Contract.** `apps/web/scripts/index.ts`, version 1.0.0, exports exactly those three names (the file is added to the manifest paths).
  The bake, `tower-catalog`, `tower-factory` and `fidelity-sync` are executables run by `pnpm`, not contract.
- **Battery.** `scripts/unit-battery tooling-entrypoints` is green in about 9.5 s of `battery.unit_time_limit` (10 s). The types step dominates;
  the limit is untouched. A slower machine can push it over; the fix is a smaller type project, not a looser limit (owner: tooling-lane).
- **Literals (not delivered here).** The census (`pnpm literals:census --list`) lists 187 occurrences in the unit's files: factory-cli.ts 122,
  catalog-bake.ts 23, tower-catalog.ts 21, fidelity-sync.ts 12, catalog-export.ts 4, catalog-files.ts 4, tower-factory.ts 1. They are CLI flags,
  messages and exit codes; zeroing them needs documented D-063 catalog keys, and the tunable ones need a TypeScript reader of the config registry,
  which does not exist (`config.get` is Python). Writing one here would be a parallel mechanism (D-069 item 1), so the list only shrinks and this PR
  adds none. Same call as the merged U4 fidelity-runner. Owner of the follow-up: tooling-lane with the TypeScript config reader line.
- **Size.** Under `units.size_ceiling`; not oversize.
- **Generated outputs.** python-types, ts-types, locale-text, addresses and codeowners show no drift (`scripts/generate --check <target>`). The on-demand
  `intents` target fails with ERR_MODULE_NOT_FOUND in this cloud environment on the base too; it is not committed and not touched here.

D-069 items: 3 (no literal added, count recorded), 5 (hermetic battery), 8 (CODEOWNERS generated from the manifest), 14 (battery within limit).
