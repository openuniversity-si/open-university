import { logStructured } from "../../platform/observability/logger.ts";
import { z } from "zod";
import { checkObjects, coverObjectInventory, objectDescriptor, readObjects, sha256Schema, uploadObject } from "./objects.ts";
import { deleteMedia, listActiveMedia, listAllMedia, listMediaVersions, MediaConflictError, rollbackMedia, swapMedia, type MediaDeletion, type MediaPool } from "./repository.ts";
import { mediaListQuery, parseMediaOwners } from "../../admin/media-contracts.ts";
import { readOwnerList } from "./owner-list.ts";
import { assertWithinBudget, MediaBudgetError } from "../domain/budget.ts";
import { adminReply, authorizeAdmin, createAdminRateLimiter, type AdminRateLimiter } from "../../admin/auth.ts";
import { StorageError } from "./storage-error.ts";
import { MediaInputError, prepareMedia } from "./prepare.ts";
import { type MediaObjectStore } from "./storage.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import type { CatalogOwnersPort, MediaCourse } from "../ports/owner.ts";
import { pruneInherited } from "./inheritance.ts";
import { courseMediaTag } from "../domain/tags.ts";
import { areaInvalidation, mediaInvalidation, NOTHING, subareaInvalidation, type MediaInvalidation } from "../domain/tags.ts";
import { mediaKey, ownerIdSchema, ownerSchema, transformSchema, variantSchema, type MediaAsset, type MediaOwner, type MediaKind } from "../domain/types.ts";
import { REQUEST_ID_HEADER, requestIdFrom } from "../../platform/observability/context.ts";
import type { ErrorCode } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { EXTENT } from "../../kernel/extent.ts";

/** Serverless hosts cap request bodies at a few MB; we reject earlier with a clear message. */
export const ADMIN_MEDIA_MAX_BYTES = LIMITS.mediaBodyBytes;

function mediaErrorCode(status: number): ErrorCode {
  switch (status) {
    case 400: return "invalid";
    case 401: return "unauthorized";
    case 404: return "not_found";
    case 409: return "state_conflict";
    case 413: return "payload_too_large";
    case 415: return "unsupported_media";
    case 422: return "unprocessable";
    case 429: return "rate_limited";
    case 502: return "upstream_failed";
    case 503: return "unconfigured";
    default: return "internal";
  }
}

interface MediaHttp {
  ok(data: unknown, status?: number): Response;
  fail(status: number, message: string, extra?: Readonly<Record<string, string>>): Response;
}

/** Every direct media handler answers with the same admin envelope as the catch-all. */
function mediaHttp(request: Request): MediaHttp {
  const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), () => crypto.randomUUID());
  const headers = { [REQUEST_ID_HEADER]: requestId };
  return {
    ok: (data, status = 200) => adminReply({ ok: true, data, requestId }, status, headers),
    fail: (status, message, extra = {}) => adminReply({ ok: false, error: { code: mediaErrorCode(status), message }, requestId }, status, { ...headers, ...extra }),
  };
}

export { createAdminRateLimiter, type AdminRateLimiter };

export interface AdminMediaDeps {
  readonly secret: string | undefined;
  readonly limiter: AdminRateLimiter;
  readonly db: () => MediaPool;
  readonly store: () => MediaObjectStore;
  readonly invalidate: (plan: MediaInvalidation) => void;
  /** Catalog course owning the media (id, published), or undefined for an unknown owner. */
  readonly courseOf: (owner: MediaOwner, ownerId: string) => Promise<MediaCourse | undefined>;
  readonly owners: (db: Queryable) => CatalogOwnersPort;
}

