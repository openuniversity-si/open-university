import type { PreconditionFailure } from "../../../kernel/errors.ts";
import { undrawablePageText } from "../../../site/domain/page-characters.ts";
import { REQUIRED_COVERS } from "../cover-source.ts";
import { declareRule } from "./registry.ts";

/**
 * Answers publish receives. Each function decides one fact and names its owner.
 * Publish records the answer. It does not decide the fact again.
 */
export const VIDEOS_FRESH = declareRule("videos.fresh", "The publish-time oEmbed check passed.");
export const COVERS_ACTIVE = declareRule("covers.active", "A course has every required active cover.");
export const HOME_ROW = declareRule("home.row", "A published course is in a visible Home row.");

const LESSON = "lesson";
const FIGURE = "figure";
const SHOWCASE = "showcase";
const SITE = "site";

export type FactOwner = typeof LESSON | typeof FIGURE | typeof SHOWCASE | typeof SITE;
export type OwnedFailure = PreconditionFailure & { readonly owner: FactOwner };

export interface VideoCheckFailure { readonly lessonId: string; readonly status: string }
export interface PageTextSlot { readonly kind: string; readonly id: string; readonly field: string; readonly text: string }

/** The lesson says whether the fresh video check still serves. */
export function lessonVideoCheckAnswer(failures: readonly VideoCheckFailure[]): OwnedFailure[] {
  return failures.map((failure) => ({
    ...VIDEOS_FRESH.fail(`lesson:${failure.lessonId}`, `The fresh oEmbed check says ${failure.status}.`),
    owner: LESSON,
  }));
}

/** The figure says whether every required picture is present. */
export function figurePresenceAnswer(courseId: string, coverKinds: ReadonlySet<string>): OwnedFailure[] {
  return REQUIRED_COVERS.filter((kind) => !coverKinds.has(kind)).map((kind) => ({
    ...COVERS_ACTIVE.fail(`course:${courseId}`, `No active ${kind} cover.`),
    owner: FIGURE,
  }));
}

/** The showcase says whether the course is on a visible Home row, or an orphan was marked on purpose. */
export function showcaseRowAnswer(courseId: string, inVisibleRow: boolean, allowOrphan: boolean): OwnedFailure[] {
  if (inVisibleRow || allowOrphan) return [];
  return [{
    ...HOME_ROW.fail(`course:${courseId}`, "The course is in no visible Home row (pass allowOrphan to publish it anyway)."),
    owner: SHOWCASE,
  }];
}

/** The site says whether the page can draw the text. Slot length stays with the offer. */
export function sitePageTextAnswer(slots: readonly PageTextSlot[]): OwnedFailure[] {
  const failed: OwnedFailure[] = [];
  for (const slot of slots) {
    const message = undrawablePageText(slot.kind, slot.field, slot.text);
    if (message === null) continue;
    failed.push({ rule: "texts.charset", entity: `${slot.kind}:${slot.id}`, message, owner: SITE });
  }
  return failed;
}
