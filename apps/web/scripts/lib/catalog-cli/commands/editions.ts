import type { z } from "zod";
import { editionCreate, editionLabel, editionPatch, parseEditionLabel } from "../../../../src/catalog/domain/contracts.ts";
import { fieldOptions, fieldValues, flag, listOption, positional } from "../args.ts";
import type { CommandSpec, Context } from "../context.ts";
import { UsageError } from "../errors.ts";
import { duration, table } from "../render.ts";
import type { CourseDetail } from "../responses.ts";
import { bytesQuery, getCourse, listAllCourses, patchFields, patchWithRetry } from "./shared.ts";

// Course editions (ADR-21, docs/catalog/editions.md). A course is named by id (course-6) or slug; an edition by its slug
// in that course (fall-2024) or its id (edition-3).

export type EditionRow = CourseDetail["editions"][number];

/** The course id of `ref`: an id as is, a slug through GET /courses. */
export async function resolveCourseId(context: Context, ref: string): Promise<string> {
  if (/^course-\d+$/.test(ref)) return ref;
  const courses = await listAllCourses(context);
  const match = courses.find((course) => course.slug === ref || course.id === ref);
  if (!match) throw new UsageError(`No course ${ref} (neither an id nor a slug).`);
  return match.id;
}

/** The edition of `detail` named by slug or id; without a name, the course's only edition (several: a usage error). */
export function editionOf(detail: CourseDetail, ref: string | undefined): EditionRow {
  const { editions } = detail;
  if (ref === undefined) {
    const [only] = editions;
    if (editions.length === 1 && only) return only;
    throw new UsageError(`${detail.course.id} has ${String(editions.length)} editions (${editions.map((edition) => edition.slug).join(", ")}): pass --edition <slug>.`);
  }
  const match = editions.find((edition) => edition.slug === ref || edition.id === ref);
  if (!match) throw new UsageError(`${detail.course.id} has no edition ${ref} (${editions.map((edition) => edition.slug).join(", ") || "none"}).`);
  return match;
}

/** One row per edition: position, id, slug, label, lessons by part, duration, pending rules (GET /courses/:id has them). */
export function editionLines(editions: readonly (Omit<EditionRow, "pending"> & { pending?: EditionRow["pending"] })[]): string[] {
  return table(["#", "edition", "slug", "label", "term", "year", "lectures", "labs", "visible", "length", "rev", "pending"], editions.map((edition) => [
    String(edition.position), edition.id, edition.slug, edition.label, edition.term ?? "-", String(edition.year), String(edition.counts.parts.lectures),
    String(edition.counts.parts.labs), `${String(edition.counts.visibleLessons)}/${String(edition.counts.lessons)}`, duration(edition.counts.durationSeconds),
    String(edition.revision), edition.pending?.length ? edition.pending.map((failure) => failure.rule).join(", ") : "-",
  ]));
}

/** `--label "Fall 2025"` (or "FA25") fills slug, term and year unless given; the label sent is always term + year (ADR-21). */
function createBody(context: Context): z.input<typeof editionCreate> {
  const fields = fieldValues(editionCreate, context.args);
  const derived = typeof fields.label === "string" ? parseEditionLabel(fields.label) : null;
  const merged = { ...(derived ?? {}), ...fields };
  const year = typeof merged.year === "number" ? merged.year : null;
  const term = typeof merged.term === "string" ? merged.term : null;
  const check = editionCreate.safeParse({ ...merged, ...(year === null ? {} : { label: editionLabel(term, year) }) });
  if (!check.success) throw new UsageError(`Pass --label "Fall 2025" (or --slug, --label, --year and --term): ${check.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ")}.`);
  return check.data;
}

