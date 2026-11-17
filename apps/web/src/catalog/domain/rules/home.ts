import type { PreconditionFailure } from "../../../kernel/errors.ts";
import { courseStatus } from "../course-status.ts";
import type { HomePut } from "../contracts.ts";
import { homeRowKinds, homeRowRecord, homeRowSpec } from "../home-row-kind.ts";
import { declareRule } from "./registry.ts";
import { HOME_ROW } from "./publish-answers.ts";

// Home row rules: PUT /home, a bundle apply into a row and a ship batch into rows all call these.

/** A stored (or wanted) Home row, as the cover rule reads it. */
export interface StoredCoverRow {
  readonly id: string;
  readonly kind: string;
  readonly visible: boolean;
  readonly cover: unknown;
  readonly authorId: string | null;
}

/** A stored Home row a batch points at, with its author's cover state (null when the row has no stored author). */
export interface HomeRowRef {
  readonly id: string;
  readonly kind: string;
  readonly visible: boolean;
  readonly hasCover: boolean;
  readonly authorId: string | null;
  readonly authorHasCover: boolean | null;
  readonly institutionId?: string | null;
}

/** Courses that sit on a visible Home row. The showcase answers this; publish only asks. */
export function coursesOnVisibleRows(
  rows: readonly { readonly id: string; readonly visible: boolean }[],
  items: readonly { readonly row_id: string; readonly course_id: string }[],
): ReadonlySet<string> {
  const visible = new Set<string>();
  for (const row of rows) if (row.visible) visible.add(row.id);
  const courses = new Set<string>();
  for (const item of items) if (visible.has(item.row_id)) courses.add(item.course_id);
  return courses;
}

const HOME_REVISION = declareRule("home.revision", "A change to Home rows names the current Home revision.");
const HOME_COVER = declareRule("home.cover", "A visible university row has its own cover; a visible author row's author has one (INV-M4, D-002).");
const HOME_VALID = declareRule("home.valid", "Rows are unique, typed by kind, and hold existing courses; the featured course is published.");

/** Every visible row that would show without its cover. `authorHasCover` is false only when that author exists and has none. */
export function homeCoverFailures(rows: readonly StoredCoverRow[], authorHasCover: ReadonlyMap<string, boolean>): PreconditionFailure[] {
  const failures: PreconditionFailure[] = [];
  for (const row of rows) {
    if (!row.visible) continue;
    const spec = homeRowRecord(row.kind);
    if (spec?.cover === "own" && !row.cover) failures.push(HOME_COVER.fail(`home_row:${row.id}`, `Curated row ${row.id} needs a cover.`));
    if (spec?.cover === "author" && row.authorId !== null && authorHasCover.get(row.authorId) === false) failures.push(HOME_COVER.fail(`home_row:${row.id}`, `Author row ${row.id} needs a cover on ${row.authorId}.`));
  }
  return failures;
}

/** The cover rule's messages, for the 422 `errors` list of PUT /home, a bundle apply and a ship batch. */
export function storedCoverErrors(rows: readonly StoredCoverRow[], authorHasCover: ReadonlyMap<string, boolean>): string[] {
  return homeCoverFailures(rows, authorHasCover).map((failure) => failure.message);
}

/** The cover rule over stored row refs. */
export function homeRefCoverErrors(rows: readonly HomeRowRef[]): string[] {
  const authors = new Map(rows.flatMap((row) => (row.authorId !== null && row.authorHasCover !== null ? [[row.authorId, row.authorHasCover] as const] : [])));
  return storedCoverErrors(rows.map((row) => ({ id: row.id, kind: row.kind, visible: row.visible, cover: row.hasCover || null, authorId: row.authorId })), authors);
}

/** A ship batch's Home placements: each row exists and the batch names the current revision. */
export function homePlacementFailures(homes: readonly { readonly rowId: string; readonly courseId: string; readonly expectedRevision: number }[], rows: readonly HomeRowRef[], revision: number): PreconditionFailure[] {
  const found = new Set(rows.map((row) => row.id));
  return homes.flatMap((home) => {
    if (!found.has(home.rowId)) return [HOME_ROW.fail(`course:${home.courseId}`, `Home row ${home.rowId} does not exist.`)];
    return home.expectedRevision === revision ? [] : [HOME_REVISION.fail(`course:${home.courseId}`, `Home revision is ${String(revision)}, not ${String(home.expectedRevision)}.`)];
  });
}

/**
 * Every Home invariant of PUT /home, all at once (the 422 lists them). A row may hold a course in draft or review:
 * releases show only published courses, so it appears when it is published. Archived and unknown courses are refused.
 */
