import { courseStatus } from "../course-status.ts";
import { columnsToVariant, indistinctEditions } from "../edition-variant.ts";
import { REQUIRED_COVERS } from "../cover-source.ts";
import { TEXT_FIELDS, textIssues } from "../fields.ts";
import { publishableRights } from "../schema/fields.ts";
import type { CatalogRow, CatalogTables } from "../tables.ts";
import type { PreconditionFailure } from "../contracts.ts";
import { sha256Hex } from "../../../kernel/canonical.ts";
import { coursesOnVisibleRows } from "./home.ts";
import { COVERS_ACTIVE, figurePresenceAnswer, HOME_ROW, lessonVideoCheckAnswer, showcaseRowAnswer, sitePageTextAnswer, VIDEOS_FRESH } from "./publish-answers.ts";
import { declareRule, type DeclaredRule } from "./registry.ts";

export { COVERS_ACTIVE, HOME_ROW };

// Status preconditions of plan §2.2 as named rules, shared by POST /courses/:id/status, publish, GET /courses(/:id) and doctor.

export { REQUIRED_COVERS };
export const PUBLISHABLE_RIGHTS = publishableRights;
export type RuleTarget = typeof courseStatus.review | typeof courseStatus.published;

/**
 * POST /courses/:id/status moves (plan §2.2). Published is reached only through POST /publish and left only through
 * POST /unpublish or DELETE ?mode=archive, which compile a release; archived to draft restores a course.
 */
export const COURSE_STATUS = courseStatus;
export const STATUS_TRANSITIONS = {
  [courseStatus.draft]: [courseStatus.review, courseStatus.archived],
  [courseStatus.review]: [courseStatus.draft, courseStatus.archived],
  [courseStatus.archived]: [courseStatus.draft],
  [courseStatus.published]: [],
} as const satisfies Record<string, readonly string[]>;
export function canTransition(from: string, to: string, transitions: Readonly<Record<string, readonly string[]>> = STATUS_TRANSITIONS): boolean {
  const allowed = transitions[from];
  return allowed?.includes(to) ?? false;
}

/** Everything the rules read about one course, taken from the normalized tables plus its active cover kinds. */
export interface CourseFacts {
  readonly course: CatalogRow<"courses">;
  readonly authorExists: boolean;
  /** The course's editions by position (ADR-21). */
  readonly editions: readonly CatalogRow<"course_editions">[];
  /** By edition position, then position within the edition. */
  readonly lessons: readonly CatalogRow<"lessons">[];
  readonly youtube: ReadonlyMap<string, string>;
  readonly texts: ReadonlyMap<string, CatalogRow<"catalog_texts">>;
  readonly coverKinds: ReadonlySet<string>;
  readonly inHomeRow: boolean;
}
export interface RuleOptions {
  readonly allowOrphan?: boolean;
  /** Videos whose fresh oEmbed check (publish preflight) failed. */
  readonly videoFailures?: readonly { readonly lessonId: string; readonly status: string }[];
  /** Publish receives page-drawing from the site. Slot length stays in this rule. */
  readonly omitPageText?: boolean;
}

export function courseFacts(tables: CatalogTables, courseId: string, coverKinds: ReadonlySet<string>): CourseFacts | null {
  const course = tables.courses.find((row) => row.id === courseId);
  if (!course) return null;
  const editions = tables.course_editions.filter((edition) => edition.course_id === courseId).sort((a, b) => a.position - b.position);
  const rank = new Map(editions.map((edition, index) => [edition.id, index]));
  const lessons = tables.lessons.filter((lesson) => lesson.course_id === courseId)
    .sort((a, b) => (rank.get(a.edition_id) ?? editions.length) - (rank.get(b.edition_id) ?? editions.length) || a.position - b.position);
  const ids = new Set(lessons.map((lesson) => lesson.id));
  return {
    course,
    authorExists: tables.authors.some((author) => author.id === course.author_id),
    editions,
    lessons,
    youtube: new Map(tables.lesson_videos.filter((video) => video.provider === "youtube" && ids.has(video.lesson_id)).map((video) => [video.lesson_id, video.status])),
    texts: new Map(tables.catalog_texts.filter((row) => row.locale === "en" && ((row.entity_kind === "course" && row.entity_id === courseId) || (row.entity_kind === "lesson" && ids.has(row.entity_id))))
      .map((row) => [`${row.entity_kind}/${row.entity_id}/${row.field}`, row])),
    coverKinds,
    inHomeRow: coursesOnVisibleRows(tables.home_rows, tables.home_row_items).has(courseId),
  };
}

