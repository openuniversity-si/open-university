/**
 * Editorial text fields of `catalog_texts` (the 0005 CHECK) with their character budgets. The budgets are the Figma slot
 * budgets of "Proto — Dynamic" (catalog-slots.json, P0 work file): Billboard title 40, subtitle 64, Billboard description
 * 240/120 (Home and course page share the Billboard), About 170, level 16, format 28, lesson title 64, lesson About 300.
 * shelfTitle has no slot of its own and shares the title budget; author bio is not in the release (§11) and gets the
 * lesson About budget. ADR-18 records why these live here before P0 adds design/catalog-slots.json and its CI cross-check.
 *
 * `review`: must be filled for draft → review (plan §2.2: the 10 course fields and each lesson's displayTitle).
 * `publish`: must be approved for review → published; an optional field is omitted from the release unless approved.
 * `release`: how a release carries the key. `required` is a string, `nullable` is present and may be null,
 * `optional` is omitted when there is no text so a stored release without the key still parses, and `off` is not a release key.
 *
 * The database CHECK reads these names. `textIssues` stays in the catalog because it calls the site alphabet.
 */
export type ReleasePresence = "required" | "nullable" | "optional" | "off";

export interface TextField {
  readonly maxChars: number;
  readonly review: boolean;
  readonly publish: boolean;
  readonly release: ReleasePresence;
}
const field = <const R extends ReleasePresence>(maxChars: number, review: boolean, publish: boolean, release: R): TextField & { readonly release: R } =>
  ({ maxChars, review, publish, release });

export const TEXT_FIELDS = {
  course: {
    displayTitle: field(40, true, true, "required"),
    shelfTitle: field(40, true, true, "required"),
    subtitle: field(64, true, true, "required"),
    billboardDescription: field(240, true, true, "required"),
    billboardDescriptionMobile: field(120, true, true, "required"),
    description: field(240, true, true, "required"),
    descriptionMobile: field(120, true, true, "required"),
    about: field(170, true, false, "nullable"),
    level: field(16, true, true, "required"),
    format: field(28, true, true, "required"),
  },
  lesson: {
    displayTitle: field(64, true, true, "required"),
    about: field(300, false, false, "nullable"),
  },
  author: {
    bio: field(300, false, false, "off"),
  },
} as const satisfies Record<string, Record<string, TextField>>;
