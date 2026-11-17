import { createHash } from "node:crypto";
import { mkdir, symlink, unlink } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { join } from "node:path";
import { MEDIA_BYTE_BUDGETS, assertWithinBudget } from "../../../../src/media/domain/budget.ts";
import { resolveCover } from "../../../../src/catalog/domain/cover-resolve.ts";
import "../../../../src/media/server/public-hosts.ts";
import { mediaPublicHost, type MediaKind } from "../../../../src/media/domain/types.ts";
import { flag, intOption, positional, stringOption } from "../args.ts";
import type { AdminClient, PreparedMedia } from "../client.ts";
import type { CommandSpec, Context } from "../context.ts";
import { CliError, EXIT, UsageError } from "../errors.ts";

export type MediaCommand = "put" | "object-put" | "list" | "rollback" | "delete" | "check" | "prune-inherited" | "install" | "migrate-content";
export interface MediaIntent {
  readonly target: "prod" | "preview";
  readonly owner: "institution" | "area" | "subarea" | "course" | "lesson";
  readonly ownerId: string;
  readonly kind: string;
  readonly variant: string;
  readonly alt: string;
  readonly forceOversize: boolean;
}
export interface MediaCliDeps {
  readonly client: AdminClient;
  readonly prepare: (input: string | Uint8Array) => Promise<PreparedMedia>;
  readonly confirm: (question: string) => Promise<void>;
  readonly keyFor: (route: string, intent: MediaIntent, sha256: string) => string;
  readonly readOnly?: boolean;
}
export interface UploadResult { readonly sha256: string; readonly url: string; readonly width: number; readonly height: number }

const MEDIA_ROUTES = [
  "media:GET /", "media:POST /check", "media:POST /objects", "media:POST /attach", "media:POST /rollback", "media:DELETE /", "media:POST /prune-inherited",
] as const;

/**
 * One Idempotency-Key per route and intent. `admin_idempotency.key` is global, so `/objects` and `/attach` for the
 * same cover must not share a key: the second would be refused as a different request (422).
 */
export function mediaKeyFor(route: string, intent: MediaIntent, sha256: string): string {
  return `m-${createHash("sha256").update(`${route}:${intent.target}:${intent.owner}:${intent.ownerId}:${intent.kind}:${intent.variant}:${sha256}`).digest("hex").slice(0, 32)}`;
}

function descriptor(media: PreparedMedia): UploadResult {
  return { sha256: media.sha256, url: `https://${mediaPublicHost(process.env)}/m/${media.sha256}.${media.extension}`, width: media.width, height: media.height };
}

const objectShape = (raw: unknown): { sha256: string; url?: string } => {
  const value = raw as { sha256?: unknown; url?: unknown } | null;
  if (value === null || typeof value.sha256 !== "string") throw new Error("Media object is missing sha256.");
  return { sha256: value.sha256, ...(typeof value.url === "string" ? { url: value.url } : {}) };
};

