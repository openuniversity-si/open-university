import type { PreconditionFailure } from "../../../kernel/errors.ts";
import type { CourseBundleV1 } from "../bundle.ts";
import { indistinctEditionMessage, offeringKey } from "../edition-variant.ts";
import type { EditionVariant } from "../schema/fields.ts";
import { unsharedVideoPairs } from "../video-share.ts";
import { youtubeWithinCourseKey } from "../youtube-identity.ts";
import { BUNDLE_AUTHOR } from "./batch.ts";
import { declareRule } from "./registry.ts";
import { placementInstitutionFailures, type HomeRowRef } from "./home.ts";

// Rules that need stored state run over a snapshot slice: the rows a batch references, loaded by a port in one round
// trip. The tests hand the same slice in memory.

/** What a batch references, by key. */
export interface RefKeys {
  readonly licenses: readonly string[];
  readonly sources: readonly string[];
  readonly areas: readonly string[];
  readonly subareas: readonly (readonly [areaId: string, subareaId: string])[];
  readonly authorIds: readonly string[];
  readonly authorSlugs: readonly string[];
  readonly courseIds: readonly string[];
  readonly courseSlugs: readonly string[];
  readonly editionIds: readonly string[];
  readonly youtubeIds: readonly string[];
  readonly homeRowIds: readonly string[];
}

/** The stored rows those keys reach. */
export interface CatalogRefs {
  readonly licenses: ReadonlySet<string>;
  readonly sources: ReadonlySet<string>;
  readonly areas: ReadonlySet<string>;
  readonly subareas: readonly { readonly areaId: string; readonly id: string }[];
  readonly authors: readonly { readonly id: string; readonly slug: string }[];
  /** Courses holding one of the batch's course slugs. */
  readonly courses: readonly { readonly id: string; readonly slug: string; readonly institutionId?: string | null }[];
  /** Editions of the batch's courses, and editions with one of its edition ids. */
  readonly editions: readonly { readonly id: string; readonly courseId: string; readonly slug: string; readonly position: number; readonly year: number; readonly variant: EditionVariant | null }[];
  /** YouTube lesson videos with one of the batch's video ids, in any course. */
  readonly videos: readonly { readonly lessonId: string; readonly courseId: string; readonly youtubeId: string }[];
  /** Share lists of the batch's courses and of courses that already hold one of its videos (D-032). */
  readonly shares: readonly { readonly id: string; readonly sharedWith: readonly string[] }[];
  /** Lessons of the batch's courses. */
  readonly lessons: readonly { readonly id: string; readonly courseId: string; readonly slug: string }[];
  readonly homeRows: readonly HomeRowRef[];
}

/** Loads the refs of a batch in one round trip. */
export interface CatalogRefsPort {
  load(keys: RefKeys): Promise<CatalogRefs>;
}

const REF_LICENSE = declareRule("ref.license.unknown", "A course's license exists.");
const REF_SOURCE = declareRule("ref.source.unknown", "A course's content source exists.");
const REF_AREA = declareRule("ref.area.unknown", "A course's area exists.");
const REF_SUBAREA = declareRule("ref.subarea.unknown", "A course's subarea exists inside its area (INV-H2).");
const BUNDLE_SLUG = declareRule("bundle.slug", "A course slug, and a lesson slug in its course, is free.");
const BUNDLE_EDITION = declareRule("bundle.edition", "An edition id, slug and position are not another edition's.");
const BUNDLE_VIDEO = declareRule("bundle.video", "A YouTube video is at most one lesson per course (INV-R3, D-003).");
const VIDEO_SHARE = declareRule("video.share", "A YouTube video used by two courses is declared by both (INV-R3, D-032).");

const unique = (values: Iterable<string>) => [...new Set(values)];

export function refKeys(bundles: readonly CourseBundleV1[]): RefKeys {
  const courses = bundles.map((bundle) => bundle.course);
  return {
    licenses: unique(courses.flatMap((course) => (course.licenseCode ? [course.licenseCode] : []))),
    sources: unique(courses.flatMap((course) => (course.sourceId ? [course.sourceId] : []))),
    areas: unique(courses.flatMap((course) => (course.areaId ? [course.areaId] : []))),
    subareas: courses.flatMap((course) => (typeof course.subareaId === "string" && course.areaId ? [[course.areaId, course.subareaId] as const] : [])),
    authorIds: bundles.map((bundle) => bundle.author.id),
    authorSlugs: bundles.map((bundle) => bundle.author.slug),
    courseIds: courses.map((course) => course.id),
    courseSlugs: courses.map((course) => course.slug),
    editionIds: bundles.flatMap((bundle) => bundle.editions.map((edition) => edition.id)),
    youtubeIds: bundles.flatMap((bundle) => bundle.lessons.map((lesson) => lesson.youtubeId)),
    homeRowIds: unique(bundles.flatMap((bundle) => (bundle.home ? [bundle.home.rowId] : []))),
  };
}

