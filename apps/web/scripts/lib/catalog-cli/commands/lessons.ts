import type { z } from "zod";
import { authorCreate, authorPatch, lessonCreate, lessonPatch } from "../../../../src/catalog/domain/contracts.ts";
import { fieldOptions, fieldValues, flag, intOption, listOption, positional, stringOption } from "../args.ts";
import { parseJsonFile, type CommandSpec, type Context } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";
import type { SlugBatchPlan, SlugPlan } from "../../../../src/catalog/domain/lesson-slug.ts";
import { LEGACY_LESSON_IDS, reslugCourse, slugCourseFromTables, type Reslug } from "../../../../src/catalog/domain/slug-course.ts";
import { table } from "../render.ts";
import type { AuthorRow } from "../responses.ts";
import { editionOf, resolveCourseId } from "./editions.ts";
import { bytesQuery, getCourse, listAllCourses, patchFields, patchWithRetry } from "./shared.ts";


const fileOption = { file: { type: "string", help: "JSON object of fields", value: "<path>" } } as const;
const editionOption = { edition: { type: "string", help: "edition slug or id (default: the course's only edition)", value: "<slug>" } } as const;

/**
 * The complete new order for `PUT …/lessons/order`: every current lesson exactly once. Problems are listed all at once
 * (missing, unknown, repeated) and nothing is sent.
 */
export function checkPermutation(current: readonly string[], proposed: readonly string[]): void {
  const seen = new Set<string>();
  const repeated = proposed.filter((id) => (seen.has(id) ? true : (seen.add(id), false)));
  const missing = current.filter((id) => !seen.has(id));
  const unknown = [...seen].filter((id) => !current.includes(id));
  const problems = [
    ...(missing.length ? [`missing: ${missing.join(", ")}`] : []), ...(unknown.length ? [`not in this course: ${unknown.join(", ")}`] : []),
    ...(repeated.length ? [`repeated: ${[...new Set(repeated)].join(", ")}`] : []),
  ];
  if (problems.length) throw new UsageError(`Not a permutation of the edition's ${String(current.length)} lessons (${problems.join("; ")}).`);
}

/** `--move <lesson> --to <position>` as the full permutation it means. */
export function moveLesson(current: readonly string[], lesson: string, to: number): string[] {
  if (!current.includes(lesson)) throw new UsageError(`${lesson} is not a lesson of this course.`);
  if (to < 1 || to > current.length) throw new UsageError(`--to must be 1–${String(current.length)}.`);
  const rest = current.filter((id) => id !== lesson);
  return [...rest.slice(0, to - 1), lesson, ...rest.slice(to - 1)];
}

async function lessonOf(context: Context, courseId: string, lessonId: string) {
  const detail = await getCourse(context, courseId);
  const lesson = detail.lessons.find((entry) => entry.id === lessonId);
  if (!lesson) throw new UsageError(`${lessonId} is not a lesson of ${courseId}.`);
  return lesson;
}

/** The course holding `lessonId`, for `lesson set <lesson>` without the course (one GET per course until found). */
async function courseOfLesson(context: Context, lessonId: string): Promise<string> {
  for (const course of await listAllCourses(context)) {
    if ((await getCourse(context, course.id)).lessons.some((lesson) => lesson.id === lessonId)) return course.id;
  }
  throw new UsageError(`No lesson ${lessonId} in any course.`);
}

/** A slug change's redirects, one per line (live with the next release). */
function slugLines(plan: SlugPlan | null | undefined): string[] {
  if (!plan) return [];
  return [
    `  redirect ${plan.created.from} → ${plan.created.to} (308 from the next release)`,
    ...plan.flattened.map((change) => `  flattened ${change.from} → ${change.after} (was → ${change.before})`),
    ...plan.removed.map((redirect) => `  removed ${redirect.from} → ${redirect.to} (back to an earlier slug)`),
  ];
}

/** A batch plan's redirects, counted for one line. */
function batchSummary(plan: SlugBatchPlan): string {
  return `${String(plan.changes.length)} slug(s), ${String(plan.created.length)} redirect(s) created, ${String(plan.flattened.length)} flattened, ${String(plan.removed.length)} removed, ${String(plan.reused.length)} old path(s) reused`;
}

