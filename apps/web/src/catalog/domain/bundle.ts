import { z } from "zod";
import { canonicalJson, sha256Hex } from "../../kernel/canonical.ts";
import { AppError, invalid } from "../../kernel/errors.ts";
import { courseBundleSchema } from "./schema/bundle.ts";
import { bundleCoverKinds, rightsStatuses } from "./schema/fields.ts";

export const bundleBody = z.strictObject({
  bundle: z.unknown(),
  current: z.unknown().optional(),
  replayKey: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/).optional(),
});

export type CourseBundleV1 = z.output<typeof courseBundleSchema>;
export type BundleCoverKind = (typeof bundleCoverKinds)[number];
export type BundleRights = (typeof rightsStatuses)[number];
export { bundleCoverKinds as BUNDLE_COVER_KINDS, rightsStatuses as BUNDLE_RIGHTS };

export type Result<T, E> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: E };

export interface BundleDiff {
  readonly course: { readonly changed: readonly string[] };
  readonly lessons: { readonly added: readonly string[]; readonly omitted: readonly string[]; readonly changed: readonly string[] };
  readonly texts: { readonly changed: readonly string[] };
  readonly home: { readonly changed: boolean };
  /** Omitted lessons are not deletions. Empty means apply would not change stored rows. */
  readonly empty: boolean;
}

function fail(message: string): Result<CourseBundleV1, AppError> {
  return { ok: false, error: invalid(message) };
}

/** The first problem, worded for the CLI and the API: a cross-field rule as is, a field problem with its path. */
function problemOf(error: z.ZodError): string {
  const issue = error.issues[0];
  if (!issue) return "Invalid course bundle.";
  if (issue.code === "custom" || issue.path.length === 0) return issue.message;
  return `${issue.path.join(".")}: ${issue.message}`;
}

/** Unknown versions and dangling references fail before any write. Absence of a collection is merge, not deletion. */
export function validateCourseBundle(input: unknown): Result<CourseBundleV1, AppError> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) return fail("A course bundle is an object.");
  if ((input as { version?: unknown }).version !== 1) return fail("Only CourseBundleV1 is accepted.");
  const parsed = courseBundleSchema.safeParse(input);
  return parsed.success ? { ok: true, value: parsed.data } : fail(problemOf(parsed.error));
}

/** A bundle may leave an edition's year unknown (null), but the store (0009) keeps a year on every edition: such a bundle is refused on write, never given an invented year. */
export function unknownYearMessage(bundle: CourseBundleV1): string | null {
  const ids = bundle.editions.filter((edition) => edition.year === null).map((edition) => edition.id);
  return ids.length === 0 ? null : `Edition ${ids.join(", ")} has no known year; name the year before writing it.`;
}

export function normalizeCourseBundle(bundle: CourseBundleV1): CourseBundleV1 {
  const parsed = validateCourseBundle(bundle);
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

export function bundleHash(bundle: CourseBundleV1): string {
  return sha256Hex(canonicalJson(bundle));
}

export function exportCourseBundle(bundle: CourseBundleV1): CourseBundleV1 {
  const parsed = validateCourseBundle(bundle);
  if (!parsed.ok) throw parsed.error;
  return parsed.value;
}

function changedFields(before: Record<string, unknown>, after: Record<string, unknown>): string[] {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((field) => canonicalJson(before[field]) !== canonicalJson(after[field]));
}

/** Lessons missing from the next bundle are omitted, not removed. */
export function diffCourseBundle(current: CourseBundleV1 | null, next: CourseBundleV1): BundleDiff {
  const base = current ?? { ...next, lessons: [], texts: [], editions: next.editions, home: null, course: { ...next.course, title: "" } };
  const previous = new Map((current?.lessons ?? []).map((lesson) => [lesson.id, lesson]));
  const upcoming = new Map(next.lessons.map((lesson) => [lesson.id, lesson]));
  const added = [...upcoming.keys()].filter((id) => !previous.has(id));
  const omitted = [...previous.keys()].filter((id) => !upcoming.has(id));
  const changed = [...upcoming.values()].flatMap((lesson) => {
    const prior = previous.get(lesson.id);
    return prior && canonicalJson(prior) !== canonicalJson(lesson) ? [lesson.id] : [];
  });
  const course = current ? changedFields({ ...current.course }, { ...next.course }) : ["id"];
  const priorTexts = new Map((current?.texts ?? []).map((row) => [`${row.entityKind}:${row.entityId}:${row.field}`, row]));
  const texts = next.texts.filter((row) => canonicalJson(priorTexts.get(`${row.entityKind}:${row.entityId}:${row.field}`)) !== canonicalJson(row)).map((row) => `${row.entityKind}:${row.entityId}:${row.field}`);
  const home = canonicalJson(current?.home ?? null) !== canonicalJson(next.home);
  const covers = canonicalJson(current?.covers ?? []) !== canonicalJson(next.covers);
  const empty = course.length === 0 && added.length === 0 && changed.length === 0 && texts.length === 0 && !home && !covers && canonicalJson(base.author) === canonicalJson(next.author);
  return { course: { changed: course }, lessons: { added, omitted, changed }, texts: { changed: texts }, home: { changed: home }, empty };
}
