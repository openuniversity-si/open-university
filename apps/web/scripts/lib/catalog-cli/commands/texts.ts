import { textsPut, type TextsPut } from "../../../../src/catalog/domain/contracts.ts";
import { TEXT_FIELDS, textIssues } from "../../../../src/catalog/domain/fields.ts";
import { writeFileSync } from "node:fs";
import { listOption, positional, requireOption, stringOption } from "../args.ts";
import { issueList } from "../client.ts";
import { parseJsonFile, type CommandSpec, type Context } from "../context.ts";
import { ApiError, CliError, EXIT, UsageError } from "../errors.ts";
import { chars, shortSha, table, type CourseDetail } from "../render.ts";
import { getCourse, listAllCourses } from "./shared.ts";


interface ApproveItem { entityKind: "course" | "lesson"; entityId: string; field: string; sha256: string }

/** A course's texts and its lessons', as `entity.field` → current text and hashes (one GET /courses/:id). */
export function courseTexts(detail: CourseDetail): { kind: "course" | "lesson"; id: string; field: string; text: string; sha256: string; approvedSha256: string | null; status: string }[] {
  const entries = (kind: "course" | "lesson", id: string, texts: CourseDetail["texts"]) => Object.entries(texts).map(([field, entry]) => ({ kind, id, field, text: entry.text, sha256: entry.sha256, approvedSha256: entry.approvedSha256, status: entry.status }));
  return [...entries("course", detail.course.id, detail.texts), ...detail.lessons.flatMap((lesson) => entries("lesson", lesson.id, lesson.texts))];
}

/** `--fields a,b`: a bare name matches that field everywhere (course and lessons); `lesson-12.displayTitle` one entity. */
function selected(fields: readonly string[] | undefined, id: string, field: string): boolean {
  return fields === undefined || fields.includes(field) || fields.includes(`${id}.${field}`);
}

/**
 * A texts.json for PUT /texts, checked before sending: the same zod schema as the API, every item an entity of this course
 * (the course, its lessons, its author), and every text within its slot and the Inter subset (fields.ts). All problems
 * are listed with their item path; nothing is sent while one remains.
 */
export function checkTextsFile(value: unknown, detail: CourseDetail): TextsPut {
  const parsed = textsPut.safeParse(value);
  if (!parsed.success) throw new UsageError(`texts.json does not match PUT /texts: ${issueList(parsed.error.issues)}`);
  const lessons = new Set(detail.lessons.map((lesson) => lesson.id));
  const problems: string[] = [];
  parsed.data.forEach((item, index) => {
    const belongs = (item.entityKind === "course" && item.entityId === detail.course.id) || (item.entityKind === "lesson" && lessons.has(item.entityId)) || (item.entityKind === "author" && item.entityId === detail.course.authorId);
    if (!belongs) problems.push(`[${String(index)}] ${item.entityKind}:${item.entityId} is not ${detail.course.id}, one of its lessons or its author`);
    for (const issue of textIssues(item.entityKind, item.field, item.text)) problems.push(`[${String(index)}] ${issue.rule}: ${issue.message}`);
  });
  if (problems.length) throw new UsageError(`texts.json has ${String(problems.length)} problem(s); nothing was sent:\n  ${problems.join("\n  ")}`);
  return parsed.data;
}