/**
 * `courseFacts` for every course in one pass. Calling `courseFacts` once per course rescans lessons, videos and texts
 * each time, which is minutes on a full catalog.
 */
export function catalogCourseFacts(tables: CatalogTables, covers: ReadonlyMap<string, ReadonlySet<string>>): Map<string, CourseFacts> {
  const authors = new Set(tables.authors.map((author) => author.id));
  const editionsByCourse = new Map<string, CatalogRow<"course_editions">[]>();
  for (const edition of tables.course_editions) {
    const list = editionsByCourse.get(edition.course_id);
    if (list) list.push(edition);
    else editionsByCourse.set(edition.course_id, [edition]);
  }
  for (const editions of editionsByCourse.values()) editions.sort((a, b) => a.position - b.position);
  const lessonsByCourse = new Map<string, CatalogRow<"lessons">[]>();
  const lessonCourse = new Map<string, string>();
  for (const lesson of tables.lessons) {
    lessonCourse.set(lesson.id, lesson.course_id);
    const list = lessonsByCourse.get(lesson.course_id);
    if (list) list.push(lesson);
    else lessonsByCourse.set(lesson.course_id, [lesson]);
  }
  const courseTexts = new Map<string, CatalogRow<"catalog_texts">[]>();
  const lessonTexts = new Map<string, CatalogRow<"catalog_texts">[]>();
  for (const row of tables.catalog_texts) {
    if (row.locale !== "en") continue;
    if (row.entity_kind === "course") {
      const list = courseTexts.get(row.entity_id);
      if (list) list.push(row);
      else courseTexts.set(row.entity_id, [row]);
    } else if (row.entity_kind === "lesson") {
      const list = lessonTexts.get(row.entity_id);
      if (list) list.push(row);
      else lessonTexts.set(row.entity_id, [row]);
    }
  }
  const videosByCourse = new Map<string, [string, string][]>();
  for (const video of tables.lesson_videos) {
    if (video.provider !== "youtube") continue;
    const courseId = lessonCourse.get(video.lesson_id);
    if (courseId === undefined) continue;
    const list = videosByCourse.get(courseId);
    const pair: [string, string] = [video.lesson_id, video.status];
    if (list) list.push(pair);
    else videosByCourse.set(courseId, [pair]);
  }
  const inHome = coursesOnVisibleRows(tables.home_rows, tables.home_row_items);
  const facts = new Map<string, CourseFacts>();
  for (const course of tables.courses) {
    const editions = editionsByCourse.get(course.id) ?? [];
    const rank = new Map(editions.map((edition, index) => [edition.id, index]));
    const lessons = [...(lessonsByCourse.get(course.id) ?? [])].sort((a, b) => (rank.get(a.edition_id) ?? editions.length) - (rank.get(b.edition_id) ?? editions.length) || a.position - b.position);
    const texts = new Map<string, CatalogRow<"catalog_texts">>();
    for (const row of courseTexts.get(course.id) ?? []) texts.set(`${row.entity_kind}/${row.entity_id}/${row.field}`, row);
    for (const lesson of lessons) {
      for (const row of lessonTexts.get(lesson.id) ?? []) texts.set(`${row.entity_kind}/${row.entity_id}/${row.field}`, row);
    }
    facts.set(course.id, {
      course,
      authorExists: authors.has(course.author_id),
      editions,
      lessons,
      youtube: new Map(videosByCourse.get(course.id) ?? []),
      texts,
      coverKinds: covers.get(course.id) ?? new Set(),
      inHomeRow: inHome.has(course.id),
    });
  }
  return facts;
}