const denials = { 503: "Admin media is not configured.", 429: "Too many requests.", 401: "Unauthorized." } as const;
export interface MediaGate { readonly skipGuard?: boolean }
async function guard(request: Request, deps: AdminMediaDeps, http: MediaHttp, gate?: MediaGate): Promise<Response | null> {
  if (gate?.skipGuard) return null;
  const denied = await authorizeAdmin(request, deps);
  return denied && http.fail(denied.status, denials[denied.status], denied.status === 429 ? { "Retry-After": String(denied.retryAfter) } : {});
}
/** Expires only what shows this media: nothing for an unpublished course (src/media/domain/tags.ts). */
function revalidate(deps: AdminMediaDeps, owner: MediaOwner, course: MediaCourse, kind: string, variant: string) {
  const plan = owner === "subarea" ? subareaInvalidation(course.subareaId ?? course.courseId, course.courses ?? [], kind, variant)
    : owner === "area" ? areaInvalidation(course.courseId, course.courses ?? [], kind, variant)
    : owner === "institution" ? NOTHING
    : mediaInvalidation({ owner, ...course, kind, variant });
  if (plan.tags.length || plan.paths.length) deps.invalidate(plan);
}
const summary = (asset: MediaAsset) => ({ ownerId: asset.ownerId, kind: asset.kind, variant: asset.variant, version: asset.version, url: asset.url, width: asset.width, height: asset.height, sha256: asset.sha256 });
const ownerKey = z.object({ owner: ownerSchema, ownerId: ownerIdSchema });
/** Wraps storage/database work so no driver detail ever reaches the response. */
async function guarded(http: MediaHttp, work: () => Promise<Response>) {
  try { return await work(); } catch (error) {
    // StorageError messages are secret-free by construction (method + HTTP status only); other errors expose just their class and code.
    const name = error instanceof Error ? error.name : "Error";
    const code = typeof (error as { code?: unknown } | null)?.code === "string" ? (error as { code: string }).code : "";
    const detail = error instanceof StorageError ? error.message : `${name}${code ? ` ${code}` : ""}`;
    logStructured("error", "ADMIN_MEDIA_FAILED", { detail });
    return http.fail(502, `Media storage or database failed (${detail}).`);
  }
}

/** Removes only redundant database references; the report retains every row and no R2 operation occurs. */
export async function handleAdminMediaPruneInherited(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  let body: unknown;
  try { body = await request.json(); } catch { return http.fail(400, "Invalid JSON."); }
  const parsed = z.strictObject({ apply: z.boolean().default(false) }).safeParse(body);
  if (!parsed.success) return http.fail(400, "Expected {apply: boolean}.");
  return guarded(http, async () => {
    const report = await pruneInherited(deps.db(), parsed.data.apply, deps.owners);
    if (report.apply && report.courseIds.length) deps.invalidate({ tags: report.courseIds.map(courseMediaTag), paths: [] });
    return http.ok(report);
  });
}

const uploadFields = ownerKey.extend({
  kind: z.string(), variant: variantSchema.default("default"), alt: z.string().trim().min(EXTENT.one).max(LIMITS.mediaAlt),
  designStatus: z.enum(["approved", "draft", "legacy"]).default("approved"), transform: z.string().optional(),
  /** "1" stores an asset above its kind's byte budget (src/media/domain/budget.ts) as a conscious exception. */
  forceOversize: z.literal("1").optional(),
});

export async function handleAdminMediaUpload(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  const tooLarge = () => http.fail(413, "File too large: the limit is 4 MB. Compress or resize the image and retry.");
  if (Number(request.headers.get("content-length") ?? 0) > ADMIN_MEDIA_MAX_BYTES + LIMITS.mediaMultipartOverhead) return tooLarge();
  let form: FormData;
  try { form = await request.formData(); } catch { return http.fail(400, "Expected multipart/form-data."); }
  const file = form.get("file");
  if (!(file instanceof Blob) || file.size === 0) return http.fail(400, "A non-empty file field is required.");
  if (file.size > ADMIN_MEDIA_MAX_BYTES) return tooLarge();
  const fields = uploadFields.safeParse(Object.fromEntries([...form.entries()].filter(([, value]) => typeof value === "string" && value !== "")));
  if (!fields.success) return http.fail(400, "Invalid owner, ownerId, kind, variant, alt or designStatus.");
  const { owner, ownerId, kind, variant, alt, designStatus, forceOversize } = fields.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { return http.fail(400, `Kind ${kind} is not valid for a ${owner}.`); }
  let transform: z.infer<typeof transformSchema> = null;
  if (fields.data.transform) {
    try { transform = transformSchema.parse(JSON.parse(fields.data.transform)); } catch { return http.fail(400, "Invalid transform."); }
  }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) return http.fail(404, `Unknown ${owner}.`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  return guarded(http, async () => {
    let input;
    try {
      const prepared = await prepareMedia(bytes);
      assertWithinBudget(kind as MediaKind, prepared.bytes.length, forceOversize === "1");
      const object = await uploadObject(deps.db(), deps.store(), prepared.bytes);
      input = { ownerId, kind: kind as MediaKind, variant, ...objectDescriptor(object), alt, designStatus, transform };
    } catch (error) {
      // Non-images, animations, SVG and assets over their byte budget are rejected before anything is stored.
      if (error instanceof MediaInputError) return http.fail(415, error.message);
      if (error instanceof MediaBudgetError) return http.fail(413, error.message);
      throw error;
    }
    const saved = await swapMedia(deps.db(), owner, input);
    revalidate(deps, owner, course, kind, variant);
    return http.ok(summary(saved));
  });
}

