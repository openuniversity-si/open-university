import { readdirSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { batchV2Hash, chunkBatchV2, type ApplyBatchData, type ApplyBatchReport } from "../../../../src/catalog/domain/batch-v2.ts";
import { batchFromBundlesV1, type V1Entry } from "../../../../src/catalog/domain/batch-convert.ts";
import { validateCourseBundle } from "../../../../src/catalog/domain/bundle.ts";
import { MAX_BODY_BYTES } from "../../../../src/catalog/domain/contracts.ts";
import { catalogBatchV2Schema, taxonomyCoverEntries, type CatalogBatchV2 } from "../../../../src/catalog/domain/schema/batch-v2.ts";
import { assertWithinBudget, MEDIA_BYTE_BUDGETS } from "../../../../src/media/domain/budget.ts";
import { objectKey } from "../../../../src/media/domain/objects.ts";
import { mediaContentType, type MediaKind } from "../../../../src/media/domain/types.ts";
import type { AdminEnvironment } from "../../../../src/admin/ports/jobs.ts";
import { stringOption } from "../args.ts";
import type { ApiClient, PreparedMedia } from "../client.ts";
import type { Context } from "../context.ts";
import { CliError, EXIT, UsageError, type ExitCode } from "../errors.ts";
import { prepareMedia } from "./covers.ts";
import { mediaKeyFor, type MediaIntent } from "./media.ts";

/** Room for the apply envelope (hash, chunk indexes, dryRun) around one part. */
const PART_BUDGET = MAX_BODY_BYTES - 1024;
const CHECK_LIMIT = 100;
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp", ".avif"]);

function environmentsOf(value: string): readonly AdminEnvironment[] {
  if (value === "both") return ["preview", "prod"];
  if (value === "preview" || value === "prod") return [value];
  throw new UsageError("--to must be preview, prod or both.");
}

function clientOf(context: Context, environment: AdminEnvironment): ApiClient {
  const own: AdminEnvironment = context.target === "prod" ? "prod" : "preview";
  return environment === own ? context.client : context.clientFor(environment);
}

function extensionOf(value: string): PreparedMedia["extension"] | null {
  return value === "jpg" || value === "png" || value === "webp" || value === "avif" ? value : null;
}

function remember(rows: { sha: string; kind: MediaKind }[], sha: string | null | undefined, kind: string): void {
  if (typeof sha !== "string") return;
  if (!(kind in MEDIA_BYTE_BUDGETS)) throw new UsageError(`Cover kind ${kind} has no byte budget.`);
  rows.push({ sha, kind: kind as MediaKind });
}

/** Every cover the batch declares, for every owner. One sha may appear as more than one kind. */
export function declaredCovers(batch: CatalogBatchV2): { sha: string; kind: MediaKind }[] {
  const rows: { sha: string; kind: MediaKind }[] = [];
  for (const item of batch.institutions) {
    remember(rows, item.cover.poster, "poster_9x16");
    remember(rows, item.cover.og, "og");
  }
  for (const item of batch.areas) for (const cover of taxonomyCoverEntries("area", item.cover)) if (cover.allowed) remember(rows, cover.sha, cover.kind);
  for (const item of batch.subareas) for (const cover of taxonomyCoverEntries("subarea", item.cover)) if (cover.allowed) remember(rows, cover.sha, cover.kind);
  for (const row of batch.homeRows) {
    remember(rows, row.cover.sha, "university_cover_9x16");
    remember(rows, row.og, "og");
  }
  for (const item of batch.courses) for (const cover of item.covers) remember(rows, cover.sha, cover.kind);
  return rows;
}

function shasOf(batch: CatalogBatchV2): string[] {
  return [...new Set(declaredCovers(batch).map((cover) => cover.sha))].sort();
}

/** The strictest declared budget for this sha, so a shared file is checked against every kind it is used as. */
export function strictestKind(batch: CatalogBatchV2, sha: string): MediaKind {
  const kinds = declaredCovers(batch).filter((cover) => cover.sha === sha).map((cover) => cover.kind);
  const first = kinds[0];
  if (!first) throw new UsageError(`No cover kind for ${sha}.`);
  return kinds.reduce((strict, kind) => MEDIA_BYTE_BUDGETS[kind] < MEDIA_BYTE_BUDGETS[strict] ? kind : strict);
}

function joinPath(dir: string, name: string): string {
  return `${dir.replace(/\/$/, "")}/${name}`;
}

function imageFiles(directory: string): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir).sort()) {
      const path = joinPath(dir, name);
      const info = statSync(path);
      if (info.isDirectory()) walk(path);
      else if (IMAGE_EXTENSIONS.has(name.slice(name.lastIndexOf(".")).toLowerCase())) found.push(path);
    }
  };
  walk(directory);
  return found;
}

