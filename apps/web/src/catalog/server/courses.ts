import type { Queryable } from "../../platform/db/uow.ts";
import { COURSE_LIST_LIMIT, type ClassifyBody, type CourseCreate, type CoursePatch, type CourseStatusBody, type PublishBatchBody, type PublishBody, type UnpublishBody } from "../domain/contracts.ts";
import { changed, classificationProblem as classificationDecision, courseView, textSummary } from "../domain/course-view.ts";
import { createTransition } from "../domain/transition.ts";
import type { CatalogStatePort } from "../ports/commands.ts";
import { activeCourseCovers, activeLessonCovers, lockMediaOwners } from "./media-gateway.ts";
import { clearCourseFeatured, courseIdForSlug, insertCourseRow, lockCoursesForClassification, lockReplacementCourseStatus, markLessonVideoChecked, publishOneCourse, publishPromotedCourses, retargetRedirectPrefix, selectCourseRow, selectCourseStatus, selectKnownCourseIds, selectLessonSlugRows, selectStaleYoutubeVideos, selectSubareaArea, setCourseFeatured, setCourseStatusClearFeatured, subjectAreaExists, updateCourseAreaColumns, updateCourseColumns, updateCourseStatusRow } from "./table-io.ts";
import { lockReleases, lockRow, type Outcome, type Tx } from "./mutation.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { AppError, notFound, preconditionsFailed, stateConflict, unprocessable, type PreconditionFailure } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import type { OEmbedResult } from "../../playback/ports/oembed.ts";
import { videoCheckCutoff } from "../domain/lesson-video.ts";
import { coverDeclarationProblem } from "../domain/cover-source.ts";
import { columnsToVariant } from "../domain/edition-variant.ts";
import { evaluateRules, publishedAreaFailures, publishedKeepsCovers, publishedKeepsRights, type RuleOptions } from "../domain/rules/status.ts";
import { classificationFailures } from "../domain/rules/lifecycle.ts";
import { activeCoverKinds } from "./cover-kinds.ts";
import { addRedirect, assertExists, assertPathFree, coursePath, editionCounts, factsOf, lessonPath, readCourseState, type CatalogState } from "./common.ts";
import { projectCoursePage } from "./list-projection.ts";
import { publishRelease, scheduleActivation, type Publication } from "./releases.ts";

type Ctx<P = { id: string }, Q = unknown, B = unknown> = HandlerContext<P, Q, B>;

export { changed, courseView, textSummary };
type CourseView = ReturnType<typeof courseView>;

type CourseListQuery = { status?: "draft" | "review" | "published" | "archived"; limit?: number; cursor?: string };

/** One page of courses, in `id` order. Counts and pending rules come from that page's projection, not a full catalog read. */
export async function listCourses(context: Ctx<unknown, CourseListQuery>): Promise<Outcome> {
  const limit = context.query.limit ?? COURSE_LIST_LIMIT;
  return { data: await projectCoursePage(context.db, { status: context.query.status, cursor: context.query.cursor, limit }) };
}

export async function createCourse(context: Ctx<unknown, unknown, CourseCreate>): Promise<Outcome> {
  const body = context.body;
  return context.mutate(async (tx) => {
    const row = await insertCourse(tx, body);
    await tx.audit({ action: "course.create", entityKind: "course", entityId: row.id, after: row });
    return { status: 201, data: { course: row }, entity: `course:${row.id}` };
  });
}

/** INSERT of a draft course (id from course_seq) after its references and slug check out. Shared with imports. */
export async function insertCourse(tx: Queryable, body: CourseCreate): Promise<CourseView> {
  await assertExists(tx, "authors", body.authorId, "author");
  if (body.sourceId !== undefined) await assertExists(tx, "content_sources", body.sourceId, "source");
  if (body.licenseCode !== undefined) await assertExists(tx, "licenses", body.licenseCode, "license");
  await assertSlugFree(tx, body.slug, null);
  const declared = coverDeclarationProblem({ id: body.slug, areaId: null, subareaId: null }, body.coverFrom);
  if (declared) throw unprocessable(declared);
  const row = await insertCourseRow(tx, [body.slug, body.authorId, body.title, body.lessonNoun ?? null, body.languageLabel ?? null, body.sourceId ?? null, body.licenseCode ?? null, body.canonicalUrl ?? null, body.attributionText ?? null, body.coverFrom]);
  return courseView(row ?? {});
}