/** Check by SHA, upload only missing bytes, then optionally attach. Dry-run returns the descriptor and sends nothing. */
export async function uploadPrepared(deps: MediaCliDeps, input: { readonly media: PreparedMedia; readonly intent: MediaIntent; readonly dryRun: boolean; readonly attach: boolean }): Promise<UploadResult> {
  if (!input.intent.forceOversize) assertWithinBudget(input.intent.kind as MediaKind, input.media.bytes.length, false);
  const expected = descriptor(input.media);
  if (input.dryRun || deps.readOnly) return expected;
  await deps.confirm(`Upload ${input.intent.owner} ${input.intent.ownerId} ${input.intent.kind}/${input.intent.variant}`);
  const check = await deps.client.call({
    routeId: "media:POST /check", params: {}, query: {}, payload: { kind: "json", value: { sha256: [input.media.sha256] } },
  }, (raw) => {
    const value = raw as { missing?: unknown; objects?: unknown };
    if (!Array.isArray(value.missing) || !Array.isArray(value.objects)) throw new Error("Media check did not return missing and objects.");
    return { missing: value.missing.map(String), objects: value.objects.map(objectShape) };
  });
  if (check.data.missing.includes(input.media.sha256)) {
    const uploaded = await deps.client.call({
      routeId: "media:POST /objects", params: {}, query: {},
      payload: { kind: "multipart", file: input.media, fields: { sha256: input.media.sha256 } },
      idempotencyKey: deps.keyFor("media:POST /objects", input.intent, input.media.sha256),
    }, objectShape);
    if (uploaded.data.sha256 !== expected.sha256 || (uploaded.data.url !== undefined && uploaded.data.url !== expected.url)) throw new UsageError("Media API returned a different object.");
  } else {
    const found = check.data.objects.find((object) => object.sha256 === expected.sha256);
    if (found?.url !== undefined && found.url !== expected.url) throw new UsageError("Media API returned a different object.");
  }
  if (input.attach) {
    await deps.client.call({
      routeId: "media:POST /attach", params: {}, query: {},
      idempotencyKey: deps.keyFor("media:POST /attach", input.intent, input.media.sha256),
      payload: { kind: "json", value: { owner: input.intent.owner, ownerId: input.intent.ownerId, kind: input.intent.kind, variant: input.intent.variant, sha256: input.media.sha256, alt: input.intent.alt, forceOversize: input.intent.forceOversize } },
    }, objectShape);
  }
  return expected;
}

function ownerOf(context: Context): { owner: MediaIntent["owner"]; ownerId: string } {
  const ownerFlag = stringOption(context.args, "owner");
  const course = stringOption(context.args, "course");
  const lesson = stringOption(context.args, "lesson");
  const subarea = stringOption(context.args, "subarea");
  const chosen = [ownerFlag, course, lesson, subarea].filter((value) => value !== undefined);
  if (chosen.length !== 1) throw new UsageError("Pass exactly one of --course, --lesson, --subarea or --owner type:id.");
  if (ownerFlag) {
    const [owner, ownerId] = ownerFlag.split(":");
    if (!ownerId || (owner !== "course" && owner !== "lesson" && owner !== "subarea" && owner !== "area" && owner !== "institution")) throw new UsageError("--owner needs institution|area|subarea|course|lesson:id.");
    return { owner, ownerId };
  }
  if (course) return { owner: "course", ownerId: course };
  if (lesson) return { owner: "lesson", ownerId: lesson };
  return { owner: "subarea", ownerId: subarea ?? "" };
}

function targetOf(context: Context): "prod" | "preview" {
  if (context.target === "staging") throw new UsageError("Media commands accept prod or preview.");
  return context.target;
}

function clientOf(context: Context): AdminClient {
  const client = context.client;
  if (flag(context.args, "read-only-api")) client.readOnly = true;
  return { call: (input, decode) => client.adminCall(input, decode) };
}

export async function installTowerMedia(appRoot: string, home = process.env.HOME ?? ""): Promise<void> {
  const wrapper = realpathSync(join(appRoot, "tooling/tower-media"));
  const bin = join(home, ".local/bin");
  await mkdir(bin, { recursive: true });
  const link = join(bin, "tower-media");
  await unlink(link).catch(() => undefined);
  await symlink(wrapper, link);
}