/** Content addresses of the images next to a batch. The sha is the bytes `prepareMedia` stores, not the file on disk. */
export async function bytesBeside(directory: string): Promise<Map<string, PreparedMedia>> {
  const files = new Map<string, PreparedMedia>();
  for (const path of imageFiles(directory)) {
    const media = await prepareMedia(path);
    const extension = extensionOf(media.extension);
    if (!extension) throw new UsageError(`${path} is not a JPEG, PNG, WebP or AVIF.`);
    files.set(media.sha256, {
      bytes: media.bytes, sha256: media.sha256, extension, contentType: mediaContentType(`file.${extension}`), width: media.width, height: media.height,
    });
  }
  return files;
}

function coverFile(bundleFile: string, relativePath: string): string {
  const root = resolve(bundleFile, "..");
  const full = resolve(root, relativePath);
  if (full !== root && !full.startsWith(`${root}${sep}`)) throw new UsageError(`Cover ${relativePath} leaves the bundle directory.`);
  return full;
}

/** A directory of CourseBundleV1 files as one CatalogBatchV2. Institution facts come from the bundles, never from GET /home. */
export async function batchFromDirectory(context: Context, directory: string): Promise<{ batch: CatalogBatchV2; files: Map<string, PreparedMedia> }> {
  const names = readdirSync(directory).filter((name) => name.endsWith(".json")).sort();
  const failures: string[] = [];
  const entries: V1Entry[] = [];
  const files = new Map<string, PreparedMedia>();
  for (const name of names) {
    const path = joinPath(directory, name);
    let bundle;
    try {
      const parsed = validateCourseBundle(JSON.parse(context.readText(path)) as unknown);
      if (!parsed.ok) { failures.push(`${path}: ${parsed.error.message}`); continue; }
      bundle = parsed.value;
    } catch (error) {
      failures.push(`${path}: ${error instanceof Error ? error.message : "unreadable"}`);
      continue;
    }
    const coverShas: Record<string, string> = {};
    for (const cover of bundle.covers) {
      try {
        const media = await prepareMedia(coverFile(path, cover.path));
        const extension = extensionOf(media.extension);
        if (!extension) throw new UsageError(`Cover ${cover.kind} is not a JPEG, PNG, WebP or AVIF.`);
        assertWithinBudget(cover.kind, media.bytes.length, false);
        coverShas[cover.kind] = media.sha256;
        files.set(media.sha256, {
          bytes: media.bytes, sha256: media.sha256, extension, contentType: mediaContentType(`file.${extension}`), width: media.width, height: media.height,
        });
      } catch (error) {
        failures.push(`${path}: ${error instanceof Error ? error.message : "cover invalid"}`);
      }
    }
    entries.push({ file: path, bundle, coverShas });
  }
  if (names.length === 0) failures.push("The directory has no bundle.");
  const converted = failures.length > 0 ? { ok: false as const, failures } : batchFromBundlesV1(entries, new Map());
  if (!converted.ok) throw new UsageError(`${String(converted.failures.length)} bundle(s) cannot ship; nothing was sent.\n${converted.failures.join("\n")}`);
  return { batch: converted.batch, files };
}

async function missingShas(client: ApiClient, shas: readonly string[]): Promise<Set<string>> {
  const missing = new Set<string>();
  for (let index = 0; index < shas.length; index += CHECK_LIMIT) {
    const slice = shas.slice(index, index + CHECK_LIMIT);
    const check = await client.adminCall({
      routeId: "media:POST /check", params: {}, query: {}, stage: true,
      payload: { kind: "json", value: { sha256: slice } },
    }, (raw) => {
      const value = raw as { missing?: unknown };
      if (!Array.isArray(value.missing)) throw new Error("Media check did not return missing.");
      return value.missing.map(String);
    });
    for (const sha of check.data) missing.add(sha);
  }
  return missing;
}

async function stageBytes(context: Context, client: ApiClient, environment: AdminEnvironment, batch: CatalogBatchV2, files: ReadonlyMap<string, PreparedMedia>): Promise<void> {
  const shas = shasOf(batch);
  if (shas.length === 0) return;
  if (context.target === "staging") throw new UsageError("Ship uploads covers on preview or prod.");
  const missing = await missingShas(client, shas);
  for (const sha of shas) {
    if (!missing.has(sha)) continue;
    const file = files.get(sha);
    if (!file) throw new UsageError(`No local file for cover ${sha}.`);
    const kind = strictestKind(batch, sha);
    assertWithinBudget(kind, file.bytes.length, false);
    const intent: MediaIntent = { target: environment, owner: "course", ownerId: "ship", kind, variant: "default", alt: "ship", forceOversize: false };
    const uploaded = await client.adminCall({
      routeId: "media:POST /objects", params: {}, query: {}, stage: true,
      payload: { kind: "multipart", file, fields: { sha256: sha } },
      idempotencyKey: mediaKeyFor("media:POST /objects", intent, sha),
    }, (raw) => {
      const value = raw as { sha256?: unknown; pathname?: unknown };
      return { sha256: typeof value.sha256 === "string" ? value.sha256 : "", pathname: typeof value.pathname === "string" ? value.pathname : "" };
    });
    if (uploaded.data.sha256 !== sha || (uploaded.data.pathname !== "" && uploaded.data.pathname !== objectKey(sha, file.extension))) {
      throw new UsageError(`Media API returned a different object for ${sha}.`);
    }
  }
}