async function assertSlugFree(db: Queryable, slug: string, courseId: string | null): Promise<void> {
  const taken = await courseIdForSlug(db, slug, courseId);
  if (taken) throw new AppError("slug_taken", `The course slug ${slug} is taken by ${String(taken.id)}.`, { courseId: taken.id });
  await assertPathFree(db, coursePath(slug));
}

/** Course + lessons + videos + texts (status, hash) + active covers + rights + preconditions. */
export async function getCourse(context: Ctx): Promise<Outcome> {
  return { data: await courseDetail(context.db, await readCourseState(context.db, [context.params.id]), context.params.id) };
}

export async function courseDetail(db: Queryable, state: CatalogState, id: string) {
  const row = await selectCourseRow(db, id);
  if (!row) throw notFound(`Course ${id}`);
  const course = courseView(row);
  const { tables } = state;
  const editionRows = tables.course_editions.filter((edition) => edition.course_id === id).sort((a, b) => a.position - b.position);
  const editionRank = new Map(editionRows.map((edition, index) => [edition.id, index]));
  const lessonRows = tables.lessons.filter((lesson) => lesson.course_id === id)
    .sort((a, b) => (editionRank.get(a.edition_id) ?? 0) - (editionRank.get(b.edition_id) ?? 0) || a.position - b.position);
  const textView = (kind: string, entityId: string) => Object.fromEntries(tables.catalog_texts.filter((text) => text.entity_kind === kind && text.entity_id === entityId)
    .map((text) => [text.field, textSummary(text)]));
  const covers = await activeCourseCovers(db, id);
  const lessonCovers = await activeLessonCovers(db, lessonRows.map((lesson) => lesson.id));
  const license = tables.licenses.find((entry) => entry.code === course.licenseCode) ?? null;
  const source = tables.content_sources.find((entry) => entry.id === course.sourceId) ?? null;
  const facts = factsOf(state, id);
  const preconditions = facts ? { review: evaluateRules("review", facts), published: evaluateRules("published", facts) } : null;
  const failed = preconditions ? [...preconditions.review, ...preconditions.published] : [];
  const lessonEdition = new Map(lessonRows.map((lesson) => [`lesson:${lesson.id}`, lesson.edition_id]));
  return {
    course,
    texts: textView("course", id),
    // Per edition: counts and the unmet preconditions that concern it or one of its lessons (ADR-21).
    editions: editionRows.map((edition) => ({
      id: edition.id, slug: edition.slug, label: edition.label, term: edition.term, year: edition.year, position: edition.position, resolution: edition.resolution,
      language: edition.language ?? null,
      variant: columnsToVariant(edition.variant_kind, edition.variant_label),
      sourcePlaylistIds: edition.source_playlist_ids, revision: state.revisions.get(edition.id) ?? 1, counts: editionCounts(tables, edition),
      pending: [...new Map(failed.filter((failure) => failure.entity === `edition:${edition.id}` || lessonEdition.get(failure.entity) === edition.id)
        .map((failure) => [`${failure.rule} ${failure.entity} ${failure.message}`, failure])).values()],
    })),
    lessons: lessonRows.map((lesson) => ({
      id: lesson.id, editionId: lesson.edition_id, part: lesson.part, slug: lesson.slug, position: lesson.position, kind: lesson.kind, youtubeTitle: lesson.youtube_title, durationSeconds: lesson.duration_seconds,
      visible: lesson.visible, licenseCode: lesson.license_code, attributionText: lesson.attribution_text, revision: state.revisions.get(lesson.id) ?? 1,
      videos: tables.lesson_videos.filter((video) => video.lesson_id === lesson.id).map((video) => ({ provider: video.provider, externalId: video.external_id, status: video.status, checkedAt: video.checked_at, checkedBy: video.checked_by })),
      texts: textView("lesson", lesson.id),
      covers: lessonCovers.rows.filter((cover) => cover.lesson_id === lesson.id).map((cover) => ({ kind: cover.kind, variant: cover.variant, version: cover.version, url: cover.url })),
    })),
    covers: covers.rows,
    rights: {
      licenseCode: course.licenseCode, license, sourceId: course.sourceId, source, canonicalUrl: course.canonicalUrl, attributionText: course.attributionText,
      rightsStatus: course.rightsStatus, rightsNotes: course.rightsNotes, rightsCheckedBy: course.rightsCheckedBy, rightsCheckedAt: course.rightsCheckedAt,
    },
    homeRows: tables.home_row_items.filter((item) => item.course_id === id).map((item) => item.row_id),
    preconditions,
  };
}

