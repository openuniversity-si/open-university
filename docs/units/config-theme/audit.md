# config-theme audit (U4)

Read-only findings, base `mod/roadmap-integration` 76cc5f2d.

- Unit: two generated files under `apps/web/src/config/domain/theme/` (`names.ts` 977 lines, `values.ts` 975 lines), both written by `pnpm tokens:generate` from `apps/web/design/figma-tokens.snapshot.json` and both in `units.size_exempt_globs`, so the unit counts zero toward `units.size_ceiling` (no `unit.oversize`). Owner `config-lane`; `requires` none.
- Physical form: S1 keeps units logical (P-03). The generator, its test (`apps/web/scripts/lib/tokens.test.ts`) and the D-063 catalog entry name these exact paths, so a move would only churn them; nothing moves and nothing is deleted (D-029). `units/config-theme/` holds the manifest; `@ou/config-theme/*` is generated into `apps/web/tsconfig.json`.
- Importers (consumer units, not edited): five files import `@ou/config-theme/values` (`ui/tokens/layout.ts`, `ui/LazyPoster/near.ts`, `ui/Billboard/Billboard.tsx`, the course view and the lesson view) and `config/domain/documents.ts` (config-documents) imports both modules by relative path.
- Imported surface (the contract) is in `contract.md`.
- Tunables: the files are generated D-063 catalogs (`scripts/lib/literal-catalogs/config.json`, `generatedFrom` the Figma snapshot), the one sanctioned place for these values; `config_check` reports no tunable and no `x-literal-sites` entry names them. The allowlist for these files is already zero.
- UI text: none.
- Battery: `scripts/unit-battery config-theme` green (types only; the unit has no tests of its own, its generator test belongs to `tooling-entrypoints`).
