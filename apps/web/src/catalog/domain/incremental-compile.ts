import { canonicalJson, sha256Hex } from "../../kernel/canonical.ts";
import { continueWatchingTitle } from "../../site/domain/reader-copy.ts";
import { releaseSha } from "../../kernel/sha.ts";
import { compileRelease, subareasInOrder, type CompileOptions } from "./compile.ts";
import { courseStatus } from "./course-status.ts";
import { authorCoverSchema } from "./author-cover.ts";
import { assertReleaseCovers } from "./cover-rule.ts";
import { projectHomeRow } from "./home-row-kind.ts";
import { COURSE_TEXT_FIELDS, TEXT_FIELDS } from "./fields.ts";
import { RELEASE_SCHEMA_VERSION, releaseSchema, type PublicCatalog } from "./release.ts";
import { catalogTablesSchema, compareIds, type CatalogRow, type CatalogTables } from "./tables.ts";

/** About stays last. The release index already stores the publish fields, then About. */
export const COURSE_FINGERPRINT_TEXTS = [...COURSE_TEXT_FIELDS.filter((field) => field !== "about"), "about"] as const;

/** A course projection is addressed by content hash. Old hashes stay so an older release can still resolve them. */
export type ProjectionRef = Readonly<{ courseId: string; sha256: string }>;

export type PublishOutcome = Readonly<{ releaseNumber: number; noop: boolean }>;

export interface ScopedCourseState {
  readonly courseId: string;
  readonly sourceRevision: number;
  /** Tables already reduced to this course. Execution timestamps are not part of the hash. */
  readonly tables: CatalogTables;
  readonly previous: PublicCatalog | null;
  readonly fresh: boolean;
}

export interface CompiledCourseProjection {
  readonly courseId: string;
  readonly sha256: string;
  readonly sourceRevision: number;
  readonly fingerprint: string;
  readonly summary: Readonly<{ authorId: string; lessonIds: readonly string[] }>;
  readonly detail: Readonly<{
    author: PublicCatalog["authors"][number];
    course: PublicCatalog["courses"][number];
    lessons: readonly PublicCatalog["lessons"][number][];
  }>;
}

export interface ReleaseIndexCourse extends ProjectionRef {
  readonly fingerprint: string;
  readonly sourceRevision: number;
}

export interface CatalogReleaseIndex {
  readonly formatVersion: 3;
  readonly manifestSha256: string;
  readonly globalFingerprint: string;
  readonly courses: readonly ReleaseIndexCourse[];
  readonly authors: readonly { readonly id: string; readonly fingerprint: string }[];
  /** Content stamps. An index written before D-033 has neither, and the next cut compiles every course once. */
  readonly licenses?: readonly { readonly code: string; readonly fingerprint: string }[];
  readonly sources?: readonly { readonly id: string; readonly fingerprint: string }[];
}

export interface ReleaseIndexInput {
  readonly globalFingerprint: string;
  readonly courses: readonly ReleaseIndexCourse[];
  readonly authors: readonly { readonly id: string; readonly fingerprint: string }[];
  readonly licenses?: readonly { readonly code: string; readonly fingerprint: string }[];
  readonly sources?: readonly { readonly id: string; readonly fingerprint: string }[];
}

export interface CatalogTableIndex {
  readonly courses: ReadonlyMap<string, CatalogRow<"courses">>;
  readonly authors: ReadonlyMap<string, CatalogRow<"authors">>;
  readonly lessonsByCourse: ReadonlyMap<string, readonly CatalogRow<"lessons">[]>;
  readonly editionsByCourse: ReadonlyMap<string, readonly CatalogRow<"course_editions">[]>;
  readonly videosByCourse: ReadonlyMap<string, readonly CatalogRow<"lesson_videos">[]>;
  readonly textsByCourse: ReadonlyMap<string, readonly CatalogRow<"catalog_texts">[]>;
}

function pushRow<T>(map: Map<string, T[]>, key: string, value: T): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

