// D-035. One list of the cover kinds each owner accepts. The batch schema, the plan, mediaKey and the
// catalog_media check all read this module. A second list is a bug.

export const coverOwners = ["institution", "area", "subarea", "course", "lesson"] as const;
export type CoverOwner = (typeof coverOwners)[number];

/** Batch taxonomy field for a kind. Institution-only and lesson frame kinds have no field here. */
export const coverFieldByKind = {
  poster_9x16: "poster",
  hero_desktop_16x9: "heroDesktop",
  hero_present: "heroPresent",
  hero_mobile_9x16: "heroMobile",
  og: "og",
  still_16x9: "still",
  lesson_default: "lessonDefault",
} as const;
type TaxonomyKind = keyof typeof coverFieldByKind;

export const coverKindsByOwner = {
  institution: ["author_cover_9x16", "university_cover_9x16", "poster_9x16", "og"],
  /** An area accepts the subarea set plus still_16x9 (D-035). A subarea does not accept still. */
  area: ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16", "og", "still_16x9", "lesson_default"],
  subarea: ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16", "og", "lesson_default"],
  course: ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16", "still_16x9", "lesson_default", "thumb"],
  lesson: ["cover_16x9", "cover_9x16", "thumb"],
} as const satisfies Record<CoverOwner, readonly [string, ...string[]]> & { area: readonly TaxonomyKind[]; subarea: readonly TaxonomyKind[] };

/** The four kinds a published course's declared owner must have. */
export const requiredCoverKinds = ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16"] as const;

/** Course kinds a CatalogBatchV2 course cover entry may name. lesson_default and thumb stay off that list. */
export const batchCourseCoverKinds = ["poster_9x16", "hero_desktop_16x9", "hero_present", "hero_mobile_9x16", "still_16x9"] as const;

const batchCourseExcluded = new Set<string>(["lesson_default", "thumb"]);

function same(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((kind, index) => kind === right[index]);
}

const derivedBatchCourse = coverKindsByOwner.course.filter((kind) => !batchCourseExcluded.has(kind));
if (!same(derivedBatchCourse, batchCourseCoverKinds)) {
  throw new Error("batchCourseCoverKinds drifted from coverKindsByOwner.course.");
}
for (const owner of ["area", "subarea", "course"] as const) {
  for (const kind of requiredCoverKinds) {
    if (!(coverKindsByOwner[owner] as readonly string[]).includes(kind)) throw new Error(`${owner} is missing required cover kind ${kind}.`);
  }
}
// The figure refuses a kind this list does not name (media/domain/cover-choice.ts). This module stays the one list.