interface Rule {
  readonly rule: DeclaredRule;
  readonly targets: readonly RuleTarget[];
  check(facts: CourseFacts, options: RuleOptions): PreconditionFailure[];
}
const courseRef = (facts: CourseFacts) => `course:${facts.course.id}`;
const visible = (facts: CourseFacts) => facts.lessons.filter((lesson) => lesson.visible);
const reviewCourseFields = Object.entries(TEXT_FIELDS.course).flatMap(([name, spec]) => (spec.review ? [name] : []));
const publishCourseFields = Object.entries(TEXT_FIELDS.course).flatMap(([name, spec]) => (spec.publish ? [name] : []));
const reviewLessonFields = Object.entries(TEXT_FIELDS.lesson).flatMap(([name, spec]) => (spec.review ? [name] : []));
const publishLessonFields = Object.entries(TEXT_FIELDS.lesson).flatMap(([name, spec]) => (spec.publish ? [name] : []));

/** Course and visible-lesson texts. Hidden lessons are not part of the offer the page draws. */
function offeredTexts(facts: CourseFacts) {
  return [...facts.texts.values()].filter((row) => row.entity_kind === "course" || visible(facts).some((lesson) => lesson.id === row.entity_id));
}

/** Text slots a target needs: the course fields, then each visible lesson's. */
function slots(facts: CourseFacts, publish: boolean) {
  const courseFields = publish ? publishCourseFields : reviewCourseFields;
  const lessonFields = publish ? publishLessonFields : reviewLessonFields;
  const course = courseFields.map((field) => ({ kind: "course", id: facts.course.id, field }));
  return lessonFields.length === 0 ? course : [...course, ...visible(facts).flatMap((row) => lessonFields.map((field) => ({ kind: "lesson", id: row.id, field })))];
}

const AUTHOR_EXISTS = declareRule("author.exists", "The course's author exists.");
export const LESSONS_VISIBLE = declareRule("lessons.visible", "A course has at least one visible lesson.");
const EDITIONS_EXISTS = declareRule("editions.exists", "A course has an edition.");
const EDITIONS_CONTIGUOUS = declareRule("editions.contiguous", "Edition positions are 1..N.");
const EDITIONS_LESSONS = declareRule("editions.lessons", "Every edition has a lesson.");
const LESSONS_EDITION = declareRule("lessons.edition", "A lesson's edition belongs to its course.");
const LESSONS_CONTIGUOUS = declareRule("lessons.contiguous", "Lesson positions in an edition are 1..N.");
const EDITIONS_AMBIGUOUS = declareRule("editions.ambiguous", "Two editions of one year need a distinct variant (D-034).");
const VIDEOS_OK = declareRule("videos.ok", "Every visible lesson has a YouTube video that is ok.");
const TEXTS_REQUIRED = declareRule("texts.required", "Every required text slot is filled.");
const TEXTS_VALID = declareRule("texts.valid", "Every text fits its slot.");
const TEXTS_APPROVED = declareRule("texts.approved", "Every published text is approved at its current text.");
export const RIGHTS_FIELDS = declareRule("rights.fields", "A course has a license, source and canonical URL.");
export const RIGHTS_STATUS = declareRule("rights.status", "A published course has cleared or accepted-risk rights.");

