# catalog-hierarchy contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is the modules below with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/catalog-hierarchy/<file>`.

| Module | Exports other units import |
|---|---|
| `cache-tags.ts` | `CATALOG_TAG` |
| `config` (`config/index.ts`) | `CONFIG_KEYS`, `OTHER_COUNTRIES_TITLE` |
| `course-status.ts` | `courseStatus` |
| `course-view.ts` | `courseView` |
| `cover-object.ts` | `coverHashes`, `resolveCatalogCoverObjects` |
| `cover-resolve.ts` | `coverOwner`, `lessonCoverAssets`, `redundantLessons`, `resolveCover` |
| `cover-source.ts` | `COVER_FROM_PATTERN`, `REQUIRED_COVERS` |
| `lesson-address.ts` | `SLUG_PATTERN`, `cleanLessonSlug` |
| `preview-token.ts` | `PREVIEW_LABEL`, `PREVIEW_MAX_MINUTES`, `PreviewClaims`, `safePreviewTarget`, `signPreviewToken`, `verifyPreviewToken` |
| `read-queries.ts` | `CatalogQueriesPort` and the projection types (`AdminCourseFilter`, `AdminCoursePage`, `AdminCourseSummary`, `AuthorsDirectoryProjection`, `CourseDetailProjection`, `ReadScope`, `RedirectProjection`, `UniversityAreaProjection`, `UniversityPageProjection`) |
| `slug-course.ts` | `reslugCourse`, `slugCourseFromTables` |

Every other export is internal. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: no tunable (`config_check` clean, no `x-literal-sites` entry); the D-063 prose census is unchanged. UI text: none. Battery: `scripts/unit-battery catalog-hierarchy`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