export const mediaCommands: CommandSpec[] = [{
  name: "media",
  usage: "media <put|object-put|list|rollback|delete|check|prune-inherited|install|migrate-content>",
  summary: "covers and objects through the admin media API (the tower-media wrapper delegates here)",
  options: {
    course: { type: "string", help: "course id", value: "<id>" },
    lesson: { type: "string", help: "lesson id", value: "<id>" },
    subarea: { type: "string", help: "subarea id", value: "<id>" },
    owner: { type: "string", help: "institution|area|subarea|course|lesson:id", value: "<type:id>" },
    owners: { type: "string", help: "comma-separated type:id list, one request", value: "<type:id,...>" },
    kind: { type: "string", help: "media kind", value: "<kind>" },
    variant: { type: "string", help: "variant (default: default)", value: "<name>" },
    alt: { type: "string", help: "alt text", value: "<text>" },
    file: { type: "string", help: "image to prepare and upload", value: "<path>" },
    version: { type: "string", help: "version to roll back or delete", value: "<n>" },
    all: { type: "boolean", help: "list every version, including inactive" },
    "force-oversize": { type: "boolean", help: "upload past the kind budget" },
    budget: { type: "boolean", help: "check also lists active assets over their kind budget" },
    registry: { type: "boolean", help: "check --registry verifies content hashes (privileged)" },
    "read-only-api": { type: "boolean", help: "prune-inherited audit through GET only" },
    apply: { type: "boolean", help: "prune-inherited writes the plan" },
    report: { type: "string", help: "write the JSON report here", value: "<file>" },
  },
  positionals: { min: 1, max: 20 },
  routes: [...MEDIA_ROUTES, "GET /tables"],
  async run(context) {
    const verb = positional(context.args, 0, "media command") as MediaCommand;
    if (verb === "install") { await installTowerMedia(context.deps.appRoot, context.deps.home); context.out.line("installed ~/.local/bin/tower-media"); return; }
    if (verb === "migrate-content" || (verb === "check" && flag(context.args, "registry"))) {
      const { runContentMigration } = await import("./media-privileged.ts");
      const args = verb === "check" ? ["--target", targetOf(context), "--verify"] : [targetOf(context), ...context.args.positionals.slice(1)];
      const code = await runContentMigration(args, context.deps.appRoot);
      if (code !== 0) throw new CliError("migrate-content failed.", EXIT.api);
      return;
    }
    const known: readonly MediaCommand[] = ["put", "object-put", "list", "rollback", "delete", "check", "prune-inherited"];
    if (!known.includes(verb)) throw new UsageError(`Unknown media command ${verb}.`);
    const target = targetOf(context);
    const client = clientOf(context);
    const variant = stringOption(context.args, "variant") ?? "default";
    if (verb === "list" || verb === "check") {
      const query: Record<string, string> = {};
      const owners = stringOption(context.args, "owners");
      if (owners && verb !== "list") throw new UsageError("--owners is only for media list.");
      if (owners && (stringOption(context.args, "course") || stringOption(context.args, "lesson") || stringOption(context.args, "subarea") || stringOption(context.args, "owner"))) {
        throw new UsageError("--owners cannot be combined with --course, --lesson, --subarea or --owner.");
      }
      if (flag(context.args, "all") || verb === "check") query.all = "1";
      if (owners) query.owners = owners;
      else if (stringOption(context.args, "course") || stringOption(context.args, "lesson") || stringOption(context.args, "subarea") || stringOption(context.args, "owner")) {
        const owner = ownerOf(context);
        query.owner = owner.owner; query.ownerId = owner.ownerId;
      }
      const kind = stringOption(context.args, "kind");
      if (kind) query.kind = kind;
      if (stringOption(context.args, "variant")) query.variant = variant;
      const listed = await client.call({ routeId: "media:GET /", params: {}, query, payload: { kind: "none" } }, (raw) => raw as {
        versions?: { version: number; active?: boolean; ownerId: string; kind: string; variant: string; width: number; height: number; url: string; sha256?: string }[];
        assets?: { version: number; ownerId: string; kind: string; variant: string; width: number; height: number; url: string; sha256: string }[];
        owners?: { owner: string; ownerId: string; versions: { version: number; active?: boolean; ownerId: string; kind: string; variant: string; width: number; height: number; url: string; sha256?: string }[] }[];
      });
      if (verb === "list") {
        const line = (row: { version: number; active?: boolean; ownerId: string; kind: string; variant: string; width: number; height: number; url: string }) => `v${String(row.version)}${"active" in row ? row.active ? " *" : "  " : " *"} ${row.ownerId} ${row.kind}/${row.variant} ${String(row.width)}x${String(row.height)} ${row.url}`;
        if (listed.data.owners) {
          for (const group of listed.data.owners) {
            if (group.versions.length === 0) context.out.line(`${group.owner}:${group.ownerId} (none)`);
            else for (const row of group.versions) context.out.line(line(row));
          }
        } else {
          for (const row of listed.data.versions ?? listed.data.assets ?? []) context.out.line(line(row));
        }
        context.out.result(listed.data);
        return;
      }
      await verifyAssets(context, listed.data.assets ?? []);
      return;
    }
    if (verb === "prune-inherited") {
      if (flag(context.args, "apply") && flag(context.args, "dry-run")) throw new UsageError("use --dry-run or --apply");
      if (flag(context.args, "read-only-api")) {
        if (flag(context.args, "apply")) throw new UsageError("--read-only-api never applies a prune.");
        const tables = await context.client.call("GET /tables");
        const media = await client.call({ routeId: "media:GET /", params: {}, query: { all: "1" }, payload: { kind: "none" } }, (raw) => raw as { assets?: { ownerId: string; kind: string; variant: string; sha256: string; active?: boolean }[] });
        const count = redundantLessons((tables.data as { tables: { courses: { id: string; area_id?: string | null; subarea_id: string | null; cover_from?: string | null }[]; lessons: { id: string; course_id: string }[] } }).tables, media.data.assets ?? []);
        context.out.line(`DRY-RUN: ${String(count)} redundant lesson rows; R2 bytes kept`);
        return;
      }
      const apply = flag(context.args, "apply");
      if (apply) await context.confirm("Prune inherited lesson rows", true);
      const report = await client.call({ routeId: "media:POST /prune-inherited", params: {}, query: {}, payload: { kind: "json", value: { apply } }, idempotencyKey: mediaKeyFor("media:POST /prune-inherited", { target, owner: "course", ownerId: "prune", kind: "prune", variant: apply ? "apply" : "dry", alt: "", forceOversize: false }, "prune") }, (raw) => raw as { apply: boolean; count: number });
      context.out.line(`${report.data.apply ? "APPLY" : "DRY-RUN"}: ${String(report.data.count)} redundant lesson rows; R2 bytes kept`);
      return;
    }
    const owner = ownerOf(context);
    const kind = stringOption(context.args, "kind");
    if (!kind && verb !== "object-put") throw new UsageError(`${verb} needs --kind.`);
    if (verb === "put" || verb === "object-put") {
      const file = stringOption(context.args, "file");
      if (!file) throw new UsageError("a readable --file is required");
      const { prepareMedia } = await import("../../../../src/media/server/prepare.ts");
      const { mediaContentType } = await import("../../../../src/media/server/storage.ts");
      const prepared = await prepareMedia(file);
      const media: PreparedMedia = { bytes: prepared.bytes, sha256: prepared.sha256, extension: prepared.extension as PreparedMedia["extension"], contentType: mediaContentType(`file.${prepared.extension}`), width: prepared.width, height: prepared.height };
      const intent: MediaIntent = { target, ...owner, kind: kind ?? "poster_9x16", variant, alt: stringOption(context.args, "alt") ?? `${owner.ownerId} ${kind ?? "object"}`, forceOversize: flag(context.args, "force-oversize") };
      const result = await uploadPrepared({ client, prepare: () => Promise.resolve(media), confirm: (question) => context.confirm(question, true), keyFor: mediaKeyFor, readOnly: context.client.readOnly }, { media, intent, dryRun: context.dryRun, attach: verb === "put" });
      if (verb === "object-put") context.out.line(JSON.stringify(result));
      else context.out.line(`v ${owner.ownerId} ${intent.kind}/${variant} ${String(result.width)}x${String(result.height)} ${result.url}`);
      return;
    }
    if (verb === "rollback") {
      const version = intOption(context.args, "version");
      if (!version) throw new UsageError("rollback needs --version.");
      await context.confirm(`Roll back ${owner.owner} ${owner.ownerId} ${kind ?? ""}/${variant} to v${String(version)}`, true);
      const restored = await client.call({ routeId: "media:POST /rollback", params: {}, query: {}, idempotencyKey: mediaKeyFor("media:POST /rollback", { target, ...owner, kind: kind ?? "", variant, alt: "", forceOversize: false }, String(version)), payload: { kind: "json", value: { ...owner, kind, variant, version } } }, (raw) => raw as { version: number; url: string; width: number; height: number });
      context.out.line(`v${String(restored.data.version)} * ${owner.ownerId} ${kind ?? ""}/${variant} ${String(restored.data.width)}x${String(restored.data.height)} ${restored.data.url}`);
      return;
    }
    const version = intOption(context.args, "version");
    if (variant === "default" && version === undefined) throw new UsageError("the default variant is never deleted; pass --version N of an inactive version");
    const kindName = kind ?? "";
    const plan = await client.call({ routeId: "media:DELETE /", params: {}, query: {}, payload: { kind: "json", value: { ...owner, kind: kindName, variant, ...(version === undefined ? {} : { version }), apply: false } } }, (raw) => raw as { plan?: { key: string; willDeleteBytes: boolean }[] });
    if (!flag(context.args, "yes") && !context.dryRun) { renderDelete(context, plan.data); context.out.line("nothing changed; re-run with --yes to apply"); return; }
    let keepBytes = false;
    const keys = (plan.data.plan ?? []).filter((row) => row.willDeleteBytes).map((row) => row.key);
    if (keys.length) {
      try {
        const peer = context.peers()[0];
        if (!peer) keepBytes = true;
        else {
          const other = await peer.client.adminCall({ routeId: "media:GET /", params: {}, query: { ...owner, kind: kindName }, payload: { kind: "none" } }, (raw) => raw as { versions?: { url: string }[] });
          const used = (other.data.versions ?? []).map((row) => new URL(row.url).pathname.slice(1)).filter((key) => keys.includes(key));
          if (used.length) { keepBytes = true; context.out.note(`warning: the other target also uses ${used.join(" ")}; keeping R2 bytes`); }
        }
      } catch { keepBytes = true; context.out.note("warning: could not check the other target; keeping R2 bytes"); }
    }
    await context.confirm(`Delete ${owner.owner} ${owner.ownerId} ${kindName}/${variant}`, true);
    const applied = await client.call({ routeId: "media:DELETE /", params: {}, query: {}, idempotencyKey: mediaKeyFor("media:DELETE /", { target, ...owner, kind: kindName, variant, alt: keepBytes ? "keep" : "drop", forceOversize: false }, String(version ?? "all")), payload: { kind: "json", value: { ...owner, kind: kindName, variant, ...(version === undefined ? {} : { version }), apply: true, keepBytes } } }, (raw) => raw as { deleted?: { version: number; variant: string }[]; bytes?: { deleted: string[]; kept: { key: string; reason: string }[] }; activeAfter: { version: number; url: string } | null; alreadyAbsent?: boolean });
    renderDelete(context, applied.data);
  },
}];