function planText(plan: ApplyBatchReport["plan"]): string {
  const parts: string[] = [];
  for (const step of Object.keys(plan).sort()) {
    const actions = plan[step] ?? {};
    for (const action of Object.keys(actions).sort()) parts.push(`${step}.${action}=${String(actions[action])}`);
  }
  return parts.join(" ");
}

/** scripts/site-health.ts of this app, run with this Node. It never prints a database URL. */
async function siteHealthCommand(context: Context, args: readonly string[], exitCode: ExitCode): Promise<void> {
  const result = await context.deps.run(process.execPath, ["scripts/site-health.ts", ...args], { cwd: context.deps.appRoot });
  if (result.code !== 0) throw new CliError((result.stderr || result.stdout || "site-health failed").trim(), exitCode);
}

/** Production is refused until rehearsal recorded a passing report for this batch (D-038). */
function requireSiteHealth(context: Context, hash: string): Promise<void> {
  return siteHealthCommand(context, ["--require", hash], EXIT.preconditions);
}

/** After the preview ship, measure the preview (staging) database and record the report for this batch sha. */
function rehearseSiteHealth(context: Context, hash: string): Promise<void> {
  return siteHealthCommand(context, ["--clone", "--batch-sha", hash, "--target", "staging"], EXIT.api);
}

function reportLine(data: ApplyBatchReport, environment: string): string {
  const release = data.release ? String(data.release.number) : "none";
  const plan = planText(data.plan);
  return `ship ${data.batchHash.slice(0, 12)} ${environment} ${data.status} courses=${String(data.courses.length)} release=${release}${data.release?.created === false ? " existing" : ""}${plan === "" ? "" : ` ${plan}`}`;
}

/**
 * Upload the missing cover bytes, then POST /batches/apply. Nothing else is sent. `--dry-run` posts `dryRun: true`
 * and prints the server report; the bytes stay, because the rolled-back transaction attaches them by sha.
 */
export async function shipPreparedBatch(context: Context, batch: CatalogBatchV2, files: ReadonlyMap<string, PreparedMedia>): Promise<void> {
  const target = stringOption(context.args, "to");
  if (!target) throw new UsageError("--to is required.");
  const environments = environmentsOf(target);
  const hash = batchV2Hash(batch);
  const parts = chunkBatchV2(batch, PART_BUDGET);
  const draft = context.args.options.draft === true;
  const note = typeof context.args.options.note === "string" ? context.args.options.note : undefined;
  await context.confirm(`Ship ${hash.slice(0, 12)} (${String(batch.courses.length)} course(s)) to ${target}${context.dryRun ? " as a dry run" : ""}.`, environments.includes("prod"));
  let envelope: unknown;
  for (const environment of environments) {
    if (environment === "prod" && !context.dryRun) await requireSiteHealth(context, hash);
    const client = clientOf(context, environment);
    await stageBytes(context, client, environment, batch, files);
    let data: ApplyBatchReport | undefined;
    for (const [index, part] of parts.entries()) {
      const result = await client.call("POST /batches/apply", {
        body: { batchHash: hash, chunk: index, chunks: parts.length, dryRun: context.dryRun, draft, ...(note ? { note } : {}), part },
      });
      const reply = result.data as ApplyBatchData;
      if (reply.status === "partial") continue;
      data = reply;
      envelope = result.envelope;
      break;
    }
    if (!data) throw new UsageError(`Batch ${hash.slice(0, 12)} stayed partial after ${String(parts.length)} chunk(s).`);
    context.out.line(reportLine(data, environment));
    if (environment === "preview" && !context.dryRun && data.status === "committed") await rehearseSiteHealth(context, hash);
  }
  if (envelope !== undefined) context.out.result(envelope);
}

export async function shipBundleDirectory(context: Context, directory: string): Promise<void> {
  const { batch, files } = await batchFromDirectory(context, directory);
  await shipPreparedBatch(context, batch, files);
}

export async function shipBatchFile(context: Context, path: string): Promise<void> {
  const parsed = catalogBatchV2Schema.safeParse(JSON.parse(context.readText(path)) as unknown);
  if (!parsed.success) throw new UsageError(parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "));
  const directory = resolve(path, "..");
  await shipPreparedBatch(context, parsed.data, await bytesBeside(directory));
}

export function isCatalogBatchFile(context: Context, path: string): boolean {
  try {
    if (!statSync(path).isFile()) return false;
    const parsed = JSON.parse(context.readText(path)) as { version?: unknown };
    return parsed.version === 2;
  } catch {
    return false;
  }
}
