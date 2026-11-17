import type { Queryable } from "../../platform/db/uow.ts";
import type { CatalogTables } from "../domain/tables.ts";
import { taxonomyDrift } from "../domain/areas.ts";
import { LEGACY_LESSON_IDS, reslugCourse, slugCoursesFromTables, slugQualityIssues } from "../domain/slug-course.ts";
import type { Outcome } from "./mutation.ts";
import type { HandlerContext } from "./http.ts";
import { catalogCourseFacts, evaluateRules, REQUIRED_COVERS } from "../domain/rules/status.ts";
import { catalogOwners } from "./media-owners.ts";
import { coverGraph, diagnoseMedia, redundantLessons } from "./media-gateway.ts";
import { progressMaintenance } from "../../progress/server/maintenance.ts";
import { livePaths, readTablesAndRevisions } from "./common.ts";
import { activeCoverKinds } from "./cover-kinds.ts";
import { compileNext, diffReleases, readActive } from "./releases.ts";
import { collectOperationalSlis } from "../../platform/observability/slis.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { limitConcurrency } from "../../platform/db/limit.ts";
import { countCourseProjections, countProjectionDrift, countRetainedReleases, selectAllCourseIds, selectAllLessonIds, selectAmbiguousEditions, selectAuthorCoverShapes, selectBehindSequences, selectCoursesMissingSubarea, selectCrossCourseLessons, selectEditionPositionGaps, selectEditionPrefixedTitles, selectHomeCoverShapes, selectHomeRowsMissingCover, selectLessonPositionGaps, selectOrphanEditions, selectOrphanTextRefs, selectRows, selectSubareaAreaMismatches, selectVideosNotOk } from "./table-io.ts";

export interface Finding { readonly code: string; readonly severity: "error" | "warning" | "info"; readonly count: number; readonly sample: unknown[]; readonly message: string }

const SAMPLE = 10;

async function compileDoctorRelease(db: Queryable, active: Awaited<ReturnType<typeof readActive>>, tables: CatalogTables, now: Date) {
  if (!active) return { kind: "none" as const };
  try {
    const next = await compileNext(db, active, new Set(), now, tables);
    return { kind: "ok" as const, next };
  } catch (error) {
    const errors = (error as { details?: { errors?: string[] } }).details?.errors ?? ["unknown"];
    return { kind: "failed" as const, errors };
  }
}
const DOCTOR_READS = 4;
const LEGACY_MEDIA_SQL = `SELECT ref FROM (
    SELECT c.relname AS ref FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname IN ('course_assets', 'lesson_assets', 'subarea_assets')
    UNION ALL
    SELECT table_name || '.' || column_name AS ref FROM information_schema.columns
    WHERE table_schema = 'public' AND (table_name, column_name) IN (('authors', 'media_sha256'), ('home_rows', 'media_sha256'), ('home_rows', 'og_media_sha256'))
  ) retired ORDER BY 1`;
function sampleRows(rows: readonly Record<string, unknown>[]): { count: number; sample: unknown[] } {
  return { count: rows.length, sample: rows.slice(EXTENT.first, SAMPLE).map((row) => (Object.keys(row).length === 1 ? Object.values(row)[EXTENT.first] : row)) };
}

/**
 * Read-only consistency report (plan §3.2). Without the asset FKs (ADR-18 lists the prerequisite), orphan assets and
 * progress are found here. `ok` is false when any finding is an error.
 */
