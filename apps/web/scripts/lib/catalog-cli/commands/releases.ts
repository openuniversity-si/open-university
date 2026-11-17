import { homePut } from "../../../../src/catalog/domain/contracts.ts";
import type { PublicCatalog } from "../../../../src/catalog/domain/release.ts";
import { diffReleases, type ReleaseDiff } from "../../../../src/catalog/server/releases.ts";
import { positional, requireOption, stringOption } from "../args.ts";
import { issueList } from "../client.ts";
import { parseJsonFile, type CommandSpec, type Context } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";
import { diffLines, orDash, shortSha, table } from "../render.ts";
import { listReleases, releaseDryRun, verifyActivation } from "./shared.ts";
import type { HomeData } from "../responses.ts";


function releaseNumber(value: string, name: string): number {
  if (!/^[1-9]\d{0,8}$/.test(value)) throw new UsageError(`<${name}> must be a release number.`);
  return Number(value);
}

async function releasePayload(context: Context, number: number): Promise<PublicCatalog> {
  return (await context.client.call("GET /releases/:n", { params: { n: String(number) } })).data.release.payload;
}

/** Home as rows of `id kind title [courses]`, the way home get prints and home set compares it. */
function homeLines(home: Pick<HomeData, "featuredCourseId" | "rows">): string[] {
  return [`featured ${orDash(home.featuredCourseId)}`, ...home.rows.map((row, index) => `${String(index + 1)}. ${row.id} (${row.kind}${!row.visible ? ", hidden" : ""}) ${row.title ?? row.authorId ?? ""} [${row.courseIds.join(", ")}]`.replace(/\s+\[/, " ["))];
}

/** What `home set` changes, line by line (rows added, removed, moved or edited, and the featured course). */
export function homeDiff(before: Pick<HomeData, "featuredCourseId" | "rows">, after: Pick<HomeData, "featuredCourseId" | "rows">): string[] {
  const lines: string[] = [];
  if (before.featuredCourseId !== after.featuredCourseId) lines.push(`  featured: ${orDash(before.featuredCourseId)} → ${orDash(after.featuredCourseId)}`);
  const old = new Map(before.rows.map((row, index) => [row.id, { row, index }]));
  const now = new Map(after.rows.map((row, index) => [row.id, { row, index }]));
  for (const [id, { row }] of now) if (!old.has(id)) lines.push(`  + row ${id} (${row.kind}) [${row.courseIds.join(", ")}]`);
  for (const [id] of old) if (!now.has(id)) lines.push(`  - row ${id}`);
  for (const [id, { row, index }] of now) {
    const previous = old.get(id);
    if (!previous) continue;
    const changes: string[] = [];
    if (previous.index !== index) changes.push(`position ${String(previous.index + 1)} → ${String(index + 1)}`);
    if (previous.row.title !== row.title) changes.push(`title ${orDash(previous.row.title)} → ${orDash(row.title)}`);
    if (previous.row.visible !== row.visible) changes.push(`visible ${String(previous.row.visible)} → ${String(row.visible)}`);
    if (previous.row.authorId !== row.authorId) changes.push(`author ${orDash(previous.row.authorId)} → ${orDash(row.authorId)}`);
    // 0013: omitted keeps the current value (PUT /home semantics), so only a given one can differ.
    if (row.fullName !== undefined && (previous.row.fullName ?? null) !== row.fullName) changes.push(`full name ${orDash(previous.row.fullName ?? null)} → ${orDash(row.fullName)}`);
    if (row.place !== undefined && (previous.row.place ?? null) !== row.place) changes.push(`place ${orDash(previous.row.place ?? null)} → ${orDash(row.place)}`);
    if (previous.row.courseIds.join(",") !== row.courseIds.join(",")) changes.push(`courses [${previous.row.courseIds.join(", ")}] → [${row.courseIds.join(", ")}]`);
    if (changes.length) lines.push(`  ~ row ${id}: ${changes.join("; ")}`);
  }
  return lines;
}

export const releaseCommands: CommandSpec[] = [
  {
    name: "release list", usage: "release list", summary: "every release, newest first (* = active)", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /releases"],
    async run(context) {
      const result = await context.client.call("GET /releases");
      context.out.lines(table(["#", "sha256", "created", "by", "note"], result.data.releases.map((release) => [`${String(release.number)}${release.isActive ? "*" : ""}`, shortSha(release.sha), release.createdAt, release.createdBy, release.note])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "release diff", usage: "release diff [a] [b]", summary: "no argument: active vs. the current tables (dry run); a: a vs. active; a b: a vs. b",
    options: {}, positionals: { min: 0, max: 2 }, routes: ["POST /releases", "GET /releases", "GET /releases/:n"],
    async run(context) {
      const [a, b] = context.args.positionals;
      if (a === undefined) {
        const result = await releaseDryRun(context);
        if (!result.data.valid) throw new CliError(`The current tables do not compile into a release:\n  ${result.data.errors.join("\n  ")}`, EXIT.api);
        context.out.lines(["Active release → current tables (what the next publish would add):", ...diffLines(result.data.diff)]);
        context.out.result(result.envelope);
        return;
      }
      const from = releaseNumber(a, "a");
      const to = b === undefined ? (await listReleases(context)).find((release) => release.isActive)?.number : releaseNumber(b, "b");
      if (to === undefined) throw new UsageError("There is no active release to compare with.");
      const diff: ReleaseDiff = diffReleases(await releasePayload(context, from), await releasePayload(context, to));
      context.out.lines([`Release #${String(from)} → #${String(to)}:`, ...diffLines(diff)]);
      context.out.result({ ok: true, data: { from, to, diff } });
    },
  },
  {
    name: "release create", usage: "release create --note \"…\"", summary: "compile the tables into a new active release (what publish does without a course)",
    options: { note: { type: "string", required: true, help: "release note", value: "<text>" } }, positionals: { min: 0, max: 0 }, routes: ["GET /releases", "POST /releases"],
    async run(context) {
      const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
      const dry = await releaseDryRun(context);
      context.out.lines(["Active release → current tables:", ...diffLines(dry.data.diff)]);
      if (dry.data.unchanged === true) { context.out.line("Nothing to release: the compile equals the active release."); return; }
      await context.confirm("Create and activate a release from the current tables", true);
      const result = await context.client.call("POST /releases", { body: { note: requireOption(context.args, "note") }, state: { active: previous } });
      if (!("release" in result.data)) throw new CliError("POST /releases answered a dry-run report instead of a release.", EXIT.api);
      const { release, noop } = result.data;
      context.out.lines([`Release #${String(release.number)} sha256 ${release.sha}${noop ? " (noop)" : ""}.`, ...diffLines(result.data.diff)]);
      context.out.result(result.envelope);
      await verifyActivation(context, release.number, previous);
    },
  },
  {
    name: "release activate", usage: "release activate <n> [--note \"…\"]", summary: "make release n active (the rollback; prints the command that undoes it)",
    options: { note: { type: "string", help: "audit note (default: tower-catalog release activate <n>)", value: "<text>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /releases", "POST /releases/:n/activate"],
    async run(context) {
      const number = releaseNumber(positional(context.args, 0, "n"), "n");
      const releases = await listReleases(context);
      const active = releases.find((release) => release.isActive);
      if (!releases.some((release) => release.number === number)) throw new UsageError(`There is no release #${String(number)}.`);
      if (active?.number === number) { context.out.line(`Release #${String(number)} is already active; nothing sent.`); return; }
      await context.confirm(`Activate release #${String(number)} (active now: #${String(active?.number ?? "none")})`, true);
      const note = stringOption(context.args, "note") ?? `tower-catalog release activate ${String(number)}`;
      const result = await context.client.call("POST /releases/:n/activate", { params: { n: String(number) }, body: { note }, state: { active: active?.number ?? null, activatedAt: active?.activatedAt ?? null } });
      context.out.lines([`Release #${String(number)} is active (was #${String(result.data.previous ?? active?.number ?? "none")}).`, ...(active ? [`Undo: tower-catalog release activate ${String(active.number)} --target ${context.target}`] : [])]);
      context.out.result(result.envelope);
      await verifyActivation(context, number, active?.number ?? null);
    },
  },
];

export const homeCommands: CommandSpec[] = [
  {
    name: "home get", usage: "home get", summary: "the Home: featured course and rows (the format home set takes)", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /home"],
    async run(context) {
      const result = await context.client.call("GET /home");
      context.out.lines([`Home revision ${String(result.data.revision)}`, ...homeLines(result.data)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "home set", usage: "home set --file home.json", summary: "replace the Home (shows the diff, asks, creates a release)",
    options: { file: { type: "string", required: true, help: "{featuredCourseId, rows, note?} as PUT /home takes (expectedRevision is read for you)", value: "<path>" } },
    positionals: { min: 0, max: 0 }, routes: ["GET /home", "GET /releases", "PUT /home"],
    async run(context) {
      const file = requireOption(context.args, "file");
      const raw = parseJsonFile(context, file);
      if (raw === null || typeof raw !== "object" || Array.isArray(raw)) throw new UsageError(`${file} must hold the PUT /home object.`);
      const pinned = (raw as { expectedRevision?: unknown }).expectedRevision;
      const parsed = homePut.safeParse({ expectedRevision: 1, ...raw });
      if (!parsed.success) throw new UsageError(`${file} does not match PUT /home: ${issueList(parsed.error.issues)}`);
      const current = (await context.client.call("GET /home")).data;
      // The file is the desired state; expectedRevision is the one just read unless the file pins it.
      const desired = { ...parsed.data, expectedRevision: typeof pinned === "number" ? pinned : current.revision };
      const changes = homeDiff(current, { featuredCourseId: desired.featuredCourseId, rows: desired.rows.map((row, index) => ({ ...row, title: row.title ?? null, authorId: row.authorId ?? null, visible: row.visible ?? true, position: index + 1 })) });
      if (changes.length === 0) { context.out.line("The Home already matches the file; nothing sent."); return; }
      context.out.lines([`Home revision ${String(current.revision)} → ${file}:`, ...changes]);
      const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
      await context.confirm("Replace the Home (a new release when the published Home changes)", true);
      const result = await context.client.call("PUT /home", { body: desired });
      context.out.lines([`Home revision ${String(result.data.home.revision)}; release #${String(result.data.release.number)}${result.data.release.created ? " created" : " unchanged"}.`, ...diffLines(result.data.diff)]);
      context.out.result(result.envelope);
      await verifyActivation(context, result.data.release.number, previous);
    },
  },
];
