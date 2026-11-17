import type { PreconditionFailure } from "../../../kernel/errors.ts";
import { validateCourseBundle, type CourseBundleV1 } from "../bundle.ts";
import { youtubeWithinCourseKey } from "../youtube-identity.ts";
import { declareRule } from "./registry.ts";

// Rules over the bundles of one batch alone (no stored state): shape, then duplicates inside the batch.

const BUNDLE_INVALID = declareRule("bundle.invalid", "A bundle matches the catalog schema.");
const BUNDLE_EDITION_YEAR = declareRule("bundle.edition.year", "An edition names a known year. A missing year is refused.");
const BUNDLE_DUPLICATE = declareRule("bundle.duplicate", "A course, slug, edition, lesson, video or text appears once in the batch.");
export const BUNDLE_AUTHOR = declareRule("bundle.author", "One author id is one person, and an author slug names one author.");

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function labelOf(input: unknown, index: number): string {
  const course = record(record(input)?.course);
  const id = typeof course?.id === "string" ? course.id.trim() : "";
  return id || `bundle-${String(index)}`;
}

/** Every raw bundle parsed; each one that fails is named by its course id (or its index). */
export function parseBundles(raw: readonly unknown[]): { bundles: CourseBundleV1[]; failures: PreconditionFailure[] } {
  const bundles: CourseBundleV1[] = [];
  const failures: PreconditionFailure[] = [];
  raw.forEach((input, index) => {
    const parsed = validateCourseBundle(input);
    if (!parsed.ok) {
      const rule = /no known year/.test(parsed.error.message) ? BUNDLE_EDITION_YEAR : BUNDLE_INVALID;
      failures.push(rule.fail(`course:${labelOf(input, index)}`, parsed.error.message));
    } else bundles.push(parsed.value);
  });
  return { bundles, failures };
}

/** Every duplicate inside the batch. The CLI runs it before sending; the server runs it again on the whole batch. */
export function duplicateFailures(bundles: readonly CourseBundleV1[]): PreconditionFailure[] {
  const failures: PreconditionFailure[] = [];
  const seen = () => {
    const taken = new Map<string, string>();
    return (key: string, courseId: string, message: string) => {
      const owner = taken.get(key);
      if (owner !== undefined) failures.push(BUNDLE_DUPLICATE.fail(`course:${courseId}`, message));
      else taken.set(key, courseId);
    };
  };
  const courseIds = seen();
  const slugs = seen();
  const lessons = seen();
  const videos = seen();
  const editions = seen();
  const authors = new Map<string, string>();
  const authorSlugs = new Map<string, string>();
  const editionSlugs = seen();
  const editionPositions = seen();
  const lessonSlugs = seen();
  const lessonPositions = seen();
  for (const bundle of bundles) {
    const id = bundle.course.id;
    courseIds(id, id, `Course ${id} appears twice in the batch.`);
    slugs(bundle.course.slug, id, `Slug ${bundle.course.slug} appears twice in the batch.`);
    const author = authors.get(bundle.author.id);
    const authorKey = `${bundle.author.slug}\n${bundle.author.name}\n${bundle.author.monogram}`;
    if (author !== undefined && author !== authorKey) failures.push(BUNDLE_AUTHOR.fail(`course:${id}`, `Author ${bundle.author.id} is not the same person in every bundle.`));
    else authors.set(bundle.author.id, authorKey);
    const slugOwner = authorSlugs.get(bundle.author.slug);
    if (slugOwner !== undefined && slugOwner !== bundle.author.id) failures.push(BUNDLE_AUTHOR.fail(`course:${id}`, `Author slug ${bundle.author.slug} is used by ${slugOwner}.`));
    else authorSlugs.set(bundle.author.slug, bundle.author.id);
    for (const edition of bundle.editions) {
      editions(edition.id, id, `Edition ${edition.id} appears twice in the batch.`);
      editionSlugs(`${id}/${edition.slug}`, id, `Edition slug ${edition.slug} appears twice in ${id}.`);
      editionPositions(`${id}/${String(edition.position)}`, id, `Edition position ${String(edition.position)} appears twice in ${id}.`);
    }
    const texts = new Set<string>();
    for (const text of bundle.texts) {
      const key = `${text.entityKind}/${text.entityId}/${text.field}`;
      if (texts.has(key)) failures.push(BUNDLE_DUPLICATE.fail(`course:${id}`, `Text ${text.field} on ${text.entityId} is repeated.`));
      texts.add(key);
    }
    for (const lesson of bundle.lessons) {
      lessons(lesson.id, id, `Lesson ${lesson.id} appears twice in the batch.`);
      videos(youtubeWithinCourseKey(id, lesson.youtubeId), id, `Video ${lesson.youtubeId} appears twice in ${id}.`);
      lessonSlugs(`${id}/${lesson.slug}`, id, `Lesson slug ${lesson.slug} appears twice in ${id}.`);
      lessonPositions(`${id}/${String(lesson.position)}`, id, `Lesson position ${String(lesson.position)} appears twice in ${id}.`);
    }
  }
  return failures;
}
