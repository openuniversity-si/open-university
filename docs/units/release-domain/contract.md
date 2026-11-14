# release-domain contract (1.0.0)

The unit is logical (S1, P-03). Its published surface is the modules below with no single entry file; adding an `index.ts` re-export would be a shim (D-029), so the manifest `contract` slot stays empty and the surface is recorded here. Importers keep `@ou/release-domain/<file>`.

| Module | Exports other units import |
|---|---|
| `baked.ts` | `bakedReleaseSchema` |
| `countries.ts` | `Country`, `groupByCountry` |
| `cover-read.ts` | `courseCoverAssets`, `ownerRefsForCourses` |
| `credits.ts` | `ImageCredit`, `imageCredits` |
| `fallback.ts` | `normalizeBakedRelease` |
| `home.ts` | `HomeCourse`, `HomePortal`, `HomeRail`, `authorCourses`, `homeCourses`, `signedOutHome` |
| `metadata.ts` | `courseMetadataInput`, `courseShareArt`, `coverShareImage`, `lessonMetadataInput` |
| `page-frame.ts` | `frameForCourses` |
| `page-read.ts` | `PageRead` |
| `preview.ts` | `previewTables` |
| `progress-reading.ts` | `progressViewCourse` |
| `public-routes.ts` | `publicRouteSnapshot` |
| `queries.ts` | `Course`, `Edition`, `Lesson`, `authorOf`, `courseBySlug`, `editionCount`, `editionOf`, `editionsForCourse`, `lessonAbout`, `lessonBySlug`, `lessonLabel`, `lessonNeighbors`, `lessonsForCourse`, `lessonsForEdition` |
| `universities.ts` | `AreaGroup`, `University`, `UniversityRail`, `findUniversity`, `splitArea`, `universities`, `universityAreas` |
| `view-model.ts` | `BillboardView`, `CardView`, `RailView`, `UniversityCard`, `UniversityGroupView`, `UniversityRailView`, `authorMediaIds`, `authorsClient`, `billboardView`, `cardView`, `featuredMediaIds`, `homeClient`, `signedInHomeClient`, `signedInMediaIds`, `universityDetailRails`, `universityIndexView` |

Every other export (and `intents.ts`, imported by nobody outside the unit) is internal. A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, remove the old. No consumer file is edited here.

Literals: no tunable (`config_check` clean, no `x-literal-sites` entry); the D-063 prose census is unchanged. UI text: none. Battery: `scripts/unit-battery release-domain`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.
