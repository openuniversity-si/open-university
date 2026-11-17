import { bundleBody } from "../domain/bundle.ts";
import * as c from "../domain/contracts.ts";
import { defineRoute, type AdminRoute } from "./http.ts";
import { createAuthor, deleteAuthor, listAuthors, patchAuthor } from "./authors.ts";
import { classifyCourses, createCourse, getCourse, listCourses, patchCourse, publishCourse, publishCourseBatch, setCourseStatus, unpublishCourse } from "./courses.ts";
import { deleteCourse, deleteEdition, deleteLesson, mediaReferences } from "./deletion.ts";
import { createEdition, listEditions, patchEdition, reorderEditions } from "./editions.ts";
import { runDoctor } from "./doctor.ts";
import { getHome, putHome } from "./home.ts";
import { createImport, draftImport } from "./imports.ts";
import { putLessonSlugs } from "./lesson-slugs.ts";
import { createLesson, patchLesson, reorderEditionLessons, reorderLessons } from "./lessons.ts";
import { createPreviewToken, readAudit } from "./misc.ts";
import { createRedirect, deleteRedirect, listRedirects } from "./redirects.ts";
import { createArea, createLicense, createSource, createSubarea, listAreas, listLicenses, listSources, listSubareas, moveArea, patchArea, patchSource } from "./reference.ts";
import { activateRelease, createRelease, getRelease, listReleases } from "./release-routes.ts";
import { exportTables } from "./tables.ts";
import { applyBundle, diffBundle, exportBundle, validateBundle } from "./bundles.ts";
import { shipBatch } from "./ship-batch.ts";
import { applyBatch } from "./batch-apply.ts";
import { applyBatchBody } from "../domain/batch-v2.ts";
import { shipBatchBody } from "../domain/ship-batch.ts";
import { advanceJob, claimJob, completeCatalogJob, renewJob } from "../../admin/server/job-handlers.ts";
import { inventoryLifecycle, mutateLifecycle, resetLifecyclePreview } from "../../admin/server/lifecycle-handlers.ts";
import { lifecycleGcBody, lifecycleResetBody } from "../../admin/lifecycle-body.ts";
import { jobAdvanceBody, jobClaimBody, jobCompleteBody, jobRenewBody } from "../../admin/job-body.ts";
import { approveTexts, getTexts, putTexts, revokeTexts } from "./texts.ts";

// Every route of plan §3.2 under /api/admin/catalog, plus GET /tables (the normalized export `tower-catalog snapshot` writes). app/api/admin/catalog/**/route.ts only delegates here (routes.test.ts
// checks both directions), and the integration suite fails if a route lacks its cases.
const noParams = c.noQuery;