function renderDelete(context: Context, data: { plan?: { version?: number; key: string; active?: boolean; willDeleteBytes: boolean; keepReason?: string }[]; deleted?: { version: number; variant: string }[]; bytes?: { deleted: string[]; kept: { key: string; reason: string }[] }; activeAfter?: { version: number; url: string } | null; alreadyAbsent?: boolean }): void {
  if (data.alreadyAbsent) context.out.line("already absent: nothing to delete");
  for (const row of data.plan ?? []) context.out.line(`DRY-RUN: would delete ${row.key} (${row.active ? "ACTIVE" : "inactive"}); R2 bytes: ${row.willDeleteBytes ? "delete" : `keep (${row.keepReason ?? "shared"})`}`);
  for (const row of data.deleted ?? []) context.out.line(`deleted v${String(row.version)} ${row.variant}`);
  for (const key of data.bytes?.deleted ?? []) context.out.line(`R2 deleted ${key}`);
  for (const kept of data.bytes?.kept ?? []) context.out.line(`R2 kept ${kept.key} (${kept.reason})`);
  if (data.activeAfter) context.out.line(`active now: v${String(data.activeAfter.version)} ${data.activeAfter.url}`);
}

/**
 * The public check hashes the body, so it downloads. Status and content-type come from that GET.
 * HEAD on the public media host is uncached and is not consulted.
 */