/** Group rows once so each course scope is a lookup. Group order matches a filter of the source arrays. */
export function indexCatalogTables(tables: CatalogTables): CatalogTableIndex {
  const lessonCourse = new Map<string, string>();
  const lessonsByCourse = new Map<string, CatalogRow<"lessons">[]>();
  for (const lesson of tables.lessons) {
    pushRow(lessonsByCourse, lesson.course_id, lesson);
    lessonCourse.set(lesson.id, lesson.course_id);
  }
  const editionsByCourse = new Map<string, CatalogRow<"course_editions">[]>();
  for (const edition of tables.course_editions) pushRow(editionsByCourse, edition.course_id, edition);
  const videosByCourse = new Map<string, CatalogRow<"lesson_videos">[]>();
  for (const video of tables.lesson_videos) {
    const courseId = lessonCourse.get(video.lesson_id);
    if (courseId) pushRow(videosByCourse, courseId, video);
  }
  const textsByCourse = new Map<string, CatalogRow<"catalog_texts">[]>();
  for (const text of tables.catalog_texts) {
    const courseId = text.entity_kind === "course" ? text.entity_id : text.entity_kind === "lesson" ? lessonCourse.get(text.entity_id) : undefined;
    if (courseId) pushRow(textsByCourse, courseId, text);
  }
  return {
    courses: new Map(tables.courses.map((course) => [course.id, course])),
    authors: new Map(tables.authors.map((author) => [author.id, author])),
    lessonsByCourse, editionsByCourse, videosByCourse, textsByCourse,
  };
}

/**
 * The same rows as `scopeCourseTables`, without parsing each course again.
 * Shared reference tables are the same arrays; course rows are the indexed objects.
 */
export function scopeCourseFromIndex(tables: CatalogTables, index: CatalogTableIndex, courseId: string): CatalogTables {
  const course = index.courses.get(courseId);
  const author = course ? index.authors.get(course.author_id) : undefined;
  return {
    licenses: tables.licenses,
    content_sources: tables.content_sources,
    authors: author ? [author] : [],
    subject_areas: tables.subject_areas,
    subject_subareas: tables.subject_subareas,
    courses: course ? [course] : [],
    course_editions: [...(index.editionsByCourse.get(courseId) ?? [])],
    lessons: [...(index.lessonsByCourse.get(courseId) ?? [])],
    lesson_videos: [...(index.videosByCourse.get(courseId) ?? [])],
    catalog_texts: [...(index.textsByCourse.get(courseId) ?? [])],
    home_rows: [],
    home_row_items: [],
    slug_redirects: [],
  };
}

/** One published course, its editions, lessons, videos, texts and author. Shared tables that do not change the course body stay out. */
export function scopeCourseTables(tables: CatalogTables, courseId: string): CatalogTables {
  const course = tables.courses.find((row) => row.id === courseId);
  const lessons = tables.lessons.filter((row) => row.course_id === courseId);
  const lessonIds = new Set(lessons.map((row) => row.id));
  return catalogTablesSchema.parse({
    licenses: tables.licenses,
    content_sources: tables.content_sources,
    authors: tables.authors.filter((row) => row.id === course?.author_id),
    subject_areas: tables.subject_areas,
    subject_subareas: tables.subject_subareas,
    courses: course ? [course] : [],
    course_editions: tables.course_editions.filter((row) => row.course_id === courseId),
    lessons,
    lesson_videos: tables.lesson_videos.filter((row) => lessonIds.has(row.lesson_id)),
    catalog_texts: tables.catalog_texts.filter((row) => (row.entity_kind === "course" && row.entity_id === courseId) || (row.entity_kind === "lesson" && lessonIds.has(row.entity_id))),
    home_rows: [],
    home_row_items: [],
    slug_redirects: [],
  });
}

function textRow(tables: CatalogTables, kind: string, id: string, field: string): CatalogRow<"catalog_texts"> | undefined {
  return tables.catalog_texts.find((row) => row.entity_kind === kind && row.entity_id === id && row.field === field && row.locale === "en");
}

/** The text the compiler will actually emit: approved table text, or the live release when this course is not being published. */
function effectiveText(state: ScopedCourseState, kind: string, id: string, field: string): string | null {
  const row = textRow(state.tables, kind, id, field);
  if (row?.status === "approved") return row.text;
  if (state.fresh || !state.previous) return null;
  const entity: Readonly<Record<string, unknown>> | undefined = kind === "course"
    ? state.previous.courses.find((course) => course.id === id)
    : state.previous.lessons.find((lesson) => lesson.id === id);
  const value = entity?.[field];
  return typeof value === "string" ? value : null;
}

function sorted<T>(rows: readonly T[], key: (row: T) => string): T[] {
  return [...rows].sort((a, b) => compareIds(key(a), key(b)));
}

