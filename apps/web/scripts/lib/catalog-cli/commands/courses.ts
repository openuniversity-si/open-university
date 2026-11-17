import type { z } from "zod";
import { CLASSIFY_MAX, courseCreate, coursePatch } from "../../../../src/catalog/domain/contracts.ts";
import type { BodyOf } from "../routes.ts";
import { fieldOptions, fieldValues, flag, intOption, positional, requireOption, stringOption } from "../args.ts";
import type { CommandSpec, Context } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";
import { diffLines, orDash, preconditionLines, reviewLines, table } from "../render.ts";
import { editionLines } from "./editions.ts";
import { bytesQuery, getCourse, listAllCourses, listReleases, patchFields, patchWithRetry, releaseDryRun, verifyActivation } from "./shared.ts";


const courseArg = (context: Context) => positional(context.args, 0, "course");

export const courseCommands: CommandSpec[] = [
  {
    name: "course list", usage: "course list [--status draft|review|published|archived]", summary: "list courses with status, revision, counts and pending rules",
    options: { status: { type: "string", help: "only this status", value: "<s>" } }, positionals: { min: 0, max: 0 }, routes: ["GET /courses"],
    async run(context) {
      const status = stringOption(context.args, "status");
      const courses = await listAllCourses(context, status === undefined ? {} : { status });
      context.out.lines(table(["id", "slug", "status", "rev", "lessons", "drafts", "pending"], courses.map((course) => [
        course.id, course.slug, `${course.status}${course.featured ? "*" : ""}`, String(course.revision), `${String(course.counts.visibleLessons)}/${String(course.counts.lessons)}`,
        String(course.counts.draftTexts), course.pending.target ? `${String(course.pending.failed.length)} for ${course.pending.target}` : "-",
      ])));
      context.out.result({ courses, nextCursor: null });
    },
  },
  {
    name: "course get", usage: "course get <course>", summary: "one course: fields, rights, lessons (review shows everything)",
    options: {}, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id"],
    async run(context) {
      const result = await context.client.call("GET /courses/:id", { params: { id: courseArg(context) } });
      const { course } = result.data;
      context.out.lines([
        `${course.id} /c/${course.slug} · ${course.title} · ${course.status} · revision ${String(course.revision)} · author ${course.authorId}`,
        `license ${orDash(course.licenseCode)} · source ${orDash(course.sourceId)} · rights ${course.rightsStatus} · published ${orDash(course.publishedAt)}`,
        ...editionLines(result.data.editions),
        ...table(["edition", "#", "lesson", "slug", "part", "kind", "visible", "rev"], result.data.lessons.map((lesson) => [
          result.data.editions.find((edition) => edition.id === lesson.editionId)?.slug ?? lesson.editionId, String(lesson.position), lesson.id, lesson.slug, lesson.part, lesson.kind, lesson.visible ? "yes" : "no", String(lesson.revision),
        ])),
      ]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "course create", usage: "course create --slug <s> --author-id <id> --title <t> [--lesson-noun …] [--source-id …] [--license-code …] [--canonical-url …]",
    summary: "create a draft course (POST /courses)", options: fieldOptions(courseCreate), positionals: { min: 0, max: 0 }, routes: ["POST /courses"],
    async run(context) {
      const body = fieldValues(courseCreate, context.args) as z.input<typeof courseCreate>;
      await context.confirm(`Create course ${body.slug}`);
      const result = await context.client.call("POST /courses", { body });
      context.out.line(`Created ${result.data.course.id} (/c/${result.data.course.slug}, draft, revision ${String(result.data.course.revision)}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "course set", usage: "course set <course> [--title …] [--rights-status cleared] [--unset <field>] [--file fields.json]",
    summary: "change course fields (PATCH, expectedRevision read first)", options: { ...fieldOptions(coursePatch, ["expectedRevision"]), file: { type: "string", help: "JSON object of fields", value: "<path>" } },
    positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "PATCH /courses/:id"],
    async run(context) {
      const id = courseArg(context);
      const fields = patchFields(context, coursePatch, context.args);
      await context.confirm(`Change ${Object.keys(fields).join(", ")} of ${id}`);
      const result = await patchWithRetry(context, fields, async () => {
        const { course } = await getCourse(context, id);
        return { revision: course.revision, values: course as unknown as Record<string, unknown> };
      }, (revision) => context.client.call("PATCH /courses/:id", { params: { id }, body: { ...fields, expectedRevision: revision } }));
      context.out.line(`Updated ${id} (revision ${String(result.data.course.revision)}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "course classify", usage: "course classify --file <csv|json> [--release --note \"…\"]",
    summary: "set area and/or subarea of many courses in ONE transaction (all or nothing; re-running is a noop); --release then publishes the tables",
    options: {
      file: { type: "string", required: true, help: "CSV with a header (course,area_id,subarea_id) or a JSON array of {course, areaId?, subareaId?}; course = id or slug; empty = keep, null = clear", value: "<path>" },
      release: { type: "boolean", help: "after classifying, compile and activate a release (as release create)" },
      note: { type: "string", help: "release note (with --release)", value: "<text>" },
    },
    positionals: { min: 0, max: 0 }, routes: ["GET /courses", "POST /courses/classify", "GET /releases", "POST /releases"],
    async run(context) {
      const file = requireOption(context.args, "file");
      const wanted = parseClassifyFile(context.readText(file), file);
      const withRelease = flag(context.args, "release");
      if (withRelease) requireOption(context.args, "note");
      const listed = await listAllCourses(context);
      const items = wanted.map((entry) => {
        const course = listed.find((row) => row.id === entry.course || row.slug === entry.course);
        if (!course) throw new UsageError(`No course ${entry.course}.`);
        return { course, item: { id: course.id, ...(entry.areaId === undefined ? {} : { areaId: entry.areaId }), ...(entry.subareaId === undefined ? {} : { subareaId: entry.subareaId }) } };
      });
      const ids = items.map((entry) => entry.item.id);
      const twice = ids.filter((id, index) => ids.indexOf(id) !== index);
      if (twice.length) throw new UsageError(`${file} names ${[...new Set(twice)].join(", ")} twice (by id and by slug).`);
      const pending = items.filter(({ course, item }) => (item.areaId !== undefined && item.areaId !== (course.areaId ?? null)) || (item.subareaId !== undefined && item.subareaId !== (course.subareaId ?? null)));
      context.out.lines([
        `Classify ${String(items.length)} course(s): ${String(pending.length)} change, ${String(items.length - pending.length)} already as asked.`,
        ...pending.slice(0, 50).map(({ course, item }) => `  ${course.id} /c/${course.slug} · ${orDash(course.areaId ?? null)}/${orDash(course.subareaId ?? null)} → ${item.areaId ?? orDash(course.areaId ?? null)}/${item.subareaId === undefined ? orDash(course.subareaId ?? null) : orDash(item.subareaId)}`),
        ...(pending.length > 50 ? [`  … and ${String(pending.length - 50)} more`] : []),
      ]);
      if (pending.length > 0) {
        await context.confirm(`Classify ${String(pending.length)} course(s) in one transaction`);
        let changed = 0;
        for (let start = 0; start < pending.length; start += CLASSIFY_MAX) {
          const result = await context.client.call("POST /courses/classify", { body: { items: pending.slice(start, start + CLASSIFY_MAX).map((entry) => entry.item) } });
          changed += result.data.changed.length;
          context.out.result(result.envelope);
        }
        context.out.line(`Classified ${String(changed)} course(s).`);
      }
      if (!withRelease) { if (pending.length > 0) context.out.line(`Published courses change on the site with the next release: tower-catalog release create --note "…" --target ${context.target}`); return; }
      const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
      const dry = await releaseDryRun(context);
      context.out.lines(["Active release → current tables:", ...diffLines(dry.data.diff)]);
      if (dry.data.unchanged === true) { context.out.line("Nothing to release: the compile equals the active release."); return; }
      await context.confirm("Create and activate a release from the current tables", true);
      const result = await context.client.call("POST /releases", { body: { note: requireOption(context.args, "note") }, state: { active: previous } });
      if (!("release" in result.data)) throw new CliError("POST /releases answered a dry-run report instead of a release.", EXIT.api);
      const { release } = result.data;
      context.out.lines([`Release #${String(release.number)} sha256 ${release.sha}.`, ...(release.created && previous !== null ? [`Roll back with: tower-catalog release activate ${String(previous)} --target ${context.target}`] : [])]);
      context.out.result(result.envelope);
      if (release.created) await verifyActivation(context, release.number, previous);
    },
  },
  {
    name: "course delete", usage: "course delete <course> --mode archive|purge [--confirm] [--replacement-featured <id>] [--delete-bytes] [--note …]",
    summary: "archive or purge; a dry-run report unless --confirm", positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "DELETE /courses/:id", "POST /media/references"],
    options: {
      mode: { type: "string", required: true, help: "archive | purge", value: "<m>" }, confirm: { type: "boolean", help: "execute (otherwise only the report)" },
      "replacement-featured": { type: "string", help: "new featured course when archiving the featured one", value: "<id>" },
      "delete-bytes": { type: "boolean", help: "purge: also delete R2 bytes no other environment uses (checked there first; default keeps them)" }, note: { type: "string", help: "audit note", value: "<text>" },
    },
    async run(context) {
      const id = courseArg(context);
      const mode = requireOption(context.args, "mode");
      if (mode !== "archive" && mode !== "purge") throw new UsageError("--mode must be archive or purge.");
      const extra = {
        ...(stringOption(context.args, "replacement-featured") === undefined ? {} : { replacementFeaturedId: stringOption(context.args, "replacement-featured") }),
        ...(stringOption(context.args, "note") === undefined ? {} : { note: stringOption(context.args, "note") }),
      };
      const report = await context.client.call("DELETE /courses/:id", { params: { id }, query: { mode, ...extra } });
      context.out.lines([`Dry-run report for ${mode} of ${id}:`, ...JSON.stringify(report.data.report, null, 2).split("\n").map((line) => `  ${line}`)]);
      if (!flag(context.args, "confirm")) {
        context.out.line("Nothing changed. Re-run with --confirm to execute.");
        context.out.result(report.envelope);
        return;
      }
      if (mode === "purge" && report.data.alreadyPurged === true) {
        await context.confirm(`Finish purge of ${id}`, true);
        const bytes = await bytesQuery(context, report.data.report);
        const result = await context.client.call("DELETE /courses/:id", { params: { id }, query: { mode, confirm: "true", ...bytes } });
        context.out.result(result.envelope);
        return;
      }
      const { course } = await getCourse(context, id);
      await context.confirm(`${mode === "purge" ? "PURGE (irreversible)" : "Archive"} ${id} (/c/${course.slug})`, true);
      const bytes = mode === "purge" ? await bytesQuery(context, report.data.report) : {};
      const result = await context.client.call("DELETE /courses/:id", { params: { id }, query: { mode, confirm: "true", expectedRevision: String(course.revision), ...extra, ...bytes } });
      context.out.line(`${mode === "purge" ? "Purged" : "Archived"} ${id}.`);
      context.out.lines(JSON.stringify(result.data, null, 2).split("\n").map((line) => `  ${line}`));
      context.out.result(result.envelope);
    },
  },
  {
    name: "status", usage: "status <course> review|draft|archived", summary: "move a course between draft, review and archived (412 lists every unmet rule)",
    options: {}, positionals: { min: 2, max: 2 }, routes: ["GET /courses/:id", "POST /courses/:id/status"],
    async run(context) {
      const id = courseArg(context);
      const to = positional(context.args, 1, "status");
      if (to !== "review" && to !== "draft" && to !== "archived") throw new UsageError("Status must be review, draft or archived (publish and unpublish have their own commands).");
      const { course, editions } = await getCourse(context, id);
      await context.confirm(`Move ${id} from ${course.status} to ${to}`);
      const result = await context.client.call("POST /courses/:id/status", { params: { id }, body: { to, expectedRevision: course.revision } });
      context.out.line(`${id} is ${result.data.course.status} (revision ${String(result.data.course.revision)}); editions ${editions.map((edition) => `${edition.slug} (${String(edition.counts.lessons)})`).join(", ") || "none"}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "publish", usage: "publish <course> --note \"…\" [--allow-orphan] | publish --batch <file> --note \"…\" [--allow-orphan]",
    summary: "publish: shows the release diff, asks, creates release N+1, verifies the site; --batch: many courses in ONE release (all or nothing)",
    options: {
      note: { type: "string", required: true, help: "release note", value: "<text>" }, "allow-orphan": { type: "boolean", help: "publish without a visible Home row" },
      batch: { type: "string", help: "file of course ids or slugs (one per line, # comments, or a JSON array): one atomic release", value: "<file>" },
    },
    positionals: { min: 0, max: 1 }, routes: ["GET /courses/:id", "GET /courses", "GET /releases", "POST /releases", "POST /courses/:id/publish", "POST /courses/publish-batch"],
    async run(context) {
      const batch = stringOption(context.args, "batch");
      if (batch !== undefined) { await publishBatch(context, batch); return; }
      if (context.args.positionals.length !== 1) throw new UsageError("publish takes one course, or --batch <file>.");
      const id = courseArg(context);
      const detail = await getCourse(context, id);
      const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
      const dry = await releaseDryRun(context);
      const unmet = detail.preconditions?.published ?? [];
      context.out.lines([
        `Publish ${id} (/c/${detail.course.slug}, ${detail.course.status}, revision ${String(detail.course.revision)}): ${String(detail.lessons.filter((lesson) => lesson.visible).length)} visible lessons, ${String(Object.keys(detail.texts).length)} course texts; active release #${String(previous ?? "none")}.`,
        "Pending table changes outside this course (POST /releases?dryRun=true):", ...diffLines(dry.data.diff),
        ...(unmet.length ? [`The API will refuse it (412): ${String(unmet.length)} unmet rule(s):`, ...preconditionLines(unmet)] : []),
      ]);
      await context.confirm(`Publish ${id} as a new release`, true);
      const body = { expectedRevision: detail.course.revision, note: requireOption(context.args, "note"), ...(flag(context.args, "allow-orphan") ? { allowOrphan: true } : {}) };
      const result = await context.client.call("POST /courses/:id/publish", { params: { id }, body });
      const { release } = result.data;
      context.out.lines([`${release.created ? "Published" : "Nothing changed (noop)"}: release #${String(release.number)} sha256 ${release.sha}`, ...diffLines(result.data.diff)]);
      context.out.result(result.envelope);
      await verifyActivation(context, release.number, previous, [detail.course.slug]);
    },
  },
  {
    name: "unpublish", usage: "unpublish <course> --note \"…\" [--replacement-featured <id>] [--to draft|archived]", summary: "take a course off the site in a new release",
    options: {
      note: { type: "string", required: true, help: "release note", value: "<text>" }, "replacement-featured": { type: "string", help: "new featured course", value: "<id>" },
      to: { type: "string", help: "draft (default) | archived", value: "<s>" },
    },
    positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id", "GET /releases", "POST /releases", "POST /courses/:id/unpublish"],
    async run(context) {
      const id = courseArg(context);
      const to = stringOption(context.args, "to");
      if (to !== undefined && to !== "draft" && to !== "archived") throw new UsageError("--to must be draft or archived.");
      const detail = await getCourse(context, id);
      const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
      const dry = await releaseDryRun(context);
      context.out.lines([`Unpublish ${id} (/c/${detail.course.slug}, ${detail.course.status}); active release #${String(previous ?? "none")}.`, "Pending table changes (dry run):", ...diffLines(dry.data.diff)]);
      await context.confirm(`Unpublish ${id}`, true);
      const replacement = stringOption(context.args, "replacement-featured");
      const body = { expectedRevision: detail.course.revision, note: requireOption(context.args, "note"), ...(replacement === undefined ? {} : { replacementFeaturedId: replacement }), ...(to === undefined ? {} : { to }) } satisfies BodyOf<"POST /courses/:id/unpublish">;
      const result = await context.client.call("POST /courses/:id/unpublish", { params: { id }, body });
      const { release } = result.data;
      context.out.lines([`Unpublished: release #${String(release.number)} sha256 ${release.sha}`, ...diffLines(result.data.diff)]);
      context.out.result(result.envelope);
      if (release.created || result.replayed) await verifyActivation(context, release.number, previous);
    },
  },
  {
    name: "review", usage: "review <course>", summary: "every field with limit, length, sha256, status; lessons, covers, preconditions",
    options: {}, positionals: { min: 1, max: 1 }, routes: ["GET /courses/:id"],
    async run(context) {
      const result = await context.client.call("GET /courses/:id", { params: { id: courseArg(context) } });
      context.out.lines(reviewLines(result.data));
      context.out.result(result.envelope);
    },
  },
  {
    name: "preview-url", usage: "preview-url <course> [--ttl-minutes 1..60]", summary: "a draft-mode preview URL (a short-lived secret: printed once, to stdout only)",
    options: { "ttl-minutes": { type: "string", help: "token lifetime, 1–60 (default 30)", value: "<n>" } }, positionals: { min: 1, max: 1 }, routes: ["POST /preview-token"],
    async run(context) {
      const ttl = intOption(context.args, "ttl-minutes");
      if (ttl !== undefined && ttl > 60) throw new UsageError("--ttl-minutes must be 1–60.");
      const result = await context.client.call("POST /preview-token", { body: { courseId: courseArg(context), ...(ttl === undefined ? {} : { ttlMinutes: ttl }) } });
      context.out.secretOutput(`${context.client.origin}${result.data.url}`, result.envelope);
      context.out.note(`Expires at ${result.data.expiresAt}; opens ${result.data.to} in draft mode.`);
    },
  },
];

/** The course references of a --batch file: a JSON array of strings, or one per line (blank lines and # comments skipped). */
export function parseBatchFile(text: string, file: string): string[] {
  const trimmed = text.trim();
  let refs: string[];
  if (trimmed.startsWith("[")) {
    let parsed: unknown;
    try { parsed = JSON.parse(trimmed); } catch { throw new UsageError(`${file} is not valid JSON.`); }
    if (!Array.isArray(parsed) || parsed.some((entry) => typeof entry !== "string")) throw new UsageError(`${file} must be a JSON array of course ids or slugs.`);
    refs = (parsed as string[]).map((entry) => entry.trim());
  } else {
    refs = trimmed.split("\n").map((line) => line.replace(/#.*$/, "").trim());
  }
  refs = refs.filter((entry) => entry.length > 0);
  if (refs.length === 0) throw new UsageError(`${file} names no course.`);
  const twice = refs.filter((entry, index) => refs.indexOf(entry) !== index);
  if (twice.length) throw new UsageError(`${file} names ${[...new Set(twice)].join(", ")} more than once.`);
  return refs;
}

async function publishBatch(context: Context, file: string): Promise<void> {
  if (context.args.positionals.length > 0) throw new UsageError("Give either one course or --batch <file>, not both.");
  const refs = parseBatchFile(context.readText(file), file);
  const listed = await listAllCourses(context);
  const courses = refs.map((ref) => {
    const course = listed.find((entry) => entry.id === ref || entry.slug === ref);
    if (!course) throw new UsageError(`No course ${ref}.`);
    return course;
  });
  const ids = courses.map((course) => course.id);
  if (new Set(ids).size !== ids.length) throw new UsageError(`${file} names the same course twice (by id and by slug).`);
  const unready = courses.filter((course) => course.status !== "review" && course.status !== "published");
  if (unready.length) throw new UsageError(`Only review or published courses can be published: ${unready.map((course) => `${course.id} (${course.status})`).join(", ")}.`);
  const pending = courses.filter((course) => course.pending.target === "published" && course.pending.failed.length > 0);
  const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
  const dry = await releaseDryRun(context);
  context.out.lines([
    `Publish ${String(courses.length)} course(s) in ONE release (${String(courses.filter((course) => course.status === "review").length)} from review); active release #${String(previous ?? "none")}.`,
    ...courses.map((course) => `  ${course.id} /c/${course.slug} · ${course.status} · revision ${String(course.revision)}`),
    "Pending table changes outside these courses (POST /releases?dryRun=true):", ...diffLines(dry.data.diff),
    ...(pending.length ? [`The API will refuse the whole batch (412) unless fixed: ${pending.map((course) => `${course.id} (${String(course.pending.failed.length)} rule(s))`).join(", ")}.`] : []),
  ]);
  await context.confirm(`Publish ${String(courses.length)} courses as one new release`, true);
  const body = {
    courses: courses.map((course) => ({ id: course.id, expectedRevision: course.revision })), note: requireOption(context.args, "note"),
    ...(flag(context.args, "allow-orphan") ? { allowOrphan: true } : {}),
  } satisfies BodyOf<"POST /courses/publish-batch">;
  const result = await context.client.call("POST /courses/publish-batch", { body });
  const { release } = result.data;
  context.out.lines([
    `${release.created ? `Published ${String(courses.length)} course(s)` : "Nothing changed (noop)"}: release #${String(release.number)} sha256 ${release.sha}`,
    ...diffLines(result.data.diff),
    ...(release.created && previous !== null ? [`Roll back the whole batch with: tower-catalog release activate ${String(previous)} --target ${context.target}`] : []),
  ]);
  context.out.result(result.envelope);
  await verifyActivation(context, release.number, previous, courses.map((course) => course.slug));
}

/** A classification file: CSV with a header naming `course` and `area_id` and/or `subarea_id`, or a JSON array. Empty keeps, `null` clears. */
export function parseClassifyFile(text: string, file: string): { course: string; areaId?: string; subareaId?: string | null }[] {
  const trimmed = text.trim();
  if (trimmed === "") throw new UsageError(`${file} is empty.`);
  const slug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const check = (value: string, label: string, line: number) => { if (!slug.test(value)) throw new UsageError(`${file}:${String(line)}: ${label} ${JSON.stringify(value)} is not an id.`); return value; };
  let entries: { course: string; areaId?: string; subareaId?: string | null }[];
  if (trimmed.startsWith("[")) {
    let parsed: unknown;
    try { parsed = JSON.parse(trimmed); } catch { throw new UsageError(`${file} is not valid JSON.`); }
    if (!Array.isArray(parsed)) throw new UsageError(`${file} must be a JSON array.`);
    entries = parsed.map((raw, index) => {
      const entry = raw as { course?: unknown; areaId?: unknown; subareaId?: unknown };
      if (typeof entry.course !== "string" || entry.course === "") throw new UsageError(`${file}[${String(index)}]: course is required.`);
      if (entry.areaId !== undefined && typeof entry.areaId !== "string") throw new UsageError(`${file}[${String(index)}]: areaId must be a string.`);
      if (entry.subareaId !== undefined && entry.subareaId !== null && typeof entry.subareaId !== "string") throw new UsageError(`${file}[${String(index)}]: subareaId must be a string or null.`);
      return {
        course: entry.course, ...(entry.areaId === undefined ? {} : { areaId: check(entry.areaId, "areaId", index + 1) }),
        ...(entry.subareaId === undefined ? {} : { subareaId: entry.subareaId === null ? null : check(entry.subareaId, "subareaId", index + 1) }),
      };
    });
  } else {
    const lines = trimmed.split(/\r?\n/);
    const header = (lines[0] ?? "").split(",").map((cell) => cell.trim());
    const at = (name: string) => header.indexOf(name);
    if (at("course") === -1 || (at("area_id") === -1 && at("subarea_id") === -1)) throw new UsageError(`${file}: the header needs course and area_id and/or subarea_id.`);
    entries = lines.slice(1).map((line, index) => ({ line, number: index + 2 })).filter(({ line }) => line.replace(/#.*$/, "").trim() !== "").map(({ line, number }) => {
      const cells = line.split(",").map((cell) => cell.trim());
      const course = cells[at("course")] ?? "";
      if (course === "") throw new UsageError(`${file}:${String(number)}: course is empty.`);
      const area = at("area_id") === -1 ? "" : cells[at("area_id")] ?? "";
      const subarea = at("subarea_id") === -1 ? "" : cells[at("subarea_id")] ?? "";
      return {
        course, ...(area === "" ? {} : { areaId: check(area, "area_id", number) }),
        ...(subarea === "" ? {} : { subareaId: subarea === "null" ? null : check(subarea, "subarea_id", number) }),
      };
    });
  }
  entries = entries.filter((entry) => entry.areaId !== undefined || entry.subareaId !== undefined);
  if (entries.length === 0) throw new UsageError(`${file} sets nothing.`);
  const courses = entries.map((entry) => entry.course);
  const twice = courses.filter((course, index) => courses.indexOf(course) !== index);
  if (twice.length) throw new UsageError(`${file} names ${[...new Set(twice)].join(", ")} more than once.`);
  return entries;
}