const PATCH_COLUMNS = {
  slug: "slug", authorId: "author_id", title: "title", lessonNoun: "lesson_noun", languageLabel: "language_label", sourceId: "source_id",
  licenseCode: "license_code", canonicalUrl: "canonical_url", attributionText: "attribution_text", rightsStatus: "rights_status", rightsNotes: "rights_notes",
  areaId: "area_id", subareaId: "subarea_id", coverFrom: "cover_from",
} as const;

/**
 * ADR-26: the classification a course ends with must hold: a subarea needs an area and must belong to it. Changing the
 * area of a course that has a subarea, without naming its new subarea (or null), is refused instead of guessed.
 * Returns the problem, or null when the pair is valid.
 */
async function classificationProblem(db: Queryable, course: { id: string; area_id: unknown; subarea_id: unknown }, next: { area_id?: unknown; subarea_id?: unknown }): Promise<string | null> {
  const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
  const area = text(next.area_id !== undefined ? next.area_id : course.area_id);
  const subarea = text(next.subarea_id !== undefined ? next.subarea_id : course.subarea_id);
  const areaExists = area === null || await subjectAreaExists(db, area);
  const early = next.subarea_id === undefined && next.area_id !== undefined && area !== course.area_id;
  let subareaAreaId: string | null = null;
  if (subarea !== null && !early) {
    const subareaRow = await selectSubareaArea(db, subarea);
    subareaAreaId = subareaRow ? text(subareaRow.area_id) : null;
  }
  return classificationDecision(course, next, { areaExists, subareaAreaId });
}