/** Canonical inputs of one course. Key order and row order do not change the hash; execution time is absent. */
export function fingerprintCourse(state: ScopedCourseState): string {
  const course = state.tables.courses[0];
  const lessons = sorted(state.tables.lessons, (row) => row.id);
  const body = {
    author: state.tables.authors[0] ?? null,
    course: course ? {
      id: course.id, slug: course.slug, author_id: course.author_id, title: course.title, language_label: course.language_label,
      lesson_noun: course.lesson_noun, featured: course.featured, source_id: course.source_id, license_code: course.license_code,
      attribution_text: course.attribution_text, canonical_url: course.canonical_url, area_id: course.area_id, subarea_id: course.subarea_id,
      cover_from: course.cover_from,
    } : null,
    license: state.tables.licenses.find((row) => row.code === course?.license_code) ?? null,
    source: state.tables.content_sources.find((row) => row.id === course?.source_id) ?? null,
    editions: sorted(state.tables.course_editions, (row) => row.id),
    lessons: lessons.map((lesson) => ({
      id: lesson.id, slug: lesson.slug, edition_id: lesson.edition_id, part: lesson.part, position: lesson.position, kind: lesson.kind,
      youtube_title: lesson.youtube_title, duration_seconds: lesson.duration_seconds, visible: lesson.visible,
      license_code: lesson.license_code, attribution_text: lesson.attribution_text,
      ...Object.fromEntries(Object.keys(TEXT_FIELDS.lesson).map((field) => [field, effectiveText(state, "lesson", lesson.id, field)])),
      video: state.tables.lesson_videos.find((row) => row.lesson_id === lesson.id && row.provider === "youtube" && row.status === "ok")?.external_id ?? null,
    })),
    texts: COURSE_FINGERPRINT_TEXTS.map((field) => ({ field, text: effectiveText(state, "course", state.courseId, field) })),
  };
  return sha256Hex(canonicalJson(body));
}

export function fingerprintAuthor(author: CatalogRow<"authors">): string {
  return sha256Hex(canonicalJson(author));
}

export function fingerprintLicense(license: CatalogRow<"licenses">): string {
  return sha256Hex(canonicalJson(license));
}

export function fingerprintSource(source: CatalogRow<"content_sources">): string {
  return sha256Hex(canonicalJson(source));
}

/** License and source stamps written on every new release index (D-033). */
export function referenceStamps(tables: CatalogTables): Pick<CatalogReleaseIndex, "licenses" | "sources"> {
  return {
    licenses: tables.licenses.map((license) => ({ code: license.code, fingerprint: fingerprintLicense(license) })),
    sources: tables.content_sources.map((source) => ({ id: source.id, fingerprint: fingerprintSource(source) })),
  };
}

/** Home, redirects and classification lists. Author rows are tracked on their own so one author does not dirty every course. */
export function fingerprintGlobals(tables: CatalogTables): string {
  return sha256Hex(canonicalJson({
    homeRows: sorted(tables.home_rows, (row) => row.id),
    homeItems: sorted(tables.home_row_items, (row) => `${row.row_id}/${row.course_id}`),
    redirects: sorted(tables.slug_redirects, (row) => row.from_path),
    areas: sorted(tables.subject_areas, (row) => row.id),
    subareas: sorted(tables.subject_subareas, (row) => row.id),
  }));
}

/**
 * Compiles one course the same way `compileRelease` does, scoped so the other courses are not walked.
 * The hash covers the author, the course and its lessons. It does not cover `publishedAt` or a release number.
 */
export function compileSingleCourseProjection(state: ScopedCourseState): CompiledCourseProjection {
  const options: CompileOptions = { ...(state.previous ? { previous: state.previous } : {}), fresh: state.fresh ? new Set([state.courseId]) : new Set() };
  const compiled = compileRelease(state.tables, { number: 1, publishedAt: "2020-01-01T00:00:00.000Z" }, options);
  const course = compiled.courses.find((row) => row.id === state.courseId);
  const author = compiled.authors.find((row) => row.id === course?.authorId);
  if (!course || !author) throw new Error(`Course ${state.courseId} did not compile.`);
  const lessons = compiled.lessons.filter((row) => row.courseId === state.courseId);
  const detail = { author, course, lessons };
  return {
    courseId: state.courseId,
    sha256: sha256Hex(canonicalJson(detail)),
    sourceRevision: state.sourceRevision,
    fingerprint: fingerprintCourse(state),
    summary: { authorId: author.id, lessonIds: lessons.map((row) => row.id) },
    detail,
  };
}