export async function checkPublicAsset(fetchPublic: (url: string, init?: RequestInit) => Promise<Response>, url: string): Promise<{ status: number; type: string; bytes: Uint8Array; hash: string }> {
  const response = await fetchPublic(url, { redirect: "error" }).catch(() => new Response(null, { status: 599 }));
  const type = response.headers.get("content-type")?.split(";")[0] ?? "";
  const bytes = new Uint8Array(await response.arrayBuffer());
  return { status: response.status, type, bytes, hash: response.ok ? createHash("sha256").update(bytes).digest("hex") : "" };
}
async function verifyAssets(context: Context, assets: readonly { version: number; ownerId: string; kind: string; variant: string; url: string; sha256: string }[]): Promise<void> {
  const fetchPublic = context.deps.fetchPublic ?? fetch;
  const types: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", avif: "image/avif" };
  let bad = 0;
  let over = 0;
  const checked = new Map<string, { hash: string; type: string; status: number; bytes: number }>();
  for (const asset of assets) {
    let verification = checked.get(asset.url);
    if (!verification) {
      const probe = await checkPublicAsset(fetchPublic, asset.url);
      verification = { hash: probe.hash, type: probe.type, status: probe.status, bytes: probe.bytes.length };
      checked.set(asset.url, verification);
    }
    const expected = types[asset.url.slice(asset.url.lastIndexOf(".") + 1)] ?? "";
    const budget = MEDIA_BYTE_BUDGETS[asset.kind as keyof typeof MEDIA_BYTE_BUDGETS];
    if (verification.status !== 200 || verification.hash !== asset.sha256) { bad += 1; context.out.line(`FAIL v${String(asset.version)} ${asset.ownerId} ${asset.kind}/${asset.variant}: ${verification.hash ? "sha256 mismatch" : `HTTP ${String(verification.status)}`} ${asset.url}`); }
    else if (verification.type !== expected) { bad += 1; context.out.line(`FAIL v${String(asset.version)} ${asset.ownerId} ${asset.kind}/${asset.variant}: Content-Type ${verification.type}, expected ${expected} ${asset.url}`); }
    else if (flag(context.args, "budget") && verification.bytes > budget) { over += 1; context.out.line(`OVER v${String(asset.version)} ${asset.ownerId} ${asset.kind}/${asset.variant}: ${String(Math.ceil(verification.bytes / 1024))} KiB > ${String(budget / 1024)} KiB ${asset.url}`); }
  }
  context.out.line(`${String(assets.length - bad)}/${String(assets.length)} active URLs OK${flag(context.args, "budget") ? `; ${String(over)} over budget` : ""}`);
  if (bad || over) throw new CliError("Media check failed.", EXIT.api);
}