export const editionCommands: CommandSpec[] = [
  {
    name: "edition list", usage: "edition list <course>", summary: "the course's editions, newest first, with lessons by part and pending rules",
    options: {}, positionals: { min: 1, max: 1 }, routes: ["GET /courses", "GET /courses/:id/editions"],
    async run(context) {
      const id = await resolveCourseId(context, positional(context.args, 0, "course"));
      const result = await context.client.call("GET /courses/:id/editions", { params: { id } });
      context.out.lines([`${id}: ${String(result.data.editions.length)} edition(s); position 1 opens by default.`, ...editionLines(result.data.editions)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "edition create", usage: "edition create <course> --label \"Fall 2025\" [--slug fall-2025] [--term fall] [--year 2025] [--resolution 1080p]",
    summary: "add an edition; it takes its place by year and term (newest first)", options: fieldOptions(editionCreate), positionals: { min: 1, max: 1 },
    routes: ["GET /courses", "POST /courses/:id/editions"],
    async run(context) {
      const id = await resolveCourseId(context, positional(context.args, 0, "course"));
      const body = createBody(context);
      await context.confirm(`Add edition ${body.label} (${body.slug}) to ${id}`);
      const result = await context.client.call("POST /courses/:id/editions", { params: { id }, body });
      context.out.line(`Created ${result.data.edition.id} (${result.data.edition.slug}) at position ${String(result.data.edition.position)}; order ${result.data.order.join(", ")}; course revision ${String(result.data.courseRevision)}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "edition set", usage: "edition set <course> <edition> [--label …] [--term …] [--year …] [--resolution …] [--unset <field>]",
    summary: "change edition fields (a new year or term moves it to its date place)", options: { ...fieldOptions(editionPatch, ["expectedRevision"]), file: { type: "string", help: "JSON object of fields", value: "<path>" } },
    positionals: { min: 2, max: 2 }, routes: ["GET /courses", "GET /courses/:id", "PATCH /editions/:id"],
    async run(context) {
      const courseId = await resolveCourseId(context, positional(context.args, 0, "course"));
      const ref = positional(context.args, 1, "edition");
      const fields = patchFields(context, editionPatch, context.args);
      const target = editionOf(await getCourse(context, courseId), ref);
      await context.confirm(`Change ${Object.keys(fields).join(", ")} of ${target.id} (${target.slug})`);
      const result = await patchWithRetry(context, fields, async () => {
        const edition = editionOf(await getCourse(context, courseId), target.id);
        return { revision: edition.revision, values: edition as unknown as Record<string, unknown> };
      }, (revision) => context.client.call("PATCH /editions/:id", { params: { id: target.id }, body: { ...fields, expectedRevision: revision } }));
      context.out.line(`Updated ${target.id} (revision ${String(result.data.edition.revision)}, position ${String(result.data.edition.position)}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "edition reorder", usage: "edition reorder <course> --ids <edition,edition,…>", summary: "set the edition order by hand (the first opens by default); every edition exactly once",
    options: { ids: { type: "string", required: true, help: "every edition (slug or id), newest first", value: "<a,b,…>" } }, positionals: { min: 1, max: 1 },
    routes: ["GET /courses", "GET /courses/:id", "PUT /courses/:id/editions/order"],
    async run(context) {
      const courseId = await resolveCourseId(context, positional(context.args, 0, "course"));
      const detail = await getCourse(context, courseId);
      const order = (listOption(context.args, "ids") ?? []).map((ref) => editionOf(detail, ref).id);
      const current = detail.editions.map((edition) => edition.id);
      const missing = current.filter((id) => !order.includes(id));
      if (missing.length > 0 || new Set(order).size !== order.length) throw new UsageError(`Name every edition of ${courseId} exactly once (${detail.editions.map((edition) => edition.slug).join(", ")}).`);
      if (order.every((id, index) => current[index] === id)) { context.out.line(`${courseId} already has this order; nothing sent.`); return; }
      await context.confirm(`Reorder the ${String(order.length)} editions of ${courseId} by hand`);
      const result = await context.client.call("PUT /courses/:id/editions/order", { params: { id: courseId }, body: { editionIds: order, expectedRevision: detail.course.revision } });
      context.out.lines([`New order (course revision ${String(result.data.revision)}):`, ...result.data.editionIds.map((id, index) => `  ${String(index + 1)} ${id}`)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "edition delete", usage: "edition delete <course> <edition> [--with-lessons] [--confirm] [--delete-bytes]",
    summary: "delete an edition (empty, or with its lessons); a dry-run report unless --confirm",
    options: {
      "with-lessons": { type: "boolean", help: "also delete its lessons (as lesson delete does: progress kept, redirects created)" },
      confirm: { type: "boolean", help: "execute (otherwise only the report)" }, "delete-bytes": { type: "boolean", help: "also delete the lessons' R2 bytes no other environment uses (checked there first; default keeps them)" },
    },
    positionals: { min: 2, max: 2 }, routes: ["GET /courses", "GET /courses/:id", "DELETE /editions/:id", "POST /media/references"],
    async run(context) {
      const courseId = await resolveCourseId(context, positional(context.args, 0, "course"));
      const edition = editionOf(await getCourse(context, courseId), positional(context.args, 1, "edition"));
      const query = flag(context.args, "with-lessons") ? { mode: "with-lessons" as const } : {};
      const report = await context.client.call("DELETE /editions/:id", { params: { id: edition.id }, query });
      context.out.lines([`Dry-run report for ${edition.id} (${edition.slug}):`, ...JSON.stringify(report.data.report, null, 2).split("\n").map((line) => `  ${line}`)]);
      if (!flag(context.args, "confirm")) { context.out.line("Nothing changed. Re-run with --confirm to execute."); context.out.result(report.envelope); return; }
      await context.confirm(`Delete edition ${edition.id} (${edition.slug}, ${String(edition.counts.lessons)} lesson(s))`, true);
      const bytes = await bytesQuery(context, report.data.report);
      const result = await context.client.call("DELETE /editions/:id", { params: { id: edition.id }, query: { ...query, ...bytes, confirm: "true", expectedRevision: String(edition.revision) } });
      context.out.line(`Deleted ${edition.id}.`);
      context.out.result(result.envelope);
    },
  },
];