/** Stable index of course hashes plus the global fingerprint. No execution timestamp and no random id. */
export function compileReleaseIndex(input: ReleaseIndexInput): CatalogReleaseIndex {
  const courses = [...input.courses].sort((a, b) => compareIds(a.courseId, b.courseId));
  const authors = [...input.authors].sort((a, b) => compareIds(a.id, b.id));
  const licenses = input.licenses === undefined ? undefined : [...input.licenses].sort((a, b) => compareIds(a.code, b.code));
  const sources = input.sources === undefined ? undefined : [...input.sources].sort((a, b) => compareIds(a.id, b.id));
  const body = {
    formatVersion: 3 as const, globalFingerprint: input.globalFingerprint, courses, authors,
    ...(licenses === undefined ? {} : { licenses }),
    ...(sources === undefined ? {} : { sources }),
  };
  return { ...body, manifestSha256: sha256Hex(canonicalJson(body)) };
}

export interface StoredReleaseIndex {
  readonly courses: readonly ReleaseIndexCourse[];
  readonly authors: readonly { readonly id: string; readonly fingerprint: string }[];
  readonly globalFingerprint: string;
  /** Absent on an index written before D-033. Missing stamps reuse nothing. */
  readonly licenses?: readonly { readonly code: string; readonly fingerprint: string }[];
  readonly sources?: readonly { readonly id: string; readonly fingerprint: string }[];
}

export interface CourseReuseHeader {
  readonly id: string;
  readonly revision: number;
  readonly authorId: string;
  readonly licenseCode: string | null;
  readonly sourceId: string | null;
}

/**
 * Courses whose stored projection is still the one the cut should ship (D-033, G-6).
 * A course outside `fresh` is reused when its revision matches and its author, license, source and rows did not change.
 * No index, or an index without license and source stamps, reuses nothing: the cut compiles every published course once.
 */
export function coursesToReuse(input: {
  readonly published: readonly CourseReuseHeader[];
  readonly stored: StoredReleaseIndex | null;
  readonly fresh: ReadonlySet<string>;
  readonly changed: ReadonlySet<string>;
  readonly dirtyAuthorIds: ReadonlySet<string>;
  readonly dirtyLicenseCodes: ReadonlySet<string>;
  readonly dirtySourceIds: ReadonlySet<string>;
}): ReadonlySet<string> {
  if (!input.stored || input.stored.licenses === undefined || input.stored.sources === undefined) return new Set();
  const storedCourses = new Map(input.stored.courses.map((course) => [course.courseId, course]));
  const reuse = new Set<string>();
  for (const course of input.published) {
    const stored = storedCourses.get(course.id);
    if (!stored || stored.sourceRevision !== course.revision) continue;
    if (input.fresh.has(course.id) || input.changed.has(course.id) || input.dirtyAuthorIds.has(course.authorId)) continue;
    if (course.licenseCode === null || input.dirtyLicenseCodes.has(course.licenseCode)) continue;
    if (course.sourceId === null || input.dirtySourceIds.has(course.sourceId)) continue;
    reuse.add(course.id);
  }
  return reuse;
}

export interface IncrementalPlan {
  readonly noop: boolean;
  readonly dirty: readonly string[];
  readonly removed: readonly string[];
  readonly globalChanged: boolean;
  readonly reasons: readonly { readonly courseId: string; readonly reason: "added" | "author" | "content" | "removed" }[];
}

/**
 * Decides which courses need a new projection. A missing index compiles every published course once (bootstrap).
 * An author change dirties only courses that name that author. Home, redirects and classification lists dirty the
 * global frame and do not recompile unrelated courses.
 */