const COURSE_AREA = declareRule("area.required", "Every published course has one area (INV-H1, D-017).");
export function publishedAreaFailures(courseId: string, areaId: unknown): PreconditionFailure[] {
  return typeof areaId === "string" && areaId.length > 0 ? [] : [COURSE_AREA.fail(`course:${courseId}`, "A published course needs an area.")];
}
export const RULES: readonly Rule[] = [
  { rule: COURSE_AREA, targets: [courseStatus.published], check: (facts) => publishedAreaFailures(facts.course.id, facts.course.area_id) },
  { rule: AUTHOR_EXISTS, targets: [courseStatus.review, courseStatus.published], check: (facts) => (facts.authorExists ? [] : [AUTHOR_EXISTS.fail(courseRef(facts), `Author ${facts.course.author_id} does not exist.`)]) },
  { rule: LESSONS_VISIBLE, targets: [courseStatus.review, courseStatus.published], check: (facts) => (visible(facts).length > 0 ? [] : [LESSONS_VISIBLE.fail(courseRef(facts), "The course has no visible lesson.")]) },
  { rule: EDITIONS_EXISTS, targets: [courseStatus.review, courseStatus.published], check: (facts) => (facts.editions.length > 0 ? [] : [EDITIONS_EXISTS.fail(courseRef(facts), "The course has no edition.")]) },
  {
    rule: EDITIONS_CONTIGUOUS, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => (facts.editions.every((edition, index) => edition.position === index + 1) ? [] : [EDITIONS_CONTIGUOUS.fail(courseRef(facts), `Edition positions are not 1..N (${facts.editions.map((edition) => edition.position).join(", ")}).`)]),
  },
  {
    rule: EDITIONS_LESSONS, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => facts.editions.filter((edition) => !facts.lessons.some((lesson) => lesson.edition_id === edition.id))
      .map((edition) => EDITIONS_LESSONS.fail(`edition:${edition.id}`, `Edition ${edition.slug} has no lesson.`)),
  },
  {
    rule: LESSONS_EDITION, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => facts.lessons.filter((lesson) => !facts.editions.some((edition) => edition.id === lesson.edition_id))
      .map((lesson) => LESSONS_EDITION.fail(`lesson:${lesson.id}`, `The lesson's edition ${lesson.edition_id} is not an edition of this course.`)),
  },
  {
    rule: LESSONS_CONTIGUOUS, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => facts.editions.flatMap((edition) => {
      const positions = facts.lessons.filter((lesson) => lesson.edition_id === edition.id).map((lesson) => lesson.position);
      return positions.every((position, index) => position === index + 1) ? [] : [LESSONS_CONTIGUOUS.fail(`edition:${edition.id}`, `Lesson positions in edition ${edition.slug} are not 1..N.`)];
    }),
  },
  {
    rule: EDITIONS_AMBIGUOUS, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => indistinctEditions(facts.editions.map((edition) => ({
      id: edition.id, year: edition.year, variant: columnsToVariant(edition.variant_kind, edition.variant_label),
    }))).flatMap((clash) => clash.ids.map((id) => {
      const edition = facts.editions.find((row) => row.id === id);
      return EDITIONS_AMBIGUOUS.fail(`edition:${id}`, `Edition ${edition?.slug ?? id} shares the year ${String(clash.year)} with another edition and has no distinct variant.`);
    })),
  },
  {
    rule: VIDEOS_OK, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => visible(facts).flatMap((lesson) => {
      const status = facts.youtube.get(lesson.id);
      return status === "ok" ? [] : [VIDEOS_OK.fail(`lesson:${lesson.id}`, status === undefined ? "The lesson has no YouTube video." : `The YouTube video is ${status}.`)];
    }),
  },
  {
    rule: VIDEOS_FRESH, targets: [courseStatus.published],
    check: (_facts, options) => lessonVideoCheckAnswer(options.videoFailures ?? []),
  },
  {
    rule: TEXTS_REQUIRED, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => {
      const failed: PreconditionFailure[] = [];
      const id = facts.course.id;
      for (const field of reviewCourseFields) {
        if (!facts.texts.has(`course/${id}/${field}`)) failed.push(TEXTS_REQUIRED.fail(`course:${id}`, `${field} is missing.`));
      }
      if (reviewLessonFields.length === 0) return failed;
      for (const lesson of facts.lessons) {
        if (!lesson.visible) continue;
        for (const field of reviewLessonFields) {
          if (!facts.texts.has(`lesson/${lesson.id}/${field}`)) failed.push(TEXTS_REQUIRED.fail(`lesson:${lesson.id}`, `${field} is missing.`));
        }
      }
      return failed;
    },
  },
  {
    // Slot length stays here. Characters the page cannot draw are the site's answer, received on publish.
    rule: TEXTS_VALID, targets: [courseStatus.review, courseStatus.published],
    check: (facts, options) => offeredTexts(facts).flatMap((row) => textIssues(row.entity_kind, row.field, row.text)
      .filter((issue) => !(options.omitPageText === true && issue.rule === "texts.charset"))
      .map((issue) => ({ rule: issue.rule, entity: `${row.entity_kind}:${row.entity_id}`, message: issue.message }))),
  },
  {
    rule: TEXTS_APPROVED, targets: [courseStatus.published],
    check: (facts) => slots(facts, true).flatMap((slot) => {
      const row = facts.texts.get(`${slot.kind}/${slot.id}/${slot.field}`);
      if (!row) return [];
      return row.status === "approved" && row.approved_sha256 === sha256Hex(row.text) ? [] : [TEXTS_APPROVED.fail(`${slot.kind}:${slot.id}`, `${slot.field} is not approved at its current text.`)];
    }),
  },
  {
    rule: COVERS_ACTIVE, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => figurePresenceAnswer(facts.course.id, facts.coverKinds),
  },
  {
    rule: RIGHTS_FIELDS, targets: [courseStatus.review, courseStatus.published],
    check: (facts) => (["license_code", "source_id", "canonical_url"] as const).filter((column) => facts.course[column] === null)
      .map((column) => RIGHTS_FIELDS.fail(courseRef(facts), `${column} is not set.`)),
  },
  {
    rule: RIGHTS_STATUS, targets: [courseStatus.published],
    check: (facts) => ((PUBLISHABLE_RIGHTS as readonly string[]).includes(facts.course.rights_status) ? [] : [RIGHTS_STATUS.fail(courseRef(facts), `Rights are ${facts.course.rights_status}; publishing needs cleared or accepted-risk.`)]),
  },
  {
    rule: HOME_ROW, targets: [courseStatus.published],
    check: (facts, options) => showcaseRowAnswer(facts.course.id, facts.inHomeRow, options.allowOrphan === true),
  },
];