export async function patchCourse(context: Ctx<{ id: string }, unknown, CoursePatch>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  return context.mutate(async (tx) => {
    if (body.areaId !== undefined || body.subareaId !== undefined || body.coverFrom !== undefined) {
      const owners: { owner: "course" | "subarea" | "area"; ownerId: string }[] = [{ owner: "course", ownerId: id }];
      if (typeof body.areaId === "string") owners.push({ owner: "area", ownerId: body.areaId });
      if (typeof body.subareaId === "string") owners.push({ owner: "subarea", ownerId: body.subareaId });
      await lockMediaOwners(tx, owners);
    }
    const locked = await lockRow(tx, "courses", id, `Course ${id}`, body.expectedRevision);
    const before = courseView(locked);
    const next: Record<string, unknown> = {};
    for (const [field, column] of Object.entries(PATCH_COLUMNS)) {
      const value = body[field as keyof typeof PATCH_COLUMNS];
      if (value !== undefined && JSON.stringify(value) !== JSON.stringify(locked[column] ?? null)) next[column] = value;
    }
    if (Object.keys(next).length === EXTENT.empty) return { data: { course: before, noop: true }, noop: true, entity: `course:${id}` };
    if (typeof next.author_id === "string") await assertExists(tx, "authors", next.author_id, "author");
    if (typeof next.source_id === "string") await assertExists(tx, "content_sources", next.source_id, "source");
    if (typeof next.license_code === "string") await assertExists(tx, "licenses", next.license_code, "license");
    if (next.area_id !== undefined || next.subarea_id !== undefined) {
      const problem = await classificationProblem(tx, { id, area_id: locked.area_id, subarea_id: locked.subarea_id }, next);
      if (problem) throw unprocessable(problem);
    }
    if (next.cover_from !== undefined || next.area_id !== undefined || next.subarea_id !== undefined) {
      const areaId = (next.area_id !== undefined ? next.area_id : locked.area_id) as string | null;
      const subareaId = (next.subarea_id !== undefined ? next.subarea_id : locked.subarea_id) as string | null;
      const token = String(next.cover_from !== undefined ? next.cover_from : locked.cover_from);
      const declared = coverDeclarationProblem({ id, areaId, subareaId }, token);
      if (declared) throw unprocessable(declared);
    }
    if (before.status === "published") {
      const failed = [...publishedKeepsRights(id, { ...locked, ...next }), ...publishedAreaFailures(id, next.area_id === undefined ? locked.area_id : next.area_id)];
      if (failed.length > 0) throw preconditionsFailed(failed);
    }
    if (next.rights_status !== undefined) {
      next.rights_checked_by = body.rightsCheckedBy ?? context.actor;
      next.rights_checked_at = context.deps.now().toISOString();
    }
    if (typeof next.slug === "string") await renameCourse(tx, id, before, next.slug);
    const columns = Object.keys(next);
    const row = await updateCourseColumns(tx, id, columns, columns.map((column) => next[column]));
    const after = courseView(row ?? {});
    if (before.status === "published" && (next.cover_from !== undefined || next.subarea_id !== undefined || next.area_id !== undefined)) {
      const covers = (await activeCoverKinds(tx, [id])).get(id);
      const failed = publishedKeepsCovers(id, covers);
      if (failed.length) throw preconditionsFailed(failed);
    }
    await tx.audit({ action: "course.update", entityKind: "course", entityId: id, ...changed(before, after) });
    return { data: { course: after }, entity: `course:${id}` };
  });
}

/** A new slug must be free; a published course keeps its old URLs as redirects (course and visible lessons) in the same transaction. */
async function renameCourse(tx: Tx, id: string, before: CourseView, slug: string): Promise<void> {
  await assertSlugFree(tx, slug, id);
  const rows = await selectLessonSlugRows(tx, id);
  for (const lesson of rows) await assertPathFree(tx, lessonPath(slug, String(lesson.slug)));
  if (before.status !== "published") return;
  const oldPrefix = coursePath(before.slug);
  const newPrefix = coursePath(slug);
  // Redirects into the old pages follow them, so no old URL ends on a dead path or in a chain.
  await retargetRedirectPrefix(tx, oldPrefix, newPrefix, oldPrefix.length + 1);
  await addRedirect(tx, oldPrefix, newPrefix);
  for (const lesson of rows.filter((row) => row.visible === true)) await addRedirect(tx, lessonPath(before.slug, String(lesson.slug)), lessonPath(slug, String(lesson.slug)));
}

/** The database CatalogStatePort, closed over the caller's transaction. The in-memory catalog uses the same `createTransition`. */
export function catalogCourseState(tx: Queryable): CatalogStatePort {
  return {
    async read(expected) {
      await lockRow(tx, "courses", expected.courseId, `Course ${expected.courseId}`, expected.expectedRevision);
      return readCourseState(tx, [expected.courseId]);
    },
    async changeStatus(change) {
      const row = await updateCourseStatusRow(tx, change.courseId, change.target);
      const course = courseView(row ?? {});
      return { revision: course.revision, course };
    },
  };
}

export async function setCourseStatus(context: Ctx<{ id: string }, unknown, CourseStatusBody>): Promise<Outcome> {
  const { id } = context.params;
  const { to, expectedRevision } = context.body;
  const transitions = context.deps.readStatusTransitions === undefined ? undefined : await context.deps.readStatusTransitions();
  return context.mutate(async (tx) => {
    const result = await createTransition({ courseId: id, expectedRevision, target: to }, undefined, {
      state: catalogCourseState(tx), audit: (entry) => tx.audit(entry),
    }, transitions);
    return { data: { course: result.course }, entity: `course:${id}` };
  });
}