export function planIncrementalPublish(input: {
  readonly published: readonly { readonly courseId: string; readonly fingerprint: string; readonly authorId: string }[];
  readonly authorFingerprints: readonly { readonly id: string; readonly fingerprint: string }[];
  readonly homeAuthorIds: readonly string[];
  readonly globalFingerprint: string;
  readonly stored: StoredReleaseIndex | null;
}): IncrementalPlan {
  if (!input.stored) {
    return {
      noop: false,
      dirty: input.published.map((course) => course.courseId).sort(compareIds),
      removed: [],
      globalChanged: true,
      reasons: input.published.map((course) => ({ courseId: course.courseId, reason: "added" as const })),
    };
  }
  const storedCourses = new Map(input.stored.courses.map((course) => [course.courseId, course]));
  const storedAuthors = new Map(input.stored.authors.map((author) => [author.id, author.fingerprint]));
  const publishedIds = new Set(input.published.map((course) => course.courseId));
  const removed = input.stored.courses.map((course) => course.courseId).filter((id) => !publishedIds.has(id)).sort(compareIds);
  const dirtyAuthors = new Set(input.authorFingerprints.filter((author) => storedAuthors.get(author.id) !== author.fingerprint).map((author) => author.id));
  const reasons: { courseId: string; reason: "added" | "author" | "content" }[] = [];
  for (const course of [...input.published].sort((a, b) => compareIds(a.courseId, b.courseId))) {
    const stored = storedCourses.get(course.courseId);
    if (!stored) reasons.push({ courseId: course.courseId, reason: "added" });
    else if (dirtyAuthors.has(course.authorId)) reasons.push({ courseId: course.courseId, reason: "author" });
    else if (stored.fingerprint !== course.fingerprint) reasons.push({ courseId: course.courseId, reason: "content" });
  }
  const homeAuthorChanged = input.homeAuthorIds.some((id) => dirtyAuthors.has(id));
  const globalChanged = input.globalFingerprint !== input.stored.globalFingerprint || homeAuthorChanged;
  return {
    noop: reasons.length === 0 && removed.length === 0 && !globalChanged,
    dirty: reasons.map((reason) => reason.courseId),
    removed,
    globalChanged,
    reasons: [...reasons, ...removed.map((courseId) => ({ courseId, reason: "removed" as const }))],
  };
}

export interface PreparedReleaseCut {
  readonly plan: IncrementalPlan;
  /** Stored projections the cut reuses. Dirty courses are absent: they are compiled. */
  readonly refs: readonly ProjectionRef[];
  readonly scopedById: ReadonlyMap<string, ScopedCourseState>;
  readonly authorIds: ReadonlySet<string>;
  readonly published: readonly { readonly id: string; readonly authorId: string }[];
}

/**
 * Fingerprints the published courses the caller did not already prove unchanged.
 * A course in `reuse` keeps the stored fingerprint and is a ref, not a compile (D-033).
 */
export function prepareReleaseCut(input: {
  readonly tables: CatalogTables;
  readonly revisions: ReadonlyMap<string, number>;
  readonly stored: StoredReleaseIndex | null;
  readonly active: { readonly payload: PublicCatalog } | null;
  readonly fresh: ReadonlySet<string>;
  /** Stored projections the caller already proved unchanged. Their lesson rows may be absent. */
  readonly reuse?: ReadonlySet<string>;
}): PreparedReleaseCut {
  const tableIndex = indexCatalogTables(input.tables);
  const published = input.tables.courses.filter((course) => course.status === courseStatus.published);
  const previous = input.active?.payload ?? null;
  const reuse = input.reuse ?? new Set<string>();
  const storedCourses = new Map((input.stored?.courses ?? []).map((course) => [course.courseId, course]));
  const scopedById = new Map<string, ScopedCourseState>();
  const fingerprinted = published.flatMap((course) => {
    const kept = reuse.has(course.id) ? storedCourses.get(course.id) : undefined;
    if (kept) return [{ courseId: course.id, authorId: course.author_id, fingerprint: kept.fingerprint }];
    const state: ScopedCourseState = {
      courseId: course.id,
      sourceRevision: input.revisions.get(course.id) ?? 0,
      tables: scopeCourseFromIndex(input.tables, tableIndex, course.id),
      previous,
      fresh: input.fresh.has(course.id),
    };
    scopedById.set(course.id, state);
    return [{ courseId: course.id, authorId: course.author_id, fingerprint: fingerprintCourse(state) }];
  });
  const authorIds = new Set([
    ...published.map((course) => course.author_id),
    ...input.tables.home_rows.flatMap((row) => row.author_id ? [row.author_id] : []),
  ]);
  const plan = planIncrementalPublish({
    published: fingerprinted,
    authorFingerprints: input.tables.authors.filter((author) => authorIds.has(author.id)).map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) })),
    homeAuthorIds: input.tables.home_rows.flatMap((row) => row.author_id ? [row.author_id] : []),
    globalFingerprint: fingerprintGlobals(input.tables),
    stored: input.stored,
  });
  const dirty = new Set(plan.dirty);
  const refs = published.flatMap((course) => {
    if (dirty.has(course.id)) return [];
    const ref = storedCourses.get(course.id);
    return ref ? [{ courseId: course.id, sha256: ref.sha256 }] : [];
  });
  return {
    plan, refs, scopedById, authorIds,
    published: published.map((course) => ({ id: course.id, authorId: course.author_id })),
  };
}