function redundantLessons(tables: { courses: readonly { id: string; area_id?: string | null; subarea_id: string | null; cover_from?: string | null }[]; lessons: readonly { id: string; course_id: string }[] }, assets: readonly { ownerId: string; kind: string; variant: string; sha256: string; active?: boolean }[]): number {
  const grouped = new Map<string, { kind: string; variant?: string; sha256: string; isActive: boolean }[]>();
  for (const row of assets) grouped.set(row.ownerId, [...(grouped.get(row.ownerId) ?? []), { kind: row.kind, variant: row.variant, sha256: row.sha256, isActive: row.active !== false }]);
  const courses = new Map(tables.courses.map((row) => [row.id, row]));
  let count = 0;
  for (const lesson of tables.lessons) {
    const course = courses.get(lesson.course_id);
    if (!course) continue;
    const inherited = resolveCover({
      area: grouped.get(course.area_id ?? ""), course: grouped.get(course.id), subarea: grouped.get(course.subarea_id ?? ""),
      coverFrom: course.cover_from ?? undefined, courseId: course.id,
    }, { target: "lesson" });
    if (inherited && (grouped.get(lesson.id) ?? []).some((asset) => asset.kind === "cover_16x9" && (asset.variant ?? "default") === "default" && asset.sha256 === inherited.sha256)) count += 1;
  }
  return count;
}