async function authorOf(context: Context, id: string): Promise<AuthorRow> {
  const authors = (await context.client.call("GET /authors")).data.authors;
  const author = authors.find((entry) => entry.id === id);
  if (!author) throw new UsageError(`No author ${id}.`);
  return author;
}

export const lessonCommands: CommandSpec[] = [
  {
    name: "lesson create", usage: "lesson create <course> --youtube-id <id> --duration-seconds <n> [--edition <slug>] [--part lectures|labs] [--slug …] [--display-title …] [--position n] [--kind …]",
    summary: "add a lesson to an edition (its YouTube video is checked with oEmbed by the API)", options: { ...fieldOptions(lessonCreate, ["editionId"]), ...editionOption },
    positionals: { min: 1, max: 1 }, routes: ["GET /courses", "GET /courses/:id", "POST /courses/:id/lessons"],
    async run(context) {
      const id = await resolveCourseId(context, positional(context.args, 0, "course"));
      const edition = editionOf(await getCourse(context, id), stringOption(context.args, "edition"));
      const body = { ...fieldValues(lessonCreate, context.args, ["editionId"]), editionId: edition.id } as z.input<typeof lessonCreate>;
      await context.confirm(`Add lesson ${body.youtubeId} to ${id}`);
      const result = await context.client.call("POST /courses/:id/lessons", { params: { id }, body });
      context.out.line(`Created ${result.data.lesson.id} at position ${String(result.data.lesson.position)} of ${edition.slug} (${result.data.lesson.slug}, ${result.data.lesson.part}); course revision ${String(result.data.courseRevision)}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "lesson set", aliases: ["lesson update"],
    usage: "lesson set [<course>] <lesson> [--slug …] [--edition <slug>] [--part lectures|labs] [--kind …] [--visible true|false] [--license-code …] [--unset <field>] [--file fields.json] [--dry-run]",
    summary: "change lesson fields (PATCH, expectedRevision read first); --slug redirects the old URL from the next release; --edition moves it to the end of another edition",
    options: { ...fieldOptions(lessonPatch, ["expectedRevision", "editionId"]), ...fileOption, edition: { type: "string", help: "move to this edition (slug or id)", value: "<slug>" } },
    positionals: { min: 1, max: 2 }, routes: ["GET /courses", "GET /courses/:id", "PATCH /lessons/:id"],
    async run(context) {
      const lone = context.args.positionals.length === 1;
      const id = positional(context.args, lone ? 0 : 1, "lesson");
      const courseId = lone ? await courseOfLesson(context, id) : await resolveCourseId(context, positional(context.args, 0, "course"));
      const move = stringOption(context.args, "edition");
      const target = move === undefined ? undefined : editionOf(await getCourse(context, courseId), move);
      const fields = target === undefined ? patchFields(context, lessonPatch, context.args) : { ...patchFields(context, lessonPatch, context.args, true), editionId: target.id };
      if (context.dryRun) {
        // The API's own dry-run: the same checks and redirect plan, nothing written.
        const lesson = await lessonOf(context, courseId, id);
        const report = await context.client.call("PATCH /lessons/:id", { params: { id }, query: { dryRun: "true" }, body: { ...fields, expectedRevision: lesson.revision } });
        if ("dryRun" in report.data) context.out.lines([`Dry-run for ${id} (nothing changed):`, ...slugLines(report.data.redirects), ...JSON.stringify(report.data.changes, null, 2).split("\n").map((line) => `  ${line}`)]);
        context.out.result(report.envelope);
        return;
      }
      await context.confirm(`Change ${Object.keys(fields).join(", ")} of ${id}`);
      const result = await patchWithRetry(context, fields, async () => {
        const lesson = await lessonOf(context, courseId, id);
        return { revision: lesson.revision, values: lesson as unknown as Record<string, unknown> };
      }, (revision) => context.client.call("PATCH /lessons/:id", { params: { id }, body: { ...fields, expectedRevision: revision } }));
      if ("dryRun" in result.data) throw new CliError("PATCH /lessons/:id answered a dry-run report instead of the lesson.", EXIT.api);
      context.out.lines([`Updated ${id} (revision ${String(result.data.lesson.revision)}).`, ...slugLines(result.data.redirects)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "lesson reslug", usage: "lesson reslug <course> | --all-imported [--dry-run | --apply] [--exclude <lesson ids>]",
    summary: "give imported lessons the clean slug rule's slugs (src/catalog/domain/lesson-address.ts); prints old → new, and only --apply sends PUT /lessons/slugs (one atomic batch per course, 308 from the old URLs from the next release); the 126 legacy lessons never change",
    options: {
      "all-imported": { type: "boolean", help: "every course without a legacy lesson" },
      apply: { type: "boolean", help: "send the batches (otherwise the API's dry-run: the same checks, nothing written)" },
      exclude: { type: "string", help: "lessons that keep their slug", value: "<ids>" },
    },
    positionals: { min: 0, max: 1 }, routes: ["GET /tables", "GET /courses/:id", "PUT /lessons/slugs"],
    async run(context) {
      const all = flag(context.args, "all-imported");
      const apply = flag(context.args, "apply");
      const ref = context.args.positionals[0];
      if (all === (ref !== undefined)) throw new UsageError("Name one course or pass --all-imported.");
      if (apply && context.dryRun) throw new UsageError("--apply and --dry-run exclude each other.");
      const exclude = new Set(listOption(context.args, "exclude") ?? []);
      const { tables } = (await context.client.call("GET /tables")).data;
      const courses = all
        ? tables.courses.filter((course) => tables.lessons.some((lesson) => lesson.course_id === course.id) && !tables.lessons.some((lesson) => lesson.course_id === course.id && LEGACY_LESSON_IDS.has(lesson.id)))
        : tables.courses.filter((course) => course.id === ref || course.slug === ref);
      if (courses.length === 0) throw new UsageError(all ? "No imported course." : `No course ${String(ref)} (neither an id nor a slug).`);
      const known = new Set(tables.lessons.filter((lesson) => courses.some((course) => course.id === lesson.course_id)).map((lesson) => lesson.id));
      const unknown = [...exclude].filter((id) => !known.has(id));
      if (unknown.length) throw new UsageError(`--exclude names lessons outside these courses: ${unknown.join(", ")}.`);
      const plans = courses.map((course) => {
        const slugCourse = slugCourseFromTables(tables, course.id);
        return { course, results: slugCourse ? reslugCourse(slugCourse, exclude) : [] };
      });
      const moved = (results: readonly Reslug[]) => results.filter((result) => result.before !== result.after);
      const rows = plans.flatMap(({ course, results }) => moved(results).map((result) => [course.slug, result.lessonId, `${result.before} → ${result.after}`, result.reason]));
      const count = (reason: Reslug["reason"]) => plans.reduce((sum, { results }) => sum + results.filter((result) => result.reason === reason).length, 0);
      context.out.lines([
        ...(rows.length ? table(["course", "lesson", "old → new", "reason"], rows) : []),
        `${String(rows.length)} slug(s) change in ${String(plans.filter(({ results }) => moved(results).length > 0).length)} of ${String(courses.length)} course(s): ${String(count("rule"))} rule, ${String(count("rule, disambiguated"))} disambiguated, ${String(count("kept"))} kept, ${String(count("excluded"))} excluded, ${String(count("legacy"))} legacy.`,
      ]);
      const batches = plans.filter(({ results }) => moved(results).length > 0);
      if (apply) await context.confirm(`Change ${String(rows.length)} lesson slug(s) in ${String(batches.length)} course(s)`);
      const answers: unknown[] = [];
      for (const { course, results } of batches) {
        const changes = moved(results).map((result) => ({ lessonId: result.lessonId, slug: result.after }));
        const { revision } = (await getCourse(context, course.id)).course;
        const answer = await context.client.call("PUT /lessons/slugs", { body: { courseId: course.id, expectedRevision: revision, changes, ...(apply ? {} : { dryRun: true }) } });
        context.out.line(`${course.slug}: ${"dryRun" in answer.data ? "dry-run, " : ""}${batchSummary(answer.data.plan)}${"courseRevision" in answer.data ? `; course revision ${String(answer.data.courseRevision)}` : ""}.`);
        answers.push(answer.envelope);
      }
      context.out.line(apply ? "Applied; the new slugs and their 308 redirects go live with the next release (release create)." : "Nothing changed. Re-run with --apply to send the batches.");
      context.out.result({ ok: true, data: { changes: rows.length, batches: answers } });
    },
  },
  {
    name: "lesson delete", usage: "lesson delete <course> <lesson> [--confirm] [--delete-bytes]", summary: "delete a lesson; a dry-run report unless --confirm",
    options: { confirm: { type: "boolean", help: "execute (otherwise only the report)" }, "delete-bytes": { type: "boolean", help: "also delete R2 bytes no other environment uses (checked there first; default keeps them)" } },
    positionals: { min: 2, max: 2 }, routes: ["GET /courses/:id", "DELETE /lessons/:id", "POST /media/references"],
    async run(context) {
      const courseId = positional(context.args, 0, "course");
      const id = positional(context.args, 1, "lesson");
      const report = await context.client.call("DELETE /lessons/:id", { params: { id } });
      context.out.lines([`Dry-run report for ${id}:`, ...JSON.stringify(report.data.report, null, 2).split("\n").map((line) => `  ${line}`)]);
      if (!flag(context.args, "confirm")) { context.out.line("Nothing changed. Re-run with --confirm to execute."); context.out.result(report.envelope); return; }
      const lesson = await lessonOf(context, courseId, id);
      await context.confirm(`Delete lesson ${id} (${lesson.slug})`, true);
      const bytes = await bytesQuery(context, report.data.report);
      const result = await context.client.call("DELETE /lessons/:id", { params: { id }, query: { ...bytes, confirm: "true", expectedRevision: String(lesson.revision) } });
      context.out.line(`Deleted ${id}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "lesson reorder", usage: "lesson reorder <course> [--edition <slug>] --ids a,b,c | --file ids.json | --move <lesson> --to <position>",
    summary: "set the complete lesson order of one edition (validated locally: no lesson missing, unknown or repeated)", positionals: { min: 1, max: 1 },
    options: {
      ...editionOption,
      ids: { type: "string", help: "every lesson id, in the new order", value: "<a,b,…>" }, file: { type: "string", help: "JSON array of every lesson id", value: "<path>" },
      move: { type: "string", help: "move one lesson…", value: "<lesson>" }, to: { type: "string", help: "…to this position (1-based)", value: "<n>" },
    },
    routes: ["GET /courses", "GET /courses/:id", "PUT /courses/:id/lessons/order", "PUT /editions/:id/lessons/order"],
    async run(context) {
      const id = await resolveCourseId(context, positional(context.args, 0, "course"));
      const ids = listOption(context.args, "ids");
      const file = stringOption(context.args, "file");
      const move = stringOption(context.args, "move");
      const to = intOption(context.args, "to");
      if ([ids, file, move].filter((value) => value !== undefined).length !== 1) throw new UsageError("Pass exactly one of --ids, --file and --move.");
      if ((move === undefined) !== (to === undefined)) throw new UsageError("--move and --to go together.");
      let proposed: string[] | undefined = ids;
      if (file !== undefined) {
        const parsed = parseJsonFile(context, file);
        if (!Array.isArray(parsed) || !parsed.every((item) => typeof item === "string")) throw new UsageError(`${file} must hold a JSON array of lesson ids.`);
        proposed = parsed;
      }
      const detail = await getCourse(context, id);
      const edition = editionOf(detail, stringOption(context.args, "edition"));
      const current = detail.lessons.filter((lesson) => lesson.editionId === edition.id).map((lesson) => lesson.id);
      if (move !== undefined) proposed = moveLesson(current, move, to ?? 0);
      const order = proposed ?? [];
      checkPermutation(current, order);
      if (order.every((lessonId, index) => current[index] === lessonId)) { context.out.line(`${edition.slug} of ${id} already has this order; nothing sent.`); return; }
      await context.confirm(`Reorder the ${String(order.length)} lessons of ${edition.slug} (${id})`);
      const body = { lessonIds: order, expectedRevision: detail.course.revision };
      // A course with one edition keeps the P4 route; with several, the order is per edition.
      const result = detail.editions.length === 1
        ? await context.client.call("PUT /courses/:id/lessons/order", { params: { id }, body })
        : await context.client.call("PUT /editions/:id/lessons/order", { params: { id: edition.id }, body });
      context.out.lines([`New order of ${edition.slug} (course revision ${String(result.data.revision)}):`, ...result.data.lessonIds.map((lessonId, index) => `  ${String(index + 1).padStart(2, "0")} ${lessonId}`)]);
      context.out.result(result.envelope);
    },
  },
];

export const authorCommands: CommandSpec[] = [
  {
    name: "author list", usage: "author list", summary: "authors with their courses and Home rows", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /authors"],
    async run(context) {
      const result = await context.client.call("GET /authors");
      context.out.lines(table(["id", "slug", "name", "monogram", "kind", "rev", "courses", "home rows"], result.data.authors.map((author) => [
        author.id, author.slug, author.name, author.monogram, author.kind, String(author.revision), String(author.courses), String(author.homeRows),
      ])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "author create", usage: "author create --slug <s> --name <n> --monogram <AB> [--role …] --kind person|institution|channel", summary: "create an author",
    options: fieldOptions(authorCreate), positionals: { min: 0, max: 0 }, routes: ["POST /authors"],
    async run(context) {
      const body = fieldValues(authorCreate, context.args) as z.input<typeof authorCreate>;
      await context.confirm(`Create author ${body.slug}`);
      const result = await context.client.call("POST /authors", { body });
      context.out.line(`Created ${result.data.author.id} (${result.data.author.slug}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "author set", usage: "author set <author> [--name …] [--monogram …] [--role …] [--kind …] [--file fields.json]", summary: "change author fields",
    options: { ...fieldOptions(authorPatch, ["expectedRevision"]), ...fileOption }, positionals: { min: 1, max: 1 }, routes: ["GET /authors", "PATCH /authors/:id"],
    async run(context) {
      const id = positional(context.args, 0, "author");
      const fields = patchFields(context, authorPatch, context.args);
      await context.confirm(`Change ${Object.keys(fields).join(", ")} of ${id}`);
      const result = await patchWithRetry(context, fields, async () => {
        const author = await authorOf(context, id);
        return { revision: author.revision, values: author as unknown as Record<string, unknown> };
      }, (revision) => context.client.call("PATCH /authors/:id", { params: { id }, body: { ...fields, expectedRevision: revision } }));
      context.out.line(`Updated ${id} (revision ${String(result.data.author.revision)}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "author delete", usage: "author delete <author> [--confirm]", summary: "delete an author without courses; a dry-run report unless --confirm",
    options: { confirm: { type: "boolean", help: "execute (otherwise only the report)" } }, positionals: { min: 1, max: 1 }, routes: ["GET /authors", "DELETE /authors/:id"],
    async run(context) {
      const id = positional(context.args, 0, "author");
      const report = await context.client.call("DELETE /authors/:id", { params: { id } });
      context.out.lines([`Dry-run report for ${id}:`, ...JSON.stringify(report.data.report, null, 2).split("\n").map((line) => `  ${line}`)]);
      if (!flag(context.args, "confirm")) { context.out.line("Nothing changed. Re-run with --confirm to execute."); context.out.result(report.envelope); return; }
      const author = await authorOf(context, id);
      await context.confirm(`Delete author ${id} (${author.slug})`, true);
      const result = await context.client.call("DELETE /authors/:id", { params: { id }, query: { confirm: "true", expectedRevision: String(author.revision) } });
      context.out.line(`Deleted ${id}.`);
      context.out.result(result.envelope);
    },
  },
];