export interface ReleaseCut {
  readonly payload: PublicCatalog;
  readonly sha: string;
  readonly unchanged: boolean;
  readonly compiledCourseIds: readonly string[];
  readonly written: readonly CompiledCourseProjection[];
  readonly index: CatalogReleaseIndex;
  readonly frame: ReleaseFrame;
  /** Wall time of this cut. A one-course cut stays small because untouched projections are not compiled. */
  readonly releaseMs: number;
}

function frameOf(payload: PublicCatalog): ReleaseFrame {
  return {
    authors: payload.authors, home: payload.home, redirects: payload.redirects,
    ...(payload.areas ? { areas: payload.areas } : {}),
    ...(payload.subareas ? { subareas: payload.subareas } : {}),
  };
}

/**
 * Builds the next release by compiling `prepared.plan.dirty` only.
 * `releaseMs` is the time of this cut (the factory bench reports it).
 * Bytes match `compileRelease` for the same tables, number and instant.
 */
export function cutRelease(input: {
  readonly tables: CatalogTables;
  readonly prepared: PreparedReleaseCut;
  readonly stored: StoredReleaseIndex | null;
  readonly storedProjections: ReadonlyMap<string, CompiledCourseProjection>;
  readonly active: { readonly number: number; readonly sha: string; readonly payload: PublicCatalog } | null;
  readonly now: Date;
  readonly nextNumber: number;
  readonly onCourseCompiled?: (courseId: string) => void;
}): ReleaseCut {
  const started = Date.now();
  const { plan, scopedById, authorIds, published } = input.prepared;
  const stamps = referenceStamps(input.tables);
  if (plan.noop && input.active && input.stored) {
    const index = compileReleaseIndex({
      globalFingerprint: input.stored.globalFingerprint,
      courses: input.stored.courses,
      authors: input.stored.authors,
      ...stamps,
    });
    return {
      payload: input.active.payload, sha: input.active.sha, unchanged: true, compiledCourseIds: [], written: [],
      index, frame: frameOf(input.active.payload), releaseMs: Date.now() - started,
    };
  }
  const compiled = new Map<string, CompiledCourseProjection>();
  const written: CompiledCourseProjection[] = [];
  for (const courseId of plan.dirty) {
    const state = scopedById.get(courseId);
    if (!state) continue;
    const projection = compileSingleCourseProjection(state);
    input.onCourseCompiled?.(courseId);
    compiled.set(courseId, projection);
    written.push(projection);
  }
  const projections: CompiledCourseProjection[] = [];
  for (const course of published) {
    const created = compiled.get(course.id);
    if (created) { projections.push(created); continue; }
    const row = input.storedProjections.get(course.id);
    if (!row) throw new Error(`Missing projection for ${course.id}.`);
    projections.push(row);
  }
  const authors = input.tables.authors.filter((author) => authorIds.has(author.id)).map((author) => ({ id: author.id, fingerprint: fingerprintAuthor(author) }));
  const indexOf = (list: readonly CompiledCourseProjection[]) => compileReleaseIndex({
    globalFingerprint: fingerprintGlobals(input.tables),
    courses: list.map((projection) => ({ courseId: projection.courseId, sha256: projection.sha256, fingerprint: projection.fingerprint, sourceRevision: projection.sourceRevision })),
    authors,
    ...stamps,
  });
  const draftNumber = input.active?.number ?? input.nextNumber;
  const draftAt = input.active?.payload.publishedAt ?? input.now.toISOString();
  const draft = assembleReleaseFromProjections({ number: draftNumber, publishedAt: draftAt, tables: input.tables, projections });
  if (input.active !== null && releaseSha(draft) === input.active.sha) {
    return {
      payload: draft, sha: input.active.sha, unchanged: true, compiledCourseIds: written.map((projection) => projection.courseId),
      written, index: indexOf(projections), frame: frameOf(draft), releaseMs: Date.now() - started,
    };
  }
  const payload = input.active === null
    ? draft
    : { ...draft, number: input.nextNumber, publishedAt: input.now.toISOString() };
  return {
    payload, sha: releaseSha(payload), unchanged: false, compiledCourseIds: written.map((projection) => projection.courseId),
    written, index: indexOf(projections), frame: frameOf(payload), releaseMs: Date.now() - started,
  };
}

