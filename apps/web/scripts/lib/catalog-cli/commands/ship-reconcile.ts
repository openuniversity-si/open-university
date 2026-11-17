import type { CourseBundleV1 } from "../../../../src/catalog/domain/bundle.ts";
import { TEXT_FIELDS } from "../../../../src/catalog/domain/fields.ts";

/** Course and lesson text keys a release carries. A field marked off the release is not compared. */
const isReleaseKey = (release: "required" | "nullable" | "optional" | "off") => release !== "off";
const COURSE_TEXTS = new Set(Object.entries(TEXT_FIELDS.course).filter(([, spec]) => isReleaseKey(spec.release)).map(([name]) => name));
const LESSON_TEXTS = new Set(Object.entries(TEXT_FIELDS.lesson).filter(([, spec]) => isReleaseKey(spec.release)).map(([name]) => name));

type Row = Readonly<Record<string, unknown>>;

function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.filter((item): item is Row => typeof item === "object" && item !== null) : [];
}

/** Same offering only when kind and label match. A missing variant is empty, so it does not match a present one. */
function variantKey(value: unknown): string {
  if (typeof value !== "object" || value === null) return "\n";
  const variant = value as Row;
  return `${typeof variant.kind === "string" ? variant.kind : ""}\n${typeof variant.label === "string" ? variant.label : ""}`;
}

/**
 * True when the active release already shows this bundle: the course with the bundle's fields, editions, lessons and
 * approved texts. A ship that stopped after the batch release (a lease lost, a dead process) then only verifies and
 * completes the job; it never publishes again. Any difference returns false, and the normal path decides.
 */
export function releaseShowsBundle(payload: unknown, bundle: CourseBundleV1): boolean {
  const release = typeof payload === "object" && payload !== null ? payload as Row : {};
  const wanted = bundle.course;
  const course = rows(release.courses).find((row) => row.id === wanted.id);
  if (!course) return false;
  const rights = (typeof course.rights === "object" && course.rights !== null ? course.rights : {}) as Row;
  const same = (actual: unknown, expected: unknown) => expected === undefined || actual === expected;
  if (course.slug !== wanted.slug || course.title !== wanted.title || course.authorId !== wanted.authorId || course.lessonNoun !== wanted.lessonNoun) return false;
  if (!same(course.languageLabel, wanted.languageLabel) || !same(course.areaId, wanted.areaId)) return false;
  if (wanted.subareaId !== undefined && (course.subareaId ?? null) !== wanted.subareaId) return false;
  if (course.coverFrom !== wanted.coverFrom) return false;
  if (wanted.sharedWith.length > 0) return false;
  if (!same(rights.licenseCode, wanted.licenseCode) || !same(rights.canonicalUrl, wanted.canonicalUrl) || !same(rights.attribution, wanted.attributionText)) return false;
  const editions = new Map(rows(course.editions).map((row) => [row.id, row]));
  for (const edition of bundle.editions) {
    const row = editions.get(edition.id);
    if (!row || row.slug !== edition.slug || row.label !== edition.label || row.year !== edition.year || row.position !== edition.position) return false;
    if (variantKey(row.variant) !== variantKey(edition.variant)) return false;
  }
  const lessons = new Map(rows(release.lessons).filter((row) => row.courseId === wanted.id).map((row) => [row.id, row]));
  for (const lesson of bundle.lessons) {
    const row = lessons.get(lesson.id);
    if (!row || row.slug !== lesson.slug || row.youtubeId !== lesson.youtubeId || row.durationSeconds !== lesson.durationSeconds || row.editionId !== lesson.editionId || row.part !== lesson.part) return false;
  }
  for (const text of bundle.texts) {
    if (!text.approved) continue;
    if (text.entityKind === "course" && COURSE_TEXTS.has(text.field) && course[text.field] !== text.text) return false;
    if (text.entityKind === "lesson" && LESSON_TEXTS.has(text.field) && lessons.get(text.entityId)?.[text.field] !== text.text) return false;
  }
  return true;
}