/** Visible YouTube videos of a course whose last check is older than the lesson's video-check age. */
async function staleVideos(db: Queryable, courseId: string, now: Date): Promise<{ lessonId: string; youtubeId: string }[]> {
  const threshold = videoCheckCutoff(now);
  const rows = await selectStaleYoutubeVideos(db, courseId, threshold);
  return rows.map((row) => ({ lessonId: String(row.lesson_id), youtubeId: String(row.external_id) }));
}

export async function publishCourse(context: Ctx<{ id: string }, unknown, PublishBody>): Promise<Outcome> {
  const { id } = context.params;
  const { deps } = context;
  const body = context.body;
  const statusRow = await selectCourseStatus(context.db, id);
  if (!statusRow) throw notFound(`Course ${id}`);
  // Preflight outside the transaction: a stale embed check is redone before anything is locked.
  const now = deps.now();
  const checks: { lessonId: string; youtubeId: string; result: OEmbedResult }[] = [];
  for (const video of await staleVideos(context.db, id, now)) checks.push({ ...video, result: await deps.oembed(video.youtubeId) });
  const options: RuleOptions = { allowOrphan: body.allowOrphan === true, videoFailures: checks.filter((check) => check.result.status !== "ok").map((check) => ({ lessonId: check.lessonId, status: check.result.status })) };
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    await lockReleases(tx);
    const locked = await lockRow(tx, "courses", id, `Course ${id}`, body.expectedRevision);
    const from = String(locked.status);
    if (from !== "review" && from !== "published") throw stateConflict(`Only a course in review (or already published) can be published; this one is ${from}.`, { from });
    const facts = factsOf(await readCourseState(tx, [id]), id);
    const failed = facts ? evaluateRules("published", facts, options) : [];
    if (failed.length > 0) throw preconditionsFailed(failed);
    const fresh = checks.filter((check) => check.result.status === "ok");
    for (const check of fresh) {
      await markLessonVideoChecked(tx, check.lessonId, check.youtubeId, now.toISOString(), deps.oembedChecker);
    }
    if (from === "review") await publishOneCourse(tx, id);
    publication = await publishRelease(tx, { note: body.note, actor: context.actor, fresh: new Set([id]), now });
    const noop = from === "published" && !publication.release.created;
    if (!noop || fresh.length > 0) {
      await tx.audit({ action: "course.publish", entityKind: "course", entityId: id, before: { status: from }, after: { status: "published", release: publication.release.number, noop, videosChecked: fresh.length }, releaseNumber: publication.release.number });
    }
    scheduleActivation(tx, deps, publication.release, publication.release.created);
    return { data: { release: publication.release, diff: publication.diff, ...(noop ? { noop: true } : {}) }, noop: noop && fresh.length === EXTENT.empty, entity: `course:${id}` };
  });
  return outcome;
}

/**
 * POST /courses/publish-batch: every listed course (review or already published) goes live in ONE new release, or none
 * does. Same rules as POST /courses/:id/publish, evaluated for all courses before anything changes; every failure across
 * the batch comes back in one 412. Rolling back is one `release activate <previous>` (the response names it).
 */