export const ADMIN_CATALOG_ROUTES: readonly AdminRoute[] = [
  defineRoute({ method: "GET", path: "/courses", action: null, idempotency: "none", params: noParams, query: c.coursesQuery, body: null, handler: listCourses }),
  defineRoute({ method: "POST", path: "/courses", action: "course.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.courseCreate, handler: createCourse }),
  defineRoute({ method: "GET", path: "/courses/:id", action: null, idempotency: "none", params: c.idParams, query: c.noQuery, body: null, handler: getCourse }),
  defineRoute({ method: "PATCH", path: "/courses/:id", action: "course.update", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.coursePatch, handler: patchCourse }),
  defineRoute({ method: "DELETE", path: "/courses/:id", action: "course.delete", idempotency: "none", params: c.idParams, query: c.courseDeleteQuery, body: null, handler: deleteCourse }),
  defineRoute({ method: "POST", path: "/courses/:id/status", action: "course.status", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.courseStatusBody, handler: setCourseStatus }),
  defineRoute({ method: "POST", path: "/courses/:id/publish", action: "course.publish", idempotency: "required", params: c.idParams, query: c.noQuery, body: c.publishBody, handler: publishCourse }),
  defineRoute({ method: "POST", path: "/courses/publish-batch", action: "course.publish.batch", idempotency: "required", params: noParams, query: c.noQuery, body: c.publishBatchBody, handler: publishCourseBatch }),
  defineRoute({ method: "POST", path: "/courses/classify", action: "course.classify", idempotency: "required", params: noParams, query: c.noQuery, body: c.classifyBody, handler: classifyCourses }),
  defineRoute({ method: "POST", path: "/courses/:id/unpublish", action: "course.unpublish", idempotency: "required", params: c.idParams, query: c.noQuery, body: c.unpublishBody, handler: unpublishCourse }),
  defineRoute({ method: "GET", path: "/courses/:id/editions", action: null, idempotency: "none", params: c.idParams, query: c.noQuery, body: null, handler: listEditions }),
  defineRoute({ method: "POST", path: "/courses/:id/editions", action: "edition.create", idempotency: "required", params: c.idParams, query: c.noQuery, body: c.editionCreate, handler: createEdition }),
  defineRoute({ method: "PUT", path: "/courses/:id/editions/order", action: "edition.reorder", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.editionOrder, handler: reorderEditions }),
  defineRoute({ method: "PATCH", path: "/editions/:id", action: "edition.update", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.editionPatch, handler: patchEdition }),
  defineRoute({ method: "DELETE", path: "/editions/:id", action: "edition.delete", idempotency: "none", params: c.idParams, query: c.editionDeleteQuery, body: null, handler: deleteEdition }),
  defineRoute({ method: "PUT", path: "/editions/:id/lessons/order", action: "lesson.reorder", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.lessonOrder, handler: reorderEditionLessons }),
  defineRoute({ method: "POST", path: "/courses/:id/lessons", action: "lesson.create", idempotency: "required", params: c.idParams, query: c.noQuery, body: c.lessonCreate, handler: createLesson }),
  defineRoute({ method: "PUT", path: "/courses/:id/lessons/order", action: "lesson.reorder", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.lessonOrder, handler: reorderLessons }),
  defineRoute({ method: "PUT", path: "/lessons/slugs", action: "lesson.slug", idempotency: "required", params: noParams, query: c.noQuery, body: c.lessonSlugsPut, handler: putLessonSlugs }),
  defineRoute({ method: "PATCH", path: "/lessons/:id", action: "lesson.update", idempotency: "none", params: c.idParams, query: c.lessonPatchQuery, body: c.lessonPatch, handler: patchLesson }),
  defineRoute({ method: "DELETE", path: "/lessons/:id", action: "lesson.delete", idempotency: "none", params: c.idParams, query: c.lessonDeleteQuery, body: null, handler: deleteLesson }),
  defineRoute({ method: "GET", path: "/authors", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: listAuthors }),
  defineRoute({ method: "POST", path: "/authors", action: "author.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.authorCreate, handler: createAuthor }),
  defineRoute({ method: "PATCH", path: "/authors/:id", action: "author.update", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.authorPatch, handler: patchAuthor }),
  defineRoute({ method: "DELETE", path: "/authors/:id", action: "author.delete", idempotency: "none", params: c.idParams, query: c.authorDeleteQuery, body: null, handler: deleteAuthor }),
  defineRoute({ method: "GET", path: "/texts", action: null, idempotency: "none", params: noParams, query: c.textsQuery, body: null, handler: getTexts }),
  defineRoute({ method: "PUT", path: "/texts", action: "text.put", idempotency: "none", params: noParams, query: c.noQuery, body: c.textsPut, handler: putTexts }),
  defineRoute({ method: "POST", path: "/texts/approve", action: "text.approve", idempotency: "required", params: noParams, query: c.noQuery, body: c.textsApprove, handler: approveTexts }),
  defineRoute({ method: "POST", path: "/texts/revoke", action: "text.revoke", idempotency: "required", params: noParams, query: c.noQuery, body: c.textsRevoke, handler: revokeTexts }),
  defineRoute({ method: "GET", path: "/home", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: getHome }),
  defineRoute({ method: "PUT", path: "/home", action: "home.set", idempotency: "none", params: noParams, query: c.noQuery, body: c.homePut, handler: putHome }),
  defineRoute({ method: "GET", path: "/areas", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: listAreas }),
  defineRoute({ method: "POST", path: "/areas", action: "area.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.areaCreate, handler: createArea }),
  defineRoute({ method: "PATCH", path: "/areas/:id", action: "area.update", idempotency: "none", params: c.idParams, query: c.noQuery, body: c.areaPatch, handler: patchArea }),
  defineRoute({ method: "POST", path: "/areas/:id/move", action: "area.move", idempotency: "required", params: c.idParams, query: c.noQuery, body: c.areaMove, handler: moveArea }),
  defineRoute({ method: "GET", path: "/subareas", action: null, idempotency: "none", params: noParams, query: c.subareasQuery, body: null, handler: listSubareas }),
  defineRoute({ method: "POST", path: "/subareas", action: "subarea.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.subareaCreate, handler: createSubarea }),
  defineRoute({ method: "GET", path: "/licenses", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: listLicenses }),
  defineRoute({ method: "POST", path: "/licenses", action: "license.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.licenseCreate, handler: createLicense }),
  defineRoute({ method: "GET", path: "/sources", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: listSources }),
  defineRoute({ method: "POST", path: "/sources", action: "source.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.sourceCreate, handler: createSource }),
  defineRoute({ method: "PATCH", path: "/sources/:id", action: "source.update", idempotency: "none", params: c.sourceParams, query: c.noQuery, body: c.sourcePatch, handler: patchSource }),
  defineRoute({ method: "POST", path: "/imports", action: "import.create", idempotency: "required", params: noParams, query: c.noQuery, body: c.importCreate, handler: createImport }),
  defineRoute({ method: "POST", path: "/imports/:id/draft", action: "import.draft", idempotency: "required", params: c.importParams, query: c.noQuery, body: c.importDraft, handler: draftImport }),
  defineRoute({ method: "GET", path: "/releases", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: listReleases }),
  defineRoute({ method: "GET", path: "/releases/:n", action: null, idempotency: "none", params: c.releaseParams, query: c.noQuery, body: null, handler: getRelease }),
  defineRoute({ method: "POST", path: "/releases", action: "release.create", idempotency: "unless-dry-run", params: noParams, query: c.releasesCreateQuery, body: c.releaseCreate, handler: createRelease }),
  defineRoute({ method: "POST", path: "/releases/:n/activate", action: "release.activate", idempotency: "required", params: c.releaseParams, query: c.noQuery, body: c.releaseActivate, handler: activateRelease }),
  defineRoute({ method: "GET", path: "/redirects", action: null, idempotency: "none", params: noParams, query: c.redirectsQuery, body: null, handler: listRedirects }),
  defineRoute({ method: "POST", path: "/redirects", action: "redirect.create", idempotency: "none", params: noParams, query: c.noQuery, body: c.redirectCreate, handler: createRedirect }),
  defineRoute({ method: "DELETE", path: "/redirects", action: "redirect.delete", idempotency: "none", params: noParams, query: c.redirectDeleteQuery, body: null, handler: deleteRedirect }),
  defineRoute({ method: "POST", path: "/preview-token", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: c.previewTokenBody, handler: createPreviewToken }),
  defineRoute({ method: "GET", path: "/audit", action: null, idempotency: "none", params: noParams, query: c.auditQuery, body: null, handler: readAudit }),
  defineRoute({ method: "GET", path: "/tables", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: exportTables }),
  defineRoute({ method: "POST", path: "/media/references", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: c.mediaReferencesBody, handler: mediaReferences }),
  defineRoute({ method: "GET", path: "/doctor", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: runDoctor }),
  defineRoute({ method: "POST", path: "/bundles/validate", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: bundleBody, handler: validateBundle }),
  defineRoute({ method: "POST", path: "/bundles/diff", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: bundleBody, handler: diffBundle }),
  defineRoute({ method: "POST", path: "/bundles/apply", action: "course.bundle", idempotency: "required", params: noParams, query: c.noQuery, body: bundleBody, handler: applyBundle }),
  defineRoute({ method: "POST", path: "/bundles/ship", action: "course.publish.ship", idempotency: "required", params: noParams, query: c.noQuery, body: shipBatchBody, handler: shipBatch }),
  defineRoute({ method: "POST", path: "/batches/apply", action: "course.publish.apply", idempotency: "required", params: noParams, query: c.noQuery, body: applyBatchBody, handler: applyBatch }),
  defineRoute({ method: "POST", path: "/bundles/export", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: bundleBody, handler: exportBundle }),
  defineRoute({ method: "POST", path: "/jobs/claim", action: "job.claim", idempotency: "none", params: noParams, query: c.noQuery, body: jobClaimBody, handler: claimJob }),
  defineRoute({ method: "POST", path: "/jobs/:id/renew", action: "job.renew", idempotency: "none", params: c.idParams, query: c.noQuery, body: jobRenewBody, handler: renewJob }),
  defineRoute({ method: "POST", path: "/jobs/:id/advance", action: "job.advance", idempotency: "required", params: c.idParams, query: c.noQuery, body: jobAdvanceBody, handler: advanceJob }),
  defineRoute({ method: "POST", path: "/jobs/:id/complete", action: "job.complete", idempotency: "required", params: c.idParams, query: c.noQuery, body: jobCompleteBody, handler: completeCatalogJob }),
  defineRoute({ method: "POST", path: "/lifecycle/inventory", action: null, idempotency: "none", params: noParams, query: c.noQuery, body: null, handler: inventoryLifecycle }),
  defineRoute({ method: "POST", path: "/lifecycle/gc", action: "lifecycle.gc", idempotency: "required", params: noParams, query: c.noQuery, body: lifecycleGcBody, handler: mutateLifecycle }),
  defineRoute({ method: "POST", path: "/lifecycle/preview-reset", action: "lifecycle.reset", idempotency: "required", params: noParams, query: c.noQuery, body: lifecycleResetBody, handler: resetLifecyclePreview }),
];

export function adminCatalogRoute(key: string): AdminRoute {
  const route = ADMIN_CATALOG_ROUTES.find((entry) => entry.key === key);
  if (!route) throw new Error(`Unknown admin catalog route ${key}.`);
  return route;
}