/** Every reference of the batch that the stored catalog refuses, all at once (G-5). */
export function referenceFailures(bundles: readonly CourseBundleV1[], refs: CatalogRefs): PreconditionFailure[] {
  const failures: PreconditionFailure[] = [];
  const batch = new Set(bundles.map((bundle) => bundle.course.id));
  const subareas = new Set(refs.subareas.map((row) => `${row.areaId}/${row.id}`));
  const authorBySlug = new Map(refs.authors.map((row) => [row.slug, row.id]));
  const slugOwner = new Map(refs.courses.map((row) => [row.slug, row.id]));
  const editionOwner = new Map(refs.editions.map((row) => [row.id, row.courseId]));
  const editionSlug = new Map(refs.editions.map((row) => [`${row.courseId}/${row.slug}`, row.id]));
  const editionPosition = new Map(refs.editions.map((row) => [`${row.courseId}/${String(row.position)}`, row.id]));
  const editionOffering = new Map(refs.editions.map((row) => [`${row.courseId}\n${offeringKey(row.year, row.variant)}`, row.id]));
  const videoOwner = new Map(refs.videos.map((row) => [youtubeWithinCourseKey(row.courseId, row.youtubeId), row.lessonId]));
  const lessonSlug = new Map(refs.lessons.map((row) => [`${row.courseId}/${row.slug}`, row.id]));
  const lessonIds = new Set(refs.lessons.map((row) => row.id));
  for (const bundle of bundles) {
    const course = bundle.course;
    const id = course.id;
    const entity = `course:${id}`;
    // D-024: the bundle's author is the lecturer; only a course already offered by another institution conflicts.
    const offeredBy = refs.courses.find((row) => row.id === id)?.institutionId;
    if (bundle.home && offeredBy) failures.push(...placementInstitutionFailures(refs.homeRows.find((row) => row.id === bundle.home?.rowId), offeredBy, id));
    if (course.licenseCode && !refs.licenses.has(course.licenseCode)) failures.push(REF_LICENSE.fail(entity, `License ${course.licenseCode} does not exist.`));
    if (course.sourceId && !refs.sources.has(course.sourceId)) failures.push(REF_SOURCE.fail(entity, `Source ${course.sourceId} does not exist.`));
    if (course.areaId && !refs.areas.has(course.areaId)) failures.push(REF_AREA.fail(entity, `Area ${course.areaId} does not exist.`));
    if (typeof course.subareaId === "string" && course.areaId && !subareas.has(`${course.areaId}/${course.subareaId}`)) failures.push(REF_SUBAREA.fail(entity, `Subarea ${course.subareaId} is not in ${course.areaId}.`));
    const author = authorBySlug.get(bundle.author.slug);
    if (author !== undefined && author !== bundle.author.id) failures.push(BUNDLE_AUTHOR.fail(entity, `Author slug ${bundle.author.slug} belongs to ${author}.`));
    const owner = slugOwner.get(course.slug);
    if (owner !== undefined && !batch.has(owner)) failures.push(BUNDLE_SLUG.fail(entity, `Slug ${course.slug} belongs to another course.`));
    for (const edition of bundle.editions) {
      const editionCourse = editionOwner.get(edition.id);
      if (editionCourse !== undefined && editionCourse !== id) failures.push(BUNDLE_EDITION.fail(entity, `Edition ${edition.id} belongs to ${editionCourse}.`));
      const slug = editionSlug.get(`${id}/${edition.slug}`);
      if (slug !== undefined && slug !== edition.id) failures.push(BUNDLE_EDITION.fail(entity, `Edition slug ${edition.slug} is taken in ${id}.`));
      const position = editionPosition.get(`${id}/${String(edition.position)}`);
      if (position !== undefined && position !== edition.id) failures.push(BUNDLE_EDITION.fail(entity, `Edition position ${String(edition.position)} is taken in ${id}.`));
      if (edition.year !== null) {
        const offering = editionOffering.get(`${id}\n${offeringKey(edition.year, edition.variant)}`);
        if (offering !== undefined && offering !== edition.id) failures.push(BUNDLE_EDITION.fail(entity, indistinctEditionMessage(edition.year, [edition.id, offering])));
      }
    }
    for (const lesson of bundle.lessons) {
      const video = videoOwner.get(youtubeWithinCourseKey(id, lesson.youtubeId));
      if (video !== undefined && video !== lesson.id) failures.push(BUNDLE_VIDEO.fail(entity, `Video ${lesson.youtubeId} belongs to ${video}.`));
      const slug = lessonSlug.get(`${id}/${lesson.slug}`);
      if (slug !== undefined && slug !== lesson.id && !lessonIds.has(lesson.id)) failures.push(BUNDLE_SLUG.fail(entity, `Lesson slug ${lesson.slug} is taken in ${id}.`));
    }
  }
  const shares = new Map<string, readonly string[]>();
  for (const row of refs.shares) shares.set(row.id, row.sharedWith);
  for (const bundle of bundles) shares.set(bundle.course.id, bundle.course.sharedWith);
  const declared = new Set(bundles.map((bundle) => bundle.course.id));
  const uses = [
    ...refs.videos.map((row) => ({ courseId: row.courseId, youtubeId: row.youtubeId })),
    ...bundles.flatMap((bundle) => bundle.lessons.map((lesson) => ({ courseId: bundle.course.id, youtubeId: lesson.youtubeId }))),
  ];
  for (const problem of unsharedVideoPairs(uses, shares, declared)) {
    failures.push(VIDEO_SHARE.fail(`course:${problem.courseId}`, `Video ${problem.youtubeId} is also in ${problem.otherCourseId}; both courses must declare the share.`));
  }
  return failures;
}
