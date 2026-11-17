import type { PreconditionFailure } from "../../../kernel/errors.ts";
import { declareRule, type RuleBlocker } from "./registry.ts";
import { COURSE_STATUS, LESSONS_VISIBLE } from "./status.ts";

// Rules that guard an edit or a delete of stored rows: the routes load the counts, the rule decides.

const STATE = declareRule("state", "A published course, or one published before, is archived before it is purged.");
const FEATURED = declareRule("featured", "Archiving the featured course names its replacement.");
const HAS_DEPENDENTS = declareRule("has_dependents", "A row that others point to is not deleted.");
const COURSE_CLASSIFICATION = declareRule("course.classification", "A course's area and subarea exist and agree (INV-H2).");
const COURSE_MISSING = declareRule("course.missing", "Every course of a ship batch is written.");
const TEXTS_DUPLICATE = declareRule("texts.duplicate", "A text slot appears once in a texts batch.");
const TEXTS_ENTITY = declareRule("texts.entity", "A text belongs to an entity that exists.");

export function courseDeleteBlockers(input: { readonly mode: string; readonly status: string; readonly publishedBefore: boolean; readonly featured: boolean; readonly replacementGiven: boolean }): RuleBlocker[] {
  const blockers: RuleBlocker[] = [];
  if (input.mode === "purge" && input.status === COURSE_STATUS.published) blockers.push(STATE.block(`A ${COURSE_STATUS.published} course is never purged: archive it first (DELETE ?mode=archive).`));
  if (input.mode === "purge" && (input.status === COURSE_STATUS.draft || input.status === COURSE_STATUS.review) && input.publishedBefore) blockers.push(STATE.block(`The course was ${COURSE_STATUS.published} before: archive it first, then purge.`));
  if (input.mode === "archive" && input.status === COURSE_STATUS.published && input.featured && !input.replacementGiven) blockers.push(FEATURED.block("The course is featured: pass replacementFeaturedId."));
  return blockers;
}

export function lessonDeleteBlockers(input: { readonly published: boolean; readonly visible: boolean; readonly otherVisible: number }): RuleBlocker[] {
  return input.published && input.visible && input.otherVisible === 0 ? [LESSONS_VISIBLE.block("The lesson is the last visible one of a published course.")] : [];
}

export function editionDeleteBlockers(input: { readonly editions: number; readonly lessons: number; readonly withLessons: boolean; readonly published: boolean; readonly visibleHere: boolean; readonly visibleElsewhere: number }): RuleBlocker[] {
  const blockers: RuleBlocker[] = [];
  if (input.editions <= 1) blockers.push(HAS_DEPENDENTS.block("The last edition of a course is never deleted; delete or archive the course instead."));
  if (input.lessons > 0 && !input.withLessons) blockers.push(HAS_DEPENDENTS.block(`The edition has ${String(input.lessons)} lesson(s): pass mode=with-lessons to delete them too.`));
  if (input.published && input.visibleHere && input.visibleElsewhere === 0) blockers.push(LESSONS_VISIBLE.block("The edition holds the last visible lessons of a published course."));
  return blockers;
}

export function authorDeleteBlockers(dependents: number): RuleBlocker[] {
  return dependents > 0 ? [HAS_DEPENDENTS.block("Courses or Home rows point to this author.")] : [];
}

/** Hiding a lesson of a published course: `visibleLessons` counts the course's visible lessons before the change. */
export function hideLessonFailures(courseId: string, published: boolean, visibleLessons: number): PreconditionFailure[] {
  return published && visibleLessons <= 1 ? [LESSONS_VISIBLE.fail(`course:${courseId}`, "A published course keeps at least one visible lesson.")] : [];
}

/** `problem` is the classification decision (course-view.ts) for the course's next area and subarea. */
export function classificationFailures(courseId: string, problem: string | null): PreconditionFailure[] {
  return problem ? [COURSE_CLASSIFICATION.fail(`course:${courseId}`, problem)] : [];
}

/** The courses of a ship batch that the write did not produce. */
export function notWrittenFailures(ids: readonly string[], written: ReadonlySet<string>): PreconditionFailure[] {
  return ids.filter((id) => !written.has(id)).map((id) => COURSE_MISSING.fail(`course:${id}`, "The course was not written."));
}

/** PUT /texts batch issues beyond each text's own slot issues: a repeated slot and an unknown entity, by item. */
export function textBatchIssues(items: readonly { readonly entityKind: string; readonly entityId: string; readonly field: string }[], exists: ReadonlySet<string>): RuleBlocker[][] {
  const seen = new Set<string>();
  return items.map((item) => {
    const entity = `${item.entityKind}:${item.entityId}`;
    const key = `${entity}.${item.field}`;
    const issues: RuleBlocker[] = [];
    if (seen.has(key)) issues.push(TEXTS_DUPLICATE.block(`${key} appears twice in the batch.`));
    if (!exists.has(entity)) issues.push(TEXTS_ENTITY.block(`${entity} does not exist.`));
    seen.add(key);
    return issues;
  });
}
