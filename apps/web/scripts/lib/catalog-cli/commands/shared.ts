import type { z } from "zod";
import { fieldValues, flag, stringOption, type ParsedArgs } from "../args.ts";
import { issueList } from "../client.ts";
import { parseJsonFile, type Context } from "../context.ts";
import { ApiError, CliError, EXIT, UsageError } from "../errors.ts";
import { COURSE_LIST_LIMIT, REDIRECT_LIST_LIMIT } from "../../../../src/catalog/domain/contracts.ts";
import type { CourseDetail, CourseRow, Redirect, ReleaseRow } from "../responses.ts";
import type { DryRunRelease } from "../responses.ts";
export type { DryRunRelease, Publication, ReleaseRow } from "../responses.ts";


/** `POST /releases?dryRun=true`: what the next compile changes against the active release; writes nothing. */
export async function releaseDryRun(context: Context): Promise<{ data: DryRunRelease; envelope: unknown }> {
  const result = await context.client.call("POST /releases", { query: { dryRun: "true" } });
  if ("release" in result.data) throw new CliError("POST /releases?dryRun=true answered a publication; refusing to go on.", EXIT.api);
  return { data: result.data, envelope: result.envelope };
}

export async function getCourse(context: Context, id: string): Promise<CourseDetail> {
  return (await context.client.call("GET /courses/:id", { params: { id } })).data;
}

/** Every course matching `filter`, one page at a time. Stops when `nextCursor` is absent. */
export async function listAllCourses(context: Context, filter: { readonly status?: string } = {}): Promise<CourseRow[]> {
  const courses: CourseRow[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 200; page += 1) {
    const result = await context.client.call("GET /courses", {
      query: { ...(filter.status === undefined ? {} : { status: filter.status }), limit: String(COURSE_LIST_LIMIT), ...(cursor === undefined ? {} : { cursor }) },
    });
    courses.push(...result.data.courses);
    const next = result.data.nextCursor;
    if (typeof next !== "string" || next.length === 0) return courses;
    if (next === cursor) throw new CliError("GET /courses repeated a cursor.", EXIT.api);
    cursor = next;
  }
  throw new CliError("GET /courses did not finish.", EXIT.api);
}

/** Every redirect, one keyset page at a time. Stops when `nextCursor` is absent. */
export async function listAllRedirects(context: Context): Promise<Redirect[]> {
  const redirects: Redirect[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 200; page += 1) {
    const result = await context.client.call("GET /redirects", {
      query: { limit: String(REDIRECT_LIST_LIMIT), ...(cursor === undefined ? {} : { cursor }) },
    });
    redirects.push(...result.data.redirects);
    const next = result.data.nextCursor;
    if (typeof next !== "string" || next.length === 0) return redirects;
    if (next === cursor) throw new CliError("GET /redirects repeated a cursor.", EXIT.api);
    cursor = next;
  }
  throw new CliError("GET /redirects did not finish.", EXIT.api);
}

export async function listReleases(context: Context): Promise<ReleaseRow[]> {
  return (await context.client.call("GET /releases")).data.releases;
}

/**
 * The fields a set command changes: `--kebab value` options and `--file <json>` (an object of the same fields); one field
 * in both is a usage error. Validated against the route's schema before anything is sent; `allowEmpty` when the caller adds one.
 */
export function patchFields(context: Context, schema: z.ZodType, args: ParsedArgs, allowEmpty = false): Record<string, unknown> {
  const fromOptions = fieldValues(schema, args, ["expectedRevision"]);
  const file = stringOption(args, "file");
  let fromFile: Record<string, unknown> = {};
  if (file !== undefined) {
    const parsed = parseJsonFile(context, file);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new UsageError(`${file} must hold a JSON object of fields.`);
    fromFile = parsed as Record<string, unknown>;
    if ("expectedRevision" in fromFile) throw new UsageError(`${file}: leave expectedRevision out; the CLI reads it right before the change.`);
    const both = Object.keys(fromFile).filter((key) => key in fromOptions);
    if (both.length) throw new UsageError(`Given both in ${file} and as options: ${both.join(", ")}.`);
  }
  const fields = { ...fromFile, ...fromOptions };
  if (Object.keys(fields).length === 0) {
    // The caller adds a field of its own (lesson set --edition), validated with it below.
    if (allowEmpty) return fields;
    throw new UsageError("Name at least one field to change (an option or --file).");
  }
  const check = schema.safeParse({ ...fields, expectedRevision: 1 });
  if (!check.success) throw new UsageError(`Invalid change: ${issueList(check.error.issues)}`);
  return fields;
}

/**
 * Read-modify-write with one safe retry: on 409 revision_conflict the entity is read again and, if nobody else changed
 * the fields this command sets, the PATCH is sent once more with the new revision. Otherwise exit 3 with the fields.
 */
