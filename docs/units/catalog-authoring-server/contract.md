# catalog-authoring-server contract (1.0.0)

The surface is recorded here and the manifest `contract` slot stays empty. A `contract.ts` entry would add a file and 16 lines to the catalog cell, which sits exactly at its budget (84 files, 8631 lines, `L3.context-size`); the budget is never loosened (D-069 item 14), and a re-export file would be a shim (D-029). Importers keep their relative paths until their own units move. What other units import today:

| Module | Exports other units import |
|---|---|
| `authors.ts` | `authorView`, `createAuthor`, `deleteAuthor`, `insertAuthor`, `listAuthors`, `patchAuthor` |
| `common.ts` | `coursePath`, `factsOf`, `iso`, `lessonPath`, `livePaths`, `pendingFor`, `readCourseState`, `readState`, `readTablesAndRevisions` |
| `courses.ts` | `catalogCourseState`, `classifyCourses`, `courseDetail`, `courseView`, `createCourse`, `getCourse`, `insertCourse`, `listCourses`, `patchCourse`, `publishCourse`, `publishCourseBatch`, `setCourseStatus`, `unpublishCourse`, `unpublishInTx` |
| `editions.ts` | `createEdition`, `editionView`, `insertEdition`, `listEditions`, `patchEdition`, `reorderEditions`, `EditionView` (type) |
| `lesson-slugs.ts` | `putLessonSlugs` |
| `lessons.ts` | `createLesson`, `insertLesson`, `lessonView`, `looksLikeLab`, `patchLesson`, `reorderEditionLessons`, `reorderLessons`, `videoOwner`, `videoTaken` |
| `reference.ts` | `createArea`, `createLicense`, `createSource`, `createSubarea`, `listAreas`, `listLicenses`, `listSources`, `listSubareas`, `moveArea`, `patchArea`, `patchSource` |
| `texts.ts` | `approveTexts`, `getTexts`, `putTexts`, `revokeTexts` |

Everything else (`changed`, `editionRow`, `assertCourseEdition`, ...) is private to the unit. A breaking change goes expand->contract (P-07, D-029); no consumer file is edited here. Generated outputs (alias, CODEOWNERS) come from `scripts/generate`.

Open item: the 423 D-063 census offenders of the eight files are not migrated here (see `plan.md`); the baseline did not grow.