/** Hash preflight can register verified objects already present in the shared bucket. */
export async function handleAdminMediaCheck(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  let body: unknown;
  try { body = await request.json(); } catch { return http.fail(400, "Invalid JSON."); }
  const parsed = z.strictObject({ sha256: z.array(sha256Schema).max(LIMITS.mediaCheckBatch) }).safeParse(body);
  if (!parsed.success) return http.fail(400, "Expected {sha256: string[]} (at most 100 hashes).");
  return guarded(http, async () => http.ok(await checkObjects(deps.db(), deps.store(), parsed.data.sha256)));
}
/** Upload content without attaching it to a catalog owner. Author and Home CLIs use this same API. */
export async function handleAdminMediaObjectUpload(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  if (Number(request.headers.get("content-length") ?? 0) > ADMIN_MEDIA_MAX_BYTES + LIMITS.mediaMultipartOverhead) return http.fail(413, "File too large.");
  let form: FormData;
  try { form = await request.formData(); } catch { return http.fail(400, "Expected multipart/form-data."); }
  const file = form.get("file");
  const hash = sha256Schema.safeParse(form.get("sha256"));
  if (!(file instanceof Blob) || !file.size || !hash.success) return http.fail(400, "file and sha256 are required.");
  if (file.size > ADMIN_MEDIA_MAX_BYTES) return http.fail(413, "File too large.");
  return guarded(http, async () => {
    try {
      const object = await uploadObject(deps.db(), deps.store(), new Uint8Array(await file.arrayBuffer()), hash.data);
      return http.ok({ ...object, ...objectDescriptor(object) });
    } catch (error) {
      if (error instanceof MediaInputError) return http.fail(415, error.message);
      throw error;
    }
  });
}
/** DB only: the immutable object must already be registered in this database. */
export async function handleAdminMediaAttach(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  let body: unknown;
  try { body = await request.json(); } catch { return http.fail(400, "Invalid JSON."); }
  const parsed = ownerKey.extend({ kind: z.string(), variant: variantSchema.default("default"), sha256: sha256Schema,
    alt: z.string().trim().min(EXTENT.one).max(LIMITS.mediaAlt), designStatus: z.enum(["approved", "draft", "legacy"]).default("approved"),
    transform: transformSchema.default(null), forceOversize: z.boolean().default(false) }).strict().safeParse(body);
  if (!parsed.success) return http.fail(400, "Invalid media attachment.");
  const { owner, ownerId, kind, variant, sha256, alt, designStatus, transform, forceOversize } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { return http.fail(400, "Invalid owner/kind."); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) return http.fail(404, "Unknown owner.");
  return guarded(http, async () => {
    const object = (await readObjects(deps.db(), [sha256]))[0];
    if (!object) return http.fail(404, "Unknown media object: check or upload it first.");
    try { assertWithinBudget(kind as MediaKind, object.bytes, forceOversize); }
    catch (error) { if (error instanceof MediaBudgetError) return http.fail(413, error.message); throw error; }
    const saved = await swapMedia(deps.db(), owner, { ownerId, kind: kind as MediaKind, variant, ...objectDescriptor(object), alt, designStatus, transform });
    revalidate(deps, owner, course, kind, variant);
    return http.ok(summary(saved));
  });
}

export async function handleAdminMediaList(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  const query = mediaListQuery.safeParse(Object.fromEntries([...new URL(request.url).searchParams].filter(([, value]) => value !== "")));
  if (!query.success) return http.fail(400, "Invalid query.");
  const { owner, ownerId, owners, kind, variant, all } = query.data;
  if (owners) {
    return guarded(http, async () => http.ok(await readOwnerList(deps.db(), parseMediaOwners(owners), { activeOnly: all !== "1", kind, variant })));
  }
  if (!owner && !ownerId) {
    // all=1: inactive versions and non-default variants too (cleanup candidates).
    return guarded(http, async () => {
      const db = deps.db();
      const assets = (await (all ? listAllMedia : listActiveMedia)(db)).map((asset) => ({ ...summary(asset), ...(all ? { active: asset.isActive } : {}), alt: asset.alt }));
      return http.ok({ assets: [...assets, ...await coverObjectInventory(db, await deps.owners(db).inventory())] });
    });
  }
  if (!owner || !ownerId) return http.fail(400, "owner and ownerId go together.");
  if (kind) { try { mediaKey(owner, ownerId, kind, variant); } catch { return http.fail(400, `Kind ${kind} is not valid for a ${owner}.`); } }
  if (!(await deps.courseOf(owner, ownerId))) return http.fail(404, `Unknown ${owner}.`);
  return guarded(http, async () => {
    const versions = await listMediaVersions(deps.db(), owner, ownerId, kind, variant);
    return http.ok({ versions: versions.map((asset) => ({ ...summary(asset), active: asset.isActive, alt: asset.alt, designStatus: asset.designStatus, createdAt: asset.createdAt.toISOString() })) });
  });
}