export async function patchWithRetry<T>(context: Context, fields: Record<string, unknown>, read: () => Promise<{ revision: number; values: Record<string, unknown> }>, send: (revision: number) => Promise<T>): Promise<T> {
  const first = await read();
  try {
    return await send(first.revision);
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "revision_conflict") throw error;
    const again = await read();
    const touched = Object.keys(fields).filter((key) => JSON.stringify(first.values[key]) !== JSON.stringify(again.values[key]));
    if (touched.length > 0) throw new CliError(`Revision changed to ${String(again.revision)} and someone else changed ${touched.join(", ")}; nothing was sent again. Review and re-run.`, EXIT.conflict);
    context.out.note(`Revision changed (${String(first.revision)} → ${String(again.revision)}) without touching these fields; retrying once.`);
    return send(again.revision);
  }
}

/** Waits for /api/health to serve release `number` (the activation revalidates the catalog tag; a few seconds at most). */
export async function verifyActivation(context: Context, number: number, rollbackTo: number | null, courses: readonly string[] = []): Promise<void> {
  const rollback = rollbackTo === null ? "" : ` Roll back with: tower-catalog release activate ${String(rollbackTo)} --target ${context.target}`;
  const active = (await listReleases(context)).find((release) => release.isActive);
  if (active?.number !== number) throw new CliError(`Post-check: GET /releases shows #${String(active?.number ?? "none")} active, not #${String(number)}.${rollback}`, EXIT.api);
  // Bound URLs for large batches: 20 maximum-length course slugs stay below the edge's URL limit.
  const groups = courses.length ? Array.from({ length: Math.ceil(courses.length / 20) }, (_, index) => courses.slice(index * 20, (index + 1) * 20)) : [[]];
  for (const group of groups) {
    let served: number | null = null;
    let present = false;
    const query = new URLSearchParams(group.map((slug) => ["course", slug])).toString();
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const response = await context.client.publicGet(`/api/health${query ? `?${query}` : ""}`);
      try {
        const health = JSON.parse(response.text) as { catalog?: { release?: number }; courses?: { slug: string; present: boolean }[] };
        served = health.catalog?.release ?? null;
        present = response.status === 200 && group.every((slug) => health.courses?.some((course) => course.slug === slug && course.present));
      } catch { served = null; present = false; }
      if (served === number && present) break;
      if (attempt < 4) await context.deps.sleep(2000);
    }
    if (served !== number) throw new CliError(`Post-check: /api/health serves release #${String(served ?? "?")}, not #${String(number)}.${rollback}`, EXIT.api);
    if (!present) throw new CliError(`Post-check: /api/health did not confirm courses in release #${String(number)}: ${group.join(", ")}.${rollback}`, EXIT.api);
  }
  context.out.line(`Verified: release #${String(number)} is active and /api/health serves it${courses.length ? ` with ${String(courses.length)} course(s)` : ""}.`);
}

const REFERENCE_BATCH = 5000;

/**
 * The byte part of a purge or delete query. The R2 bucket is shared by preview and prod, and a server sees only its own
 * database, so by default every byte is kept. With `--delete-bytes`, the candidate keys (no other row of this
 * database uses them) are checked on every peer environment (POST /media/references); bytes go only when no peer uses
 * any of them and every peer answered. Anything else keeps them all, with a note (the objects stay for the GC).
 */
export async function bytesQuery(context: Context, report: Readonly<Record<string, unknown>> | undefined): Promise<{ deleteBytes?: "true"; checkedKeys?: string }> {
  const candidates = Array.isArray(report?.r2Candidates) ? report.r2Candidates.filter((key): key is string => typeof key === "string") : [];
  if (!flag(context.args, "delete-bytes") || candidates.length === 0) return {};
  let peers;
  try { peers = context.peers(); } catch (error) {
    context.out.note(`Could not reach the other environment (${error instanceof Error ? error.message : "unknown error"}); keeping every R2 byte.`);
    return {};
  }
  for (const peer of peers) {
    const used: string[] = [];
    try {
      for (let start = 0; start < candidates.length; start += REFERENCE_BATCH) {
        used.push(...(await peer.client.call("POST /media/references", { body: { keys: candidates.slice(start, start + REFERENCE_BATCH) } })).data.used);
      }
    } catch (error) {
      context.out.note(`Could not check ${peer.target} (${error instanceof Error ? error.message : "unknown error"}); keeping every R2 byte.`);
      return {};
    }
    if (used.length > 0) {
      context.out.note(`${peer.target} still uses ${String(used.length)} of these key(s) (${used.slice(0, 3).join(", ")}${used.length > 3 ? ", …" : ""}); keeping every R2 byte.`);
      return {};
    }
  }
  context.out.note(`No other environment (${peers.map((peer) => peer.target).join(", ")}) uses the ${String(candidates.length)} candidate key(s): their R2 bytes go after the commit.`);
  return { deleteBytes: "true", checkedKeys: JSON.stringify(candidates) };
}