export async function runDoctor(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const db = context.db;
  const findings: Finding[] = [];
  const add = (code: string, severity: Finding["severity"], message: string, result: { count: number; sample: unknown[] }) => {
    if (result.count > EXTENT.empty) findings.push({ code, severity, message, ...result });
  };
  // Independent reads share four connections. Finding order below is unchanged. Covers wait until those reads finish:
  // they open three media queries of their own. D-029: the legacy names stay in this report.
  const occupy = limitConcurrency(DOCTOR_READS);
  const [
    legacyRows, orphanTexts, courseIdRows, lessonIdRows, authorCoverRows, homeCoverRows, videosNotOk, orphanEditions,
    crossCourseLessons, editionGaps, lessonGaps, ambiguousEditions, prefixedTitles, behindSequences, subareaMismatches,
    missingSubarea, homeMissing, body, ownerGraph, active, projectionCount, projectionDriftCount, retainedReleases,
  ] = await Promise.all([
    occupy(() => selectRows(db, LEGACY_MEDIA_SQL)),
    occupy(() => selectOrphanTextRefs(db)),
    occupy(() => selectAllCourseIds(db)),
    occupy(() => selectAllLessonIds(db)),
    occupy(() => selectAuthorCoverShapes(db)),
    occupy(() => selectHomeCoverShapes(db)),
    occupy(() => selectVideosNotOk(db)),
    occupy(() => selectOrphanEditions(db)),
    occupy(() => selectCrossCourseLessons(db)),
    occupy(() => selectEditionPositionGaps(db)),
    occupy(() => selectLessonPositionGaps(db)),
    occupy(() => selectAmbiguousEditions(db)),
    occupy(() => selectEditionPrefixedTitles(db)),
    occupy(() => selectBehindSequences(db)),
    occupy(() => selectSubareaAreaMismatches(db)),
    occupy(() => selectCoursesMissingSubarea(db)),
    occupy(() => selectHomeRowsMissingCover(db)),
    readTablesAndRevisions(db, occupy),
    occupy(() => catalogOwners(db).graph()),
    occupy(() => readActive(db)),
    occupy(() => countCourseProjections(db)),
    occupy(() => countProjectionDrift(db)),
    occupy(() => countRetainedReleases(db)),
  ]);
  const state = { ...body, covers: await activeCoverKinds(db) };
  const courseIds = courseIdRows.map((row) => String(row.id));
  const lessonIds = lessonIdRows.map((row) => String(row.id));
  const mapCover = (table: "authors" | "home_rows", rows: Record<string, unknown>[]) => rows.map((row) => ({ id: String(row.id), table, sha256: typeof row.sha256 === "string" ? row.sha256 : null, width: row.width === null || row.width === undefined ? null : Number(row.width), height: row.height === null || row.height === undefined ? null : Number(row.height), url: typeof row.url === "string" ? row.url : null }));
  const covers = [...mapCover("authors", authorCoverRows), ...mapCover("home_rows", homeCoverRows)];
  const mediaFindings = await diagnoseMedia(db, { courseIds, lessonIds, covers });
  const progress = await progressMaintenance(db).orphanedLessons(lessonIds);
  const redundant = redundantLessons(await coverGraph(db, ownerGraph));
  const compiled = await compileDoctorRelease(db, active, state.tables, context.deps.now());
  add("media.legacy.reader", "error", "A retired media table or cover column is still in the database.", sampleRows(legacyRows));
  add("texts.orphan", "error", "Texts whose entity no longer exists.", sampleRows(orphanTexts));
  for (const finding of mediaFindings) {
    const message = finding.code === "assets.orphan" ? "Cover rows whose course or lesson no longer exists (their R2 bytes may be orphaned too)."
      : finding.code === "r2.pending" ? "R2 objects a committed DELETE could not remove yet; re-run that DELETE."
      : finding.code.startsWith("media.registry.authors") || finding.code.startsWith("media.registry.home_rows") ? "Author/university cover without its registered object."
      : "Content-addressed references without their immutable registry object.";
    add(finding.code, finding.code === "assets.orphan" || finding.code === "r2.pending" ? "warning" : "error", message, finding);
  }
  add("progress.orphan", "info", "Progress rows of deleted lessons (kept on purpose; never deleted by the catalog).", { count: progress.count, sample: [...progress.sample] });
  add("videos.not_ok", "error", "Visible lessons of published courses whose YouTube video is not ok.", sampleRows(videosNotOk));
  // Editions (ADR-21). The composite foreign key already keeps a lesson's edition in its course; the doctor proves it.
  add("editions.orphan", "warning", "Editions without any lesson (publish refuses them; delete or fill them).", sampleRows(orphanEditions));
  add("lessons.edition_course", "error", "Lessons whose edition belongs to another course.", sampleRows(crossCourseLessons));
  add("editions.gaps", "error", "Courses whose edition positions are not 1..N.", sampleRows(editionGaps));
  add("lessons.gaps", "error", "Editions whose lesson positions are not 1..N.", sampleRows(lessonGaps));
  add("editions.ambiguous", "warning", "Courses with more than one edition of the same year and variant.", sampleRows(ambiguousEditions));
  // Titles that carry the edition (a stopgap from before editions existed). Approved copy is not edited here: editorial review decides.
  add("lesson.title.edition_prefix", "info", "Lesson titles that name their semester; the edition shows it now (editorial review).", sampleRows(prefixedTitles));
  // The next value is read from the sequence itself (including freshly reset sequences): after setval(…, false),
  // pg_sequences.last_value is NULL although the next id is right, which read as "behind" on every migrated target.
  add("sequences.behind", "error", "An id sequence would hand out an existing id.", sampleRows(behindSequences));

  // Areas and subareas (ADR-25/26): the composite key keeps a subarea inside its course's area; the doctor proves it.
  // (Courses without an area are a product state, the "More courses" rail; not flagged.) Drift is checked with the release below.
  add("courses.subarea_area", "error", "Courses whose subarea belongs to another area (or that have a subarea but no area).", sampleRows(subareaMismatches));
  add("courses.subarea_missing", "info", "Published courses in an area that has subareas but without one (they go to the area's own rail when it is split).", sampleRows(missingSubarea));

  add("media.lesson.redundant", "warning", "Lesson cover versions equal to the active inherited cover; prune-inherited removes references and keeps R2 bytes.", {
    count: redundant.length, sample: redundant.slice(EXTENT.first, SAMPLE).map(({ asset, courseId }) => ({ id: asset.id, lessonId: asset.ownerId, courseId, sha256: asset.sha256 })),
  });
  const unresolved = state.tables.courses.filter((course) => course.status === "published").flatMap((course) =>
    REQUIRED_COVERS.filter((kind) => !state.covers.get(course.id)?.has(kind)).map((kind) => `${course.id}/${kind}`));
  add("media.cover.unresolved", "error", "Published course cover kinds unresolved by the shared cover rule.", { count: unresolved.length, sample: unresolved.slice(EXTENT.first, SAMPLE) });
  const live = livePaths(state.tables);
  const coursesById = new Map(state.tables.courses.map((course) => [course.id, course]));
  const existing = new Set([...state.tables.courses.map((course) => `/c/${course.slug}`), ...state.tables.lessons.flatMap((lesson) => {
    const course = coursesById.get(lesson.course_id);
    return course ? [`/c/${course.slug}/${lesson.slug}`] : [];
  })]);
  const redirects = state.tables.slug_redirects;
  add("redirects.broken", "warning", "Redirects to a page that no longer exists, or from a page that exists again.", {
    count: redirects.filter((redirect) => !existing.has(redirect.to_path) || existing.has(redirect.from_path)).length,
    sample: redirects.filter((redirect) => !existing.has(redirect.to_path) || existing.has(redirect.from_path)).slice(EXTENT.first, SAMPLE).map((redirect) => `${redirect.from_path} -> ${redirect.to_path}`),
  });
  const dormant = redirects.filter((redirect) => existing.has(redirect.to_path) && !live.has(redirect.to_path));
  add("redirects.dormant", "info", "Redirects to pages that are not published now; they resolve again when the target is.", { count: dormant.length, sample: dormant.slice(EXTENT.first, SAMPLE).map((redirect) => `${redirect.from_path} -> ${redirect.to_path}`) });
  const slugCourses = slugCoursesFromTables(state.tables);
  const unclean = state.tables.courses.flatMap((course) => {
    const slugCourse = slugCourses.get(course.id);
    return slugCourse ? reslugCourse(slugCourse).filter((entry) => !LEGACY_LESSON_IDS.has(entry.lessonId))
      .map((entry) => ({ entry, issues: slugQualityIssues(entry.before, entry.after, course.slug) })).filter(({ issues }) => issues.length > EXTENT.empty)
      .map(({ entry, issues }) => `${course.slug}/${entry.before} (${entry.lessonId}): ${issues.join(", ")}`) : [];
  });
  add("lesson.slug.quality", "warning", "Imported lesson slugs the slug rule would not give (long, edition tag, course name); `tower-catalog lesson reslug` fixes them. The 126 legacy lessons are never checked.",
    { count: unclean.length, sample: unclean.slice(EXTENT.first, SAMPLE) });
  const factsByCourse = catalogCourseFacts(state.tables, state.covers);
  const blocked = state.tables.courses.filter((course) => course.status === "published").flatMap((course) => {
    const facts = factsByCourse.get(course.id);
    const failed = facts ? evaluateRules("published", facts, { allowOrphan: true }) : [];
    return failed.length > EXTENT.empty ? [{ course: course.id, failed: failed.map((failure) => `${failure.rule} ${failure.entity}`) }] : [];
  });
  add("course.preconditions", "warning", "Published courses that would not pass publish now (e.g. edited texts awaiting approval).", { count: blocked.length, sample: blocked.slice(EXTENT.first, SAMPLE) });

  add("home.cover.missing", "warning", "A visible Universities or Authors row has no cover of its own. The next release is refused while one of these rows publishes a course. A legacy release renders a neutral placeholder, never a course poster.", sampleRows(homeMissing));

  // The tables own the areas and their order; the release carries them. An `area create` or a subarea change waits for
  // the next release (area move and area update cut one themselves).
  const drift = active ? taxonomyDrift(active.payload, state.tables) : [];
  add("taxonomy.drift", "info", "Areas or subareas whose order or title in the database differs from the active release (they go live with the next release).", { count: drift.length, sample: drift.slice(EXTENT.first, SAMPLE) });
  if (compiled.kind === "none") {
    findings.push({ code: "release.none", severity: "error", message: "No active release.", count: 1, sample: [] });
  } else if (compiled.kind === "failed") {
    findings.push({ code: "release.compile_failed", severity: "error", message: "The tables do not compile into a valid release.", count: compiled.errors.length, sample: compiled.errors.slice(EXTENT.first, SAMPLE) });
  } else if (active && !compiled.next.unchanged) {
    const diff = diffReleases(active.payload, compiled.next.payload);
    findings.push({ code: "release.drift", severity: "info", message: "The tables hold changes the active release does not (they go live with the next release).", count: 1, sample: [diff] });
  }
  if (projectionDriftCount > EXTENT.empty) findings.push({ code: "projection.drift", severity: "error", message: "The active release index names a projection that is not stored.", count: projectionDriftCount, sample: [] });
  if (retainedReleases > EXTENT.empty) findings.push({ code: "release.retained", severity: "info", message: "Inactive releases remain restorable. Deploy age alone does not authorize dropping the v2 reader.", count: retainedReleases, sample: [] });
  const { poolPressure } = await import("../../platform/db/pool.ts");
  const operational = await collectOperationalSlis({
    activeReleaseNumber: () => Promise.resolve(active?.number ?? 0),
    projectionCount: () => Promise.resolve(projectionCount),
    projectionDriftCount: () => Promise.resolve(projectionDriftCount),
    pool: poolPressure,
  });
  return { data: { ok: findings.every((finding) => finding.severity !== "error"), activeRelease: active ? { number: active.number, sha: active.sha } : null, findings, operational } };
}
