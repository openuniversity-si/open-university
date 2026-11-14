# tooling-catalog-cli-content contract (1.0.0)

Entry: `apps/web/scripts/lib/catalog-cli/commands/contract.ts`, address `@ou/tooling-catalog-cli-content`. It exports only what other units import today:

| Export | Source | Importer |
|---|---|---|
| `courseCommands`, `editionCommands`, `importCommands`, `authorCommands`, `lessonCommands`, `referenceCommands`, `textCommands` | the six modules | `catalog-cli/registry.ts` (relative path, core unit) |
| `checkTextsFile` | `texts.ts` | `catalog-cli/sync.test.ts` (`@ou/tooling-catalog-cli-content/texts.ts`) |

Everything else (`resolveCourseId`, `parseBatchFile`, `moveLesson`, ...) is private to the unit. A breaking change goes expand->contract (P-07, D-029); no consumer file is edited here. Generated outputs (`tsconfig` aliases, CODEOWNERS) come from `scripts/generate`.

Open item: the 1073 D-063 census offenders of the six files are not migrated here (see `plan.md`); the baseline did not grow.