function liveRedirects(redirects: CatalogTables["slug_redirects"], courses: readonly PublicCatalog["courses"][number][], lessons: readonly PublicCatalog["lessons"][number][]): PublicCatalog["redirects"] {
  const live = new Set(courses.map((course) => `/c/${course.slug}`));
  const slugs = new Map(courses.map((course) => [course.id, course.slug]));
  for (const lesson of lessons) live.add(`/c/${slugs.get(lesson.courseId) ?? ""}/${lesson.slug}`);
  return redirects.filter((redirect) => live.has(redirect.to_path) && !live.has(redirect.from_path))
    .map((redirect) => ({ from: redirect.from_path, to: redirect.to_path }))
    .sort((a, b) => a.from.localeCompare(b.from));
}

/**
 * Builds the v2 payload from course projections already compiled and the shared sections.
 * Course compilation is not repeated here.
 */
export function assembleReleaseFromProjections(input: {
  readonly number: number;
  readonly publishedAt: string;
  readonly tables: CatalogTables;
  readonly projections: readonly CompiledCourseProjection[];
}): PublicCatalog {
  const projections = [...input.projections].sort((a, b) => compareIds(a.courseId, b.courseId));
  const courses = projections.map((projection) => projection.detail.course);
  const lessons = projections.flatMap((projection) => projection.detail.lessons);
  const authors = new Map(projections.map((projection) => [projection.detail.author.id, projection.detail.author]));
  const published = new Set(courses.map((course) => course.id));
  for (const row of input.tables.home_rows) {
    if (!row.author_id || authors.has(row.author_id)) continue;
    const author = input.tables.authors.find((entry) => entry.id === row.author_id);
    if (!author) throw new Error(`Unknown author ${row.author_id}.`);
    authors.set(author.id, {
      id: author.id, slug: author.slug, name: author.name, monogram: author.monogram, role: author.role,
      kind: author.kind as PublicCatalog["authors"][number]["kind"],
      ...(author.cover ? { cover: authorCoverSchema.parse(author.cover) } : {}),
    });
  }
  const rows = input.tables.home_rows.filter((row) => row.visible).sort((a, b) => a.position - b.position);
  const home: PublicCatalog["home"] = {
    featuredCourseId: courses.find((course) => course.featured)?.id ?? null,
    rows: rows.map((row) => projectHomeRow({
      id: row.id,
      kind: row.kind as PublicCatalog["home"]["rows"][number]["kind"],
      title: row.title ?? (row.author_id ? (authors.get(row.author_id)?.name ?? continueWatchingTitle) : continueWatchingTitle),
      authorId: row.author_id,
      institutionId: row.institution_id,
      courseIds: input.tables.home_row_items.filter((item) => item.row_id === row.id && published.has(item.course_id))
        .sort((a, b) => a.position - b.position).map((item) => item.course_id),
      cover: row.cover,
      fullName: row.full_name,
      place: row.place,
    })),
  };
  const areas = courses.some((course) => course.areaId !== undefined)
    ? [...input.tables.subject_areas].sort((a, b) => a.position - b.position).map((area) => ({ id: area.id, title: area.title }))
    : undefined;
  const subareas = courses.some((course) => course.subareaId !== undefined) ? subareasInOrder(input.tables) : undefined;
  const catalog = stitchRelease({
    number: input.number,
    publishedAt: input.publishedAt,
    projections,
    frame: {
      authors: [...authors.values()].sort((a, b) => compareIds(a.id, b.id)),
      home,
      redirects: liveRedirects(input.tables.slug_redirects, courses, lessons),
      ...(areas ? { areas } : {}),
      ...(subareas ? { subareas } : {}),
    },
  });
  assertReleaseCovers(catalog, "all");
  return catalog;
}

export interface ReleaseFrame {
  readonly authors: PublicCatalog["authors"];
  readonly home: PublicCatalog["home"];
  readonly redirects: PublicCatalog["redirects"];
  readonly areas?: PublicCatalog["areas"];
  readonly subareas?: PublicCatalog["subareas"];
}