export async function publishCourseBatch(context: Ctx<unknown, unknown, PublishBatchBody>): Promise<Outcome> {
  const { deps } = context;
  const body = context.body;
  const ids = body.courses.map((course) => course.id);
  const known = await selectKnownCourseIds(context.db, ids);
  const missing = ids.filter((id) => !known.some((row) => row.id === id));
  if (missing.length > 0) throw notFound(`Course ${missing.join(", ")}`);
  const now = deps.now();
  const checks: { courseId: string; lessonId: string; youtubeId: string; result: OEmbedResult }[] = [];
  const stale: { courseId: string; lessonId: string; youtubeId: string }[] = [];
  for (const id of ids) for (const video of await staleVideos(context.db, id, now)) stale.push({ courseId: id, ...video });
  // A whole university can carry thousands of stale videos: check them 16 at a time, before anything is locked.
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(16, stale.length) }, async () => {
    while (cursor < stale.length) {
      const video = stale[cursor] as (typeof stale)[number];
      cursor += 1;
      checks.push({ ...video, result: await deps.oembed(video.youtubeId) });
    }
  }));
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    await lockReleases(tx);
    const from = new Map<string, string>();
    for (const course of [...body.courses].sort((a, b) => a.id.localeCompare(b.id))) {
      const locked = await lockRow(tx, "courses", course.id, `Course ${course.id}`, course.expectedRevision);
      const status = String(locked.status);
      if (status !== "review" && status !== "published") throw stateConflict(`Only courses in review (or already published) can be published; ${course.id} is ${status}.`, { id: course.id, from: status });
      from.set(course.id, status);
    }
    const state = await readCourseState(tx, ids);
    const failed = ids.flatMap((id) => {
      const facts = factsOf(state, id);
      const videoFailures = checks.filter((check) => check.courseId === id && check.result.status !== "ok").map((check) => ({ lessonId: check.lessonId, status: check.result.status }));
      return facts ? evaluateRules("published", facts, { allowOrphan: body.allowOrphan === true, videoFailures }) : [];
    });
    if (failed.length > 0) throw preconditionsFailed(failed);
    const fresh = checks.filter((check) => check.result.status === "ok");
    for (const check of fresh) {
      await markLessonVideoChecked(tx, check.lessonId, check.youtubeId, now.toISOString(), deps.oembedChecker);
    }
    const promoted = ids.filter((id) => from.get(id) === "review");
    if (promoted.length > 0) await publishPromotedCourses(tx, promoted);
    publication = await publishRelease(tx, { note: body.note, actor: context.actor, fresh: new Set(ids), now });
    const noop = promoted.length === EXTENT.empty && !publication.release.created;
    if (!noop || fresh.length > 0) {
      for (const id of ids) {
        await tx.audit({ action: "course.publish", entityKind: "course", entityId: id, before: { status: from.get(id) }, after: { status: "published", release: publication.release.number, batch: ids.length }, releaseNumber: publication.release.number });
      }
      await tx.audit({ action: "course.publish.batch", entityKind: "release", entityId: String(publication.release.number), before: { active: publication.previous }, after: { release: publication.release.number, created: publication.release.created, courses: ids }, releaseNumber: publication.release.number });
    }
    scheduleActivation(tx, deps, publication.release, publication.release.created);
    return {
      data: { release: publication.release, diff: publication.diff, previous: publication.previous, courses: ids.map((id) => ({ id, from: from.get(id) ?? "" })), ...(noop ? { noop: true } : {}) },
      noop: noop && fresh.length === EXTENT.empty, entity: `courses:${String(ids.length)}`,
    };
  });
  return outcome;
}

/**
 * POST /courses/classify (ADR-26): area and/or subarea for many courses in ONE transaction. Every item is checked first
 * and all problems come back in one 412; nothing changes unless all hold. Setting what a course already has is a noop,
 * so re-running a backfill file is safe. Published courses change on the site with the next release (`release create`).
 */