export const textCommands: CommandSpec[] = [
  {
    name: "texts get", usage: "texts get <course> | texts get <kind:id>", summary: "fields with status, hash, limit and length (a course includes its lessons)",
    options: {}, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "GET /texts"],
    async run(context) {
      const target = positional(context.args, 0, "course");
      if (target.includes(":")) {
        const result = await context.client.call("GET /texts", { query: { entity: target } });
        context.out.lines(table(["field", "status", "chars", "limit", "sha256", "issues"], result.data.fields.map((field) => [
          field.field, field.status ?? "missing", field.text === null ? "-" : String(chars(field.text)), String(field.maxChars), shortSha(field.sha256), field.issues.map((issue) => issue.rule).join(",") || "-",
        ])));
        context.out.result(result.envelope);
        return;
      }
      const result = await context.client.call("GET /courses/:id", { params: { id: target } });
      context.out.lines(table(["entity", "field", "status", "chars", "limit", "sha256", "issues"], courseTexts(result.data).map((entry) => [
        `${entry.kind}:${entry.id}`, entry.field, entry.approvedSha256 === entry.sha256 ? "approved" : entry.status, String(chars(entry.text)),
        String((TEXT_FIELDS[entry.kind] as Record<string, { maxChars: number }>)[entry.field]?.maxChars ?? "-"), shortSha(entry.sha256),
        textIssues(entry.kind, entry.field, entry.text).map((issue) => issue.rule).join(",") || "-",
      ])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "texts put", usage: "texts put <course> --file texts.json", summary: "write texts as draft, all or nothing (validated locally first)",
    options: { file: { type: "string", required: true, help: "the PUT /texts array", value: "<path>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "PUT /texts"],
    async run(context) {
      const id = positional(context.args, 0, "course");
      const file = requireOption(context.args, "file");
      const raw = parseJsonFile(context, file);
      const items = checkTextsFile(raw, await getCourse(context, id));
      await context.confirm(`Write ${String(items.length)} text(s) of ${id} as draft`);
      const result = await context.client.call("PUT /texts", { body: items });
      context.out.lines(table(["entity", "field", "status", "sha256", "changed"], result.data.items.map((item) => [item.entity, item.field, item.status, shortSha(item.sha256), item.changed ? "yes" : "no"])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "texts revoke", usage: "texts revoke <course> --fields a,b", summary: "withdraw approvals (the texts go back to draft)",
    options: { fields: { type: "string", required: true, help: "names or entity.field", value: "<a,b>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "POST /texts/revoke"],
    async run(context) {
      const id = positional(context.args, 0, "course");
      const fields = listOption(context.args, "fields");
      const items = courseTexts(await getCourse(context, id)).filter((entry) => selected(fields, entry.id, entry.field)).map((entry) => ({ entityKind: entry.kind, entityId: entry.id, field: entry.field }));
      if (items.length === 0) throw new UsageError(`No text of ${id} matches --fields.`);
      await context.confirm(`Revoke ${String(items.length)} approval(s) of ${id}`);
      const result = await context.client.call("POST /texts/revoke", { body: { items } });
      context.out.line(`Revoked ${String(result.data.items.length)} approval(s).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "approve", usage: "approve <course> --by \"Daniel\" [--fields a,b]", summary: "approve exactly the hashes just read (409 if a text changed: nothing approved)",
    options: { by: { type: "string", required: true, help: "who approves (recorded)", value: "<name>" }, fields: { type: "string", help: "only these names or entity.field", value: "<a,b>" } },
    positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "POST /texts/approve"],
    async run(context) {
      const id = positional(context.args, 0, "course");
      const fields = listOption(context.args, "fields");
      const by = requireOption(context.args, "by");
      const read = courseTexts(await getCourse(context, id)).filter((entry) => selected(fields, entry.id, entry.field));
      const pending = read.filter((entry) => entry.approvedSha256 !== entry.sha256);
      if (pending.length === 0) { context.out.line(`Nothing to approve in ${id}${fields ? " for --fields" : ""}: every text is approved at its current hash.`); return; }
      context.out.lines([`Approve as "${by}" exactly these ${String(pending.length)} text(s):`, ...pending.map((entry) => `  ${entry.kind}:${entry.id}.${entry.field} ${shortSha(entry.sha256)} «${Array.from(entry.text).slice(0, 72).join("")}${chars(entry.text) > 72 ? "…" : ""}»`)]);
      await context.confirm(`Approve ${String(pending.length)} text(s) of ${id}`, true);
      const items: ApproveItem[] = pending.map((entry) => ({ entityKind: entry.kind, entityId: entry.id, field: entry.field, sha256: entry.sha256 }));
      try {
        const result = await context.client.call("POST /texts/approve", { body: { items, approvedBy: by } });
        context.out.line(`Approved ${String(result.data.items.length)} text(s) as ${result.data.approvedBy}.`);
        context.out.result(result.envelope);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        const now = new Map(courseTexts(await getCourse(context, id)).map((entry) => [`${entry.id}.${entry.field}`, entry.sha256]));
        const changed = pending.filter((entry) => now.get(`${entry.id}.${entry.field}`) !== entry.sha256).map((entry) => `${entry.kind}:${entry.id}.${entry.field}`);
        throw new CliError(`Nothing was approved: ${changed.length ? `changed since you read them: ${changed.join(", ")}` : error.message}. Run review again. (requestId ${error.requestId})`, EXIT.conflict);
      }
    },
  },
  {
    name: "draft-copy", usage: "draft-copy <course> [--out pack.json]", summary: "context pack for the session to draft texts (no LLM API is called; then texts put)",
    options: { out: { type: "string", help: "write the pack here instead of stdout", value: "<path>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "GET /courses", "GET /texts"],
    async run(context) {
      const id = positional(context.args, 0, "course");
      const pack = await draftPack(context, id);
      const out = stringOption(context.args, "out");
      const text = `${JSON.stringify(pack, null, 2)}\n`;
      if (out !== undefined) {
        writeFileSync(out, text);
        context.out.line(`Wrote the draft-copy pack of ${id} to ${out}: fill template[].text, save it as texts.json, then tower-catalog texts put ${id} --file texts.json.`);
      } else if (context.out.json) context.out.result(pack);
      else context.out.line(text.trimEnd());
    },
  },
];

const EXAMPLE_COURSES = 2;

/** Plan §4.3: title, lessons, slot limits and approved examples of the same fields; the template is the PUT /texts body. */
export async function draftPack(context: Context, id: string) {
  const detail = await getCourse(context, id);
  const published = (await listAllCourses(context, { status: "published" })).filter((course) => course.id !== id).slice(0, EXAMPLE_COURSES);
  const examples: { entity: string; field: string; text: string }[] = [];
  for (const course of published) {
    const texts = (await context.client.call("GET /texts", { query: { entity: `course:${course.id}` } })).data;
    for (const field of texts.fields) if (field.text !== null && field.status === "approved") examples.push({ entity: texts.entity, field: field.field, text: field.text });
  }
  const slot = (kind: "course" | "lesson") => Object.fromEntries(Object.entries(TEXT_FIELDS[kind]).map(([field, spec]) => [field, { maxChars: spec.maxChars, requiredForReview: spec.review, requiredForPublish: spec.publish }]));
  const item = (entityKind: "course" | "lesson", entityId: string, field: string) => ({ entityKind, entityId, field, text: "", source: "llm" as const, sourceRef: "tower-catalog draft-copy", confidence: "medium" as const });
  return {
    course: { id: detail.course.id, slug: detail.course.slug, title: detail.course.title, lessonNoun: detail.course.lessonNoun, languageLabel: detail.course.languageLabel, authorId: detail.course.authorId, status: detail.course.status },
    lessons: detail.lessons.map((lesson) => ({ id: lesson.id, position: lesson.position, youtubeTitle: lesson.youtubeTitle, durationSeconds: lesson.durationSeconds, displayTitle: lesson.texts.displayTitle?.text ?? null })),
    current: Object.fromEntries(Object.entries(detail.texts).map(([field, entry]) => [field, entry.text])),
    slots: { course: slot("course"), lesson: slot("lesson") },
    rules: [
      "Each text fits its slot's maxChars (code points) and uses only characters of the Inter subset; texts put checks both before sending.",
      "Nothing drafted is approved: texts put writes draft; Daniel reviews and approves with review + approve.",
      "English, no invented facts: use only the titles above, the playlist and what the session can verify.",
    ],
    examples,
    template: [
      ...Object.entries(TEXT_FIELDS.course).filter(([, spec]) => spec.review).map(([field]) => item("course", detail.course.id, field)),
      ...detail.lessons.flatMap((lesson) => Object.entries(TEXT_FIELDS.lesson).filter(([, spec]) => spec.review).map(([field]) => item("lesson", lesson.id, field))),
    ],
  };
}