const rollbackBody = z.strictObject({ owner: ownerSchema, ownerId: ownerIdSchema, kind: z.string(), variant: variantSchema.default("default"), version: z.number().int().positive() });

export async function handleAdminMediaRollback(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  let body: unknown;
  try { body = await request.json(); } catch { return http.fail(400, "Invalid JSON."); }
  const parsed = rollbackBody.safeParse(body);
  if (!parsed.success) return http.fail(400, "Invalid rollback request.");
  const { owner, ownerId, kind, variant, version } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { return http.fail(400, `Kind ${kind} is not valid for a ${owner}.`); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) return http.fail(404, `Unknown ${owner}.`);
  return guarded(http, async () => {
    const db = deps.db();
    if (!(await listMediaVersions(db, owner, ownerId, kind, variant)).some((asset) => asset.version === version)) return http.fail(404, "Version not found.");
    const restored = await rollbackMedia(db, owner, ownerId, kind, variant, version);
    revalidate(deps, owner, course, kind, variant);
    return http.ok(summary(restored));
  });
}

const deleteBody = z.strictObject({
  owner: ownerSchema, ownerId: ownerIdSchema, kind: z.string(), variant: variantSchema.default("default"),
  version: z.number().int().positive().optional(), apply: z.boolean().default(false), keepBytes: z.boolean().default(false),
});

/**
 * Deletes one inactive version, or a whole non-default variant (no `version`). Dry-run unless `apply`.
 * R2 bytes go only when no remaining row of this database uses the key and `keepBytes` is false (the bucket is shared with
 * the other environment). Bytes are deleted inside the row transaction: an R2 failure restores the rows (502), so re-running is safe.
 */
export async function handleAdminMediaDelete(request: Request, deps: AdminMediaDeps, gate?: MediaGate): Promise<Response> {
  const http = mediaHttp(request);
  const denied = await guard(request, deps, http, gate);
  if (denied) return denied;
  let body: unknown;
  try { body = await request.json(); } catch { return http.fail(400, "Invalid JSON."); }
  const parsed = deleteBody.safeParse(body);
  if (!parsed.success) return http.fail(400, "Invalid delete request.");
  const { owner, ownerId, kind, variant, version, apply, keepBytes } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { return http.fail(400, `Kind ${kind} is not valid for a ${owner}.`); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) return http.fail(404, `Unknown ${owner}.`);
  const keepReason = (deletion: MediaDeletion, key: string) => keepBytes ? "keepBytes requested" : deletion.shared.has(key) ? "another row of this database uses the key" : null;
  const bytes = { deleted: [] as string[], kept: [] as { key: string; reason: string }[] };
  return guarded(http, async () => {
    let deletion: MediaDeletion;
    try {
      deletion = await deleteMedia(deps.db(), owner, ownerId, kind, variant, version, {
        apply,
        async beforeCommit(planned) {
          for (const key of new Set(planned.targets.map((asset) => asset.pathname))) {
            const reason = keepReason(planned, key);
            if (reason) { bytes.kept.push({ key, reason }); continue; }
            await deps.store().delete(key);
            bytes.deleted.push(key);
          }
        },
      });
    } catch (error) {
      if (error instanceof MediaConflictError) return http.fail(409, error.message);
      if (error instanceof StorageError) return http.fail(502, `Stored object delete failed (${error.message}); no rows were deleted. Re-run the same command.`);
      throw error;
    }
    const activeAfter = deletion.activeAfter && { version: deletion.activeAfter.version, url: deletion.activeAfter.url };
    const alreadyAbsent = deletion.targets.length === 0 ? { alreadyAbsent: true } : {};
    if (!apply) {
      const plan = deletion.targets.map((asset) => ({ version: asset.version, variant: asset.variant, active: asset.isActive, key: asset.pathname, willDeleteBytes: !keepReason(deletion, asset.pathname), keepReason: keepReason(deletion, asset.pathname) ?? undefined }));
      return http.ok({ dryRun: true, plan, activeAfter, ...alreadyAbsent });
    }
    if (deletion.targets.length) revalidate(deps, owner, course, kind, variant);
    return http.ok({ dryRun: false, deleted: deletion.targets.map((asset) => ({ version: asset.version, variant: asset.variant })), bytes, activeAfter, ...alreadyAbsent });
  });
}