/** What a published course keeps while it is edited (PATCH /courses/:id): its rights fields and status. Unpublish first. */
export function publishedKeepsRights(courseId: string, merged: Readonly<Record<string, unknown>>): PreconditionFailure[] {
  const failed = (["license_code", "source_id", "canonical_url"] as const).filter((column) => merged[column] === null)
    .map((column) => RIGHTS_FIELDS.fail(`course:${courseId}`, `A published course keeps its ${column}.`));
  if (!(PUBLISHABLE_RIGHTS as readonly string[]).includes(String(merged.rights_status))) failed.push(RIGHTS_STATUS.fail(`course:${courseId}`, "A published course keeps cleared or accepted-risk rights; unpublish it first."));
  return failed;
}

/** What a published course keeps when its cover inputs change (PATCH /courses/:id, a bundle apply): every required active cover. */
export function publishedKeepsCovers(courseId: string, covers: ReadonlySet<string> | undefined): PreconditionFailure[] {
  return REQUIRED_COVERS.filter((kind) => !covers?.has(kind)).map((kind) => COVERS_ACTIVE.fail(`course:${courseId}`, `A published course keeps its active ${kind} cover; unpublish it first.`));
}

const reviewRules = RULES.filter((rule) => rule.targets.includes(courseStatus.review));
const publishedRules = RULES.filter((rule) => rule.targets.includes(courseStatus.published));

/** Every unmet precondition for `target`, all rules evaluated (the 412 lists the complete set, never only the first). */
export function evaluateRules(target: RuleTarget, facts: CourseFacts, options: RuleOptions = {}): (PreconditionFailure & { readonly owner?: string })[] {
  const rules = target === courseStatus.review ? reviewRules : publishedRules;
  const asking = target === courseStatus.published;
  const ruleOptions = asking ? { ...options, omitPageText: true } : options;
  const failed: (PreconditionFailure & { readonly owner?: string })[] = [];
  for (const rule of rules) {
    const found = rule.check(facts, ruleOptions);
    if (found.length > 0) failed.push(...found);
  }
  if (asking) {
    failed.push(...sitePageTextAnswer(offeredTexts(facts).map((row) => ({ kind: row.entity_kind, id: row.entity_id, field: row.field, text: row.text }))));
  }
  return failed;
}