export function homeFailures(body: HomePut, statuses: ReadonlyMap<string, string>, authors: ReadonlySet<string>): PreconditionFailure[] {
  const errors: string[] = [];
  for (const kind of homeRowKinds) {
    const cap = homeRowSpec(kind).maxRows;
    if (cap !== null && body.rows.filter((row) => row.kind === kind).length > cap) errors.push("At most one continue row.");
  }
  const ids = new Set<string>();
  for (const row of body.rows) {
    if (ids.has(row.id)) errors.push(`Row ${row.id} appears twice.`);
    ids.add(row.id);
    const spec = homeRowSpec(row.kind);
    if (spec.titleRequired && row.title === undefined) errors.push(`Curated row ${row.id} needs a title.`);
    if (spec.author && (row.authorId === undefined || !authors.has(row.authorId))) errors.push(`Author row ${row.id} needs an existing authorId.`);
    if ((!spec.fullName || !spec.place) && (row.fullName || row.place)) errors.push(`Row ${row.id} (${row.kind}) takes no full name or place: they are for curated (university) rows.`);
    if (spec.cover !== "own" && row.cover) errors.push(`Row ${row.id} (${row.kind}) takes no cover: covers are for curated (university) rows.`);
    if (!spec.author && row.authorId !== undefined) errors.push(`Row ${row.id} (${row.kind}) takes no authorId.`);
    if (!spec.catalogCourses && row.courseIds.length > 0) errors.push("The continue row is derived from progress: no courseIds.");
    if (new Set(row.courseIds).size !== row.courseIds.length) errors.push(`Row ${row.id} repeats a course.`);
    for (const id of row.courseIds) {
      const status = statuses.get(id);
      if (status === undefined) errors.push(`Row ${row.id}: course ${id} does not exist.`);
      else if (status === courseStatus.archived) errors.push(`Row ${row.id}: course ${id} is ${courseStatus.archived}.`);
    }
  }
  if (body.featuredCourseId !== null && statuses.get(body.featuredCourseId) !== courseStatus.published) errors.push(`Featured course ${body.featuredCourseId} is not ${courseStatus.published}.`);
  return errors.map((message) => HOME_VALID.fail("home", message));
}

const HOME_INSTITUTION = declareRule("home.institution", "A curated row belongs to one existing institution and groups only its courses (INV-H5).");
/** A declaration wins; otherwise the row's courses can identify exactly one provenance parent. */
export function rowInstitution(row: Pick<HomePut["rows"][number], "institutionId" | "courseIds">, courseInstitutions: ReadonlyMap<string, string>): string | undefined {
  if (row.institutionId) return row.institutionId;
  const parents = new Set(row.courseIds.flatMap((id) => { const parent = courseInstitutions.get(id); return parent ? [parent] : []; }));
  return parents.size === 1 ? [...parents][0] : undefined;
}
export function homeInstitutionFailures(rows: HomePut["rows"], institutions: ReadonlySet<string>, courseInstitutions: ReadonlyMap<string, string>): PreconditionFailure[] {
  const failed: PreconditionFailure[] = [], used = new Set<string>();
  for (const row of rows) {
    if (!homeRowSpec(row.kind).institution) {
      if (row.institutionId) failed.push(HOME_INSTITUTION.fail(`home_row:${row.id}`, "Only a curated row takes institutionId."));
      continue;
    }
    const institution = rowInstitution(row, courseInstitutions);
    if (!institution || !institutions.has(institution)) failed.push(HOME_INSTITUTION.fail(`home_row:${row.id}`, "A curated row needs exactly one existing institution."));
    else {
      if (used.has(institution)) failed.push(HOME_INSTITUTION.fail(`home_row:${row.id}`, `Institution ${institution} already has a curated row.`));
      used.add(institution);
      if (row.courseIds.some((id) => courseInstitutions.has(id) && courseInstitutions.get(id) !== institution)) failed.push(HOME_INSTITUTION.fail(`home_row:${row.id}`, "A curated row cannot group institutions."));
    }
  }
  return failed;
}

/** Existing placements use the same institution rule as PUT /home. */
export function placementInstitutionFailures(row: HomeRowRef | undefined, institutionId: string, courseId: string): PreconditionFailure[] {
  const spec = row ? homeRowRecord(row.kind) : undefined;
  return spec?.institution && row?.institutionId != null && row.institutionId !== institutionId
    ? [HOME_INSTITUTION.fail(`course:${courseId}`, `Curated row ${row.id} belongs to institution ${row.institutionId}.`)] : [];
}
