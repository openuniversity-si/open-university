import { z } from "zod";
import { LIMITS } from "../../catalog/domain/schema/fields.ts";
import type { CuratedV1 } from "./curated.ts";
import { EXTENT } from "../../kernel/extent.ts";

// Generated texts stay unapproved. A separate reviewer is the only actor that may approve them (D-019).

export const GENERATOR_ACTOR = "factory-text-generator@1";
export const REVIEWER_ACTOR = "factory-text-reviewer@1";

export interface FactoryTextRecord {
  readonly entityKind: "course" | "lesson";
  readonly entityId: string;
  readonly field: "description" | "displayTitle";
  readonly text: string;
  readonly language: string;
  readonly approved: boolean;
  readonly approvedBy: string | null;
  readonly approvedAt: string | null;
  readonly flags: readonly ("placeholder-title")[];
  readonly actor: typeof GENERATOR_ACTOR;
}

const factoryTextSchema = z.strictObject({
  entityKind: z.enum(["course", "lesson"]),
  entityId: z.string().min(EXTENT.one).max(LIMITS.factoryEntityId),
  field: z.enum(["description", "displayTitle"]),
  text: z.string().min(EXTENT.one).max(LIMITS.text),
  language: z.string().trim().min(EXTENT.one).max(LIMITS.languageLabel),
  approved: z.boolean(),
  approvedBy: z.string().min(EXTENT.one).nullable(),
  approvedAt: z.string().min(EXTENT.one).nullable(),
  flags: z.array(z.enum(["placeholder-title"])),
  actor: z.literal(GENERATOR_ACTOR),
}).superRefine((text, context) => {
  if (text.approvedBy === GENERATOR_ACTOR) {
    context.addIssue({ code: "custom", path: ["approvedBy"], message: "The generator cannot approve a text." });
  }
  if (text.approved) {
    if (text.approvedBy !== REVIEWER_ACTOR) context.addIssue({ code: "custom", path: ["approvedBy"], message: "Only the separate reviewer can approve a text." });
    if (text.approvedAt === null) context.addIssue({ code: "custom", path: ["approvedAt"], message: "Approval names its time." });
    if (text.flags.includes("placeholder-title")) context.addIssue({ code: "custom", path: ["flags"], message: "A placeholder title is not approved." });
  } else if (text.approvedBy !== null || text.approvedAt !== null) {
    context.addIssue({ code: "custom", path: ["approved"], message: "An unapproved text has no approver." });
  }
});

export interface TextIssue { readonly name: string; readonly message: string }

/** Every problem, named by index and field (`0.approvedBy`). */
export function parseFactoryTexts(input: unknown): { readonly ok: true; readonly texts: readonly FactoryTextRecord[] } | { readonly ok: false; readonly issues: readonly TextIssue[] } {
  if (!Array.isArray(input)) return { ok: false, issues: [{ name: "texts", message: "texts: expected a list" }] };
  const issues: TextIssue[] = [];
  const texts: FactoryTextRecord[] = [];
  input.forEach((item, index) => {
    const parsed = factoryTextSchema.safeParse(item);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const name = [String(index), ...issue.path.map((part) => String(part))].join(".");
        issues.push({ name, message: `${name}: ${issue.message}` });
      }
      return;
    }
    texts.push(parsed.data);
  });
  return issues.length === 0 ? { ok: true, texts } : { ok: false, issues };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** `Aula de 22/10/2026` is a date placeholder. The generator keeps it and flags it. */
export function isPlaceholderTitle(title: string, noun: string): boolean {
  const nounText = noun.trim();
  if (nounText === "") return false;
  return new RegExp(`^${escapeRegExp(nounText)} de \\d{2}/\\d{2}/\\d{4}$`).test(title.trim());
}

export interface TextCourse {
  readonly id: string;
  readonly title: string;
  readonly lessons: readonly { readonly youtubeId: string; readonly title: string }[];
}

/** One generator. Language and the lesson noun are parameters. Every text leaves with approved false. */
export function generateTexts(courses: readonly TextCourse[], options: { readonly language: string; readonly noun: string }): FactoryTextRecord[] {
  const language = options.language.trim();
  const noun = options.noun.trim();
  const texts: FactoryTextRecord[] = [];
  for (const course of courses) {
    const lessons = course.lessons.filter((lesson) => lesson.title.trim() !== "");
    texts.push({
      entityKind: "course", entityId: course.id, field: "description", text: `${course.title} (${String(lessons.length)} ${noun}).`,
      language, approved: false, approvedBy: null, approvedAt: null, flags: [], actor: GENERATOR_ACTOR,
    });
    for (const lesson of lessons) {
      const title = lesson.title.trim();
      texts.push({
        entityKind: "lesson", entityId: `${course.id}/${lesson.youtubeId}`, field: "displayTitle", text: title,
        language, approved: false, approvedBy: null, approvedAt: null,
        flags: isPlaceholderTitle(title, noun) ? ["placeholder-title"] : [], actor: GENERATOR_ACTOR,
      });
    }
  }
  return texts;
}

/** Courses without an id or a title are listed and skipped. The label is the id or the title, never a playlist id (D-032). */
export function textsFromCurated(curated: CuratedV1, options: { readonly language: string; readonly noun: string }): { readonly texts: readonly FactoryTextRecord[]; readonly skipped: readonly string[] } {
  const skipped: string[] = [];
  const courses: TextCourse[] = [];
  for (const course of curated.courses) {
    if (course.decision === "exclude") continue;
    if (course.id === undefined || course.title === undefined) {
      skipped.push(course.id ?? course.title ?? "unnamed");
      continue;
    }
    courses.push({
      id: course.id, title: course.title,
      lessons: (course.lessons ?? []).map((lesson) => ({ youtubeId: lesson.youtubeId, title: lesson.originalTitle })),
    });
  }
  return { texts: generateTexts(courses, options), skipped };
}

/** Stamps approval with the reviewer. A placeholder title stays unapproved. */
export function reviewTexts(texts: readonly FactoryTextRecord[], reviewedAt: string): FactoryTextRecord[] {
  return texts.map((text) => text.flags.includes("placeholder-title")
    ? { ...text, approved: false, approvedBy: null, approvedAt: null }
    : { ...text, approved: true, approvedBy: REVIEWER_ACTOR, approvedAt: reviewedAt });
}