/** Joins stored course projections to the frame captured for the same release. */
export function stitchRelease(input: {
  readonly number: number;
  readonly publishedAt: string;
  readonly projections: readonly CompiledCourseProjection[];
  readonly frame: ReleaseFrame;
}): PublicCatalog {
  const projections = [...input.projections].sort((a, b) => compareIds(a.courseId, b.courseId));
  return releaseSchema.parse({
    schemaVersion: RELEASE_SCHEMA_VERSION,
    number: input.number,
    publishedAt: input.publishedAt,
    authors: input.frame.authors,
    courses: projections.map((projection) => projection.detail.course),
    lessons: projections.flatMap((projection) => projection.detail.lessons),
    home: input.frame.home,
    redirects: input.frame.redirects,
    ...(input.frame.areas ? { areas: input.frame.areas } : {}),
    ...(input.frame.subareas ? { subareas: input.frame.subareas } : {}),
  });
}

// ---- Diffs (pure; snapshots in, no database) ----

export interface EntityDiff { readonly added: string[]; readonly removed: string[]; readonly changed: { id: string; fields: string[] }[] }
export interface ReleaseDiff {
  readonly authors: EntityDiff;
  readonly courses: EntityDiff;
  readonly lessons: EntityDiff;
  readonly texts: { readonly changed: string[] };
  readonly home: { readonly changed: boolean };
  readonly redirects: { readonly added: string[]; readonly removed: string[] };
  readonly empty: boolean;
}

const COURSE_TEXT = new Set(Object.keys(TEXT_FIELDS.course));
const LESSON_TEXT = new Set(Object.keys(TEXT_FIELDS.lesson));

function entityDiff<T extends { id: string }>(before: readonly T[], after: readonly T[]): EntityDiff {
  const old = new Map(before.map((entry) => [entry.id, entry]));
  const now = new Map(after.map((entry) => [entry.id, entry]));
  const changed = [...now.values()].flatMap((entry) => {
    const previous = old.get(entry.id);
    if (!previous) return [];
    const fields = [...new Set([...Object.keys(previous), ...Object.keys(entry)])]
      .filter((field) => canonicalJson((previous as Record<string, unknown>)[field]) !== canonicalJson((entry as Record<string, unknown>)[field]));
    return fields.length > 0 ? [{ id: entry.id, fields }] : [];
  });
  return { added: [...now.keys()].filter((id) => !old.has(id)), removed: [...old.keys()].filter((id) => !now.has(id)), changed };
}

/** What a release changes against another: ids and field names only. */
export function diffReleases(before: PublicCatalog | null, after: PublicCatalog): ReleaseDiff {
  const empty: PublicCatalog = { ...after, authors: [], courses: [], lessons: [], home: { featuredCourseId: null, rows: [] }, redirects: [] };
  const base = before ?? empty;
  const authors = entityDiff(base.authors, after.authors);
  const courses = entityDiff(base.courses, after.courses);
  const lessons = entityDiff(base.lessons, after.lessons);
  const texts = [
    ...courses.changed.flatMap((entry) => entry.fields.filter((field) => COURSE_TEXT.has(field)).map((field) => `course:${entry.id}.${field}`)),
    ...lessons.changed.flatMap((entry) => entry.fields.filter((field) => LESSON_TEXT.has(field)).map((field) => `lesson:${entry.id}.${field}`)),
  ];
  const redirect = (list: PublicCatalog["redirects"]) => new Set(list.map((entry) => `${entry.from} -> ${entry.to}`));
  const oldRedirects = redirect(base.redirects);
  const newRedirects = redirect(after.redirects);
  const home = canonicalJson(base.home) !== canonicalJson(after.home);
  const added = [...newRedirects].filter((entry) => !oldRedirects.has(entry));
  const removed = [...oldRedirects].filter((entry) => !newRedirects.has(entry));
  const isEmpty = [authors, courses, lessons].every((entry) => entry.added.length + entry.removed.length + entry.changed.length === 0) && !home && added.length + removed.length === 0;
  return { authors, courses, lessons, texts: { changed: texts }, home: { changed: home }, redirects: { added, removed }, empty: isEmpty };
}

/** Identity of a release ignoring its number and publication timestamp. */
export function releaseContentSha(payload: PublicCatalog): string {
  return sha256Hex(canonicalJson({
    authors: payload.authors, courses: payload.courses, lessons: payload.lessons, home: payload.home, redirects: payload.redirects,
    areas: payload.areas ?? null, subareas: payload.subareas ?? null,
  }));
}

export const releaseCounts = (payload: PublicCatalog) => ({
  authors: payload.authors.length, courses: payload.courses.length, lessons: payload.lessons.length, rows: payload.home.rows.length, redirects: payload.redirects.length,
});