export async function classifyCourses(context: Ctx<unknown, unknown, ClassifyBody>): Promise<Outcome> {
  const { items } = context.body;
  return context.mutate(async (tx) => {
    await lockMediaOwners(tx, items.flatMap((item) => {
      const owners: { owner: "course" | "subarea" | "area"; ownerId: string }[] = [{ owner: "course", ownerId: item.id }];
      if (typeof item.subareaId === "string") owners.push({ owner: "subarea", ownerId: item.subareaId });
      return owners;
    }));
    const rows = await lockCoursesForClassification(tx, items.map((item) => item.id));
    const current = new Map(rows.map((row) => [String(row.id), row]));
    const missing = items.filter((item) => !current.has(item.id)).map((item) => item.id);
    if (missing.length > 0) throw notFound(`Course ${missing.join(", ")}`);
    const failed: PreconditionFailure[] = [];
    const changes: { id: string; next: { area_id?: string; subarea_id?: string | null }; before: { areaId: string | null; subareaId: string | null } }[] = [];
    for (const item of items) {
      const row = current.get(item.id) as Record<string, unknown>;
      const next: { area_id?: string; subarea_id?: string | null } = {};
      if (item.areaId !== undefined && item.areaId !== row.area_id) next.area_id = item.areaId;
      if (item.subareaId !== undefined && item.subareaId !== (row.subarea_id ?? null)) next.subarea_id = item.subareaId;
      if (Object.keys(next).length === EXTENT.empty) continue;
      const problem = await classificationProblem(tx, { id: item.id, area_id: row.area_id, subarea_id: row.subarea_id }, next);
      failed.push(...classificationFailures(item.id, problem));
      if (!problem) changes.push({ id: item.id, next, before: { areaId: (row.area_id ?? null) as string | null, subareaId: (row.subarea_id ?? null) as string | null } });
    }
    if (failed.length > 0) throw preconditionsFailed(failed);
    const changed: { id: string; before: { areaId: string | null; subareaId: string | null }; after: { areaId: string | null; subareaId: string | null } }[] = [];
    for (const change of changes) {
      const columns = Object.keys(change.next) as (keyof typeof change.next)[];
      const updated = await updateCourseAreaColumns(tx, change.id, columns, columns.map((column) => change.next[column]));
      const after = { areaId: (updated?.area_id ?? null) as string | null, subareaId: (updated?.subarea_id ?? null) as string | null };
      await tx.audit({ action: "course.update", entityKind: "course", entityId: change.id, before: change.before, after });
      changed.push({ id: change.id, before: change.before, after });
    }
    const unchanged = items.length - changed.length;
    if (changed.length > 0) await tx.audit({ action: "course.classify", entityKind: "courses", entityId: String(items.length), after: { changed: changed.length, unchanged } });
    return { data: { changed, unchanged, ...(changed.length === EXTENT.empty ? { noop: true } : {}) }, noop: changed.length === EXTENT.empty, entity: `courses:${String(items.length)}` };
  });
}

/**
 * published → draft|archived inside a mutation: the featured course needs a published replacement first, then a new release
 * without the course is compiled and activated. Shared by POST /unpublish and DELETE ?mode=archive.
 */
export async function unpublishInTx(tx: Tx, context: Ctx, id: string, options: { expectedRevision: number; to: "draft" | "archived"; replacementFeaturedId?: string; note: string; action: string }): Promise<Publication> {
  await lockReleases(tx);
  const locked = await lockRow(tx, "courses", id, `Course ${id}`, options.expectedRevision);
  if (locked.status !== "published") throw stateConflict(`Course ${id} is ${String(locked.status)}, not published.`, { status: locked.status });
  if (locked.featured === true) {
    const replacement = options.replacementFeaturedId;
    if (replacement === undefined) throw stateConflict(`Course ${id} is the featured course: pass replacementFeaturedId (a published course).`);
    const replacementRow = await lockReplacementCourseStatus(tx, replacement);
    if (replacement === id || replacementRow?.status !== "published") throw unprocessable(`replacementFeaturedId ${replacement} must be another published course.`);
    await clearCourseFeatured(tx, id);
    await setCourseFeatured(tx, replacement);
  }
  await setCourseStatusClearFeatured(tx, id, options.to);
  const publication = await publishRelease(tx, { note: options.note, actor: context.actor, fresh: new Set(), now: context.deps.now() });
  await tx.audit({ action: options.action, entityKind: "course", entityId: id, before: { status: "published", featured: locked.featured === true }, after: { status: options.to, replacementFeaturedId: options.replacementFeaturedId ?? null, release: publication.release.number }, releaseNumber: publication.release.number });
  return publication;
}

export async function unpublishCourse(context: Ctx<{ id: string }, unknown, UnpublishBody>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    publication = await unpublishInTx(tx, context, id, { expectedRevision: body.expectedRevision, to: body.to ?? "draft", note: body.note, action: "course.unpublish", ...(body.replacementFeaturedId === undefined ? {} : { replacementFeaturedId: body.replacementFeaturedId }) });
    scheduleActivation(tx, context.deps, publication.release, publication.release.created);
    return { data: { release: publication.release, diff: publication.diff }, entity: `course:${id}` };
  });
  return outcome;
}
