import { z } from "zod";
import { AppError } from "../../kernel/errors.ts";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import { assertWithinBudget, MediaBudgetError } from "../domain/budget.ts";
import { pruneInherited } from "./inheritance.ts";
import { checkObjects, coverObjectInventory, objectDescriptor, readObjects, uploadObject } from "./objects.ts";
import { deleteMedia, listActiveMedia, listAllMedia, listMediaVersions, MediaConflictError, rollbackMedia, swapMedia, type MediaDeletion } from "./repository.ts";
import { StorageError } from "./storage-error.ts";
import { MediaInputError, prepareMedia } from "./prepare.ts";
import { areaInvalidation, courseMediaTag, mediaInvalidation, NOTHING, subareaInvalidation, type MediaInvalidation } from "../domain/tags.ts";
import { mediaKey, transformSchema, type MediaAsset, type MediaKind, type MediaOwner } from "../domain/types.ts";
import type { AdminMediaDeps } from "./admin.ts";
import { mediaAttachBody, mediaCheckBody, mediaDeleteBody, mediaListQuery, mediaPruneBody, mediaRollbackBody, mediaUploadFields, parseMediaOwners } from "../../admin/media-contracts.ts";
import { readOwnerList } from "./owner-list.ts";

const summary = (asset: MediaAsset) => ({ ownerId: asset.ownerId, kind: asset.kind, variant: asset.variant, version: asset.version, url: asset.url, width: asset.width, height: asset.height, sha256: asset.sha256 });

function revalidate(deps: AdminMediaDeps, owner: MediaOwner, course: { readonly courseId: string; readonly published: boolean; readonly subareaId?: string; readonly courses?: readonly { readonly courseId: string; readonly published: boolean }[] }, kind: string, variant: string, participant?: UnitOfWork) {
  const plan: MediaInvalidation = owner === "subarea" ? subareaInvalidation(course.subareaId ?? course.courseId, course.courses ?? [], kind, variant)
    : owner === "area" ? areaInvalidation(course.courseId, course.courses ?? [], kind, variant)
    : owner === "institution" ? NOTHING
    : mediaInvalidation({ owner, ...course, kind, variant });
  if (!plan.tags.length && !plan.paths.length) return;
  if (participant) participant.onAfterCommit(() => { deps.invalidate(plan); });
  else deps.invalidate(plan);
}

const databaseOf = (deps: AdminMediaDeps, participant?: UnitOfWork) => participant ?? deps.db();

async function guarded<T>(work: () => Promise<T>): Promise<T> {
  try { return await work(); } catch (error) {
    if (error instanceof AppError) throw error;
    const name = error instanceof Error ? error.name : "Error";
    const code = typeof (error as { code?: unknown } | null)?.code === "string" ? (error as { code: string }).code : "";
    const detail = error instanceof StorageError ? error.message : `${name}${code ? ` ${code}` : ""}`;
    logStructured("error", "ADMIN_MEDIA_FAILED", { detail });
    throw new AppError("upstream_failed", `Media storage or database failed (${detail}).`);
  }
}

export async function performMediaUpload(deps: AdminMediaDeps, input: { readonly bytes: Uint8Array; readonly fields: Readonly<Record<string, string>> }, participant?: UnitOfWork) {
  const fields = mediaUploadFields.safeParse(input.fields);
  if (!fields.success) throw new AppError("invalid", "Invalid owner, ownerId, kind, variant, alt or designStatus.");
  const { owner, ownerId, kind, variant, alt, designStatus, forceOversize } = fields.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { throw new AppError("invalid", `Kind ${kind} is not valid for a ${owner}.`); }
  let transform: z.infer<typeof transformSchema> = null;
  if (fields.data.transform) {
    try { transform = transformSchema.parse(JSON.parse(fields.data.transform)); } catch { throw new AppError("invalid", "Invalid transform."); }
  }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) throw new AppError("not_found", `Unknown ${owner}.`);
  return guarded(async () => {
    let prepared;
    try {
      prepared = await prepareMedia(input.bytes);
      assertWithinBudget(kind as MediaKind, prepared.bytes.length, forceOversize === "1");
    } catch (error) {
      if (error instanceof MediaInputError) throw new AppError("unsupported_media", error.message);
      if (error instanceof MediaBudgetError) throw new AppError("payload_too_large", error.message);
      throw error;
    }
    const db = databaseOf(deps, participant);
    const object = await uploadObject(db, deps.store(), prepared.bytes);
    const saved = await swapMedia(db, owner, { ownerId, kind: kind as MediaKind, variant, ...objectDescriptor(object), alt, designStatus, transform });
    revalidate(deps, owner, course, kind, variant, participant);
    return summary(saved);
  });
}

export async function performMediaCheck(deps: AdminMediaDeps, body: unknown, participant?: UnitOfWork) {
  const parsed = mediaCheckBody.safeParse(body);
  if (!parsed.success) throw new AppError("invalid", "Expected {sha256: string[]} (at most 100 hashes).");
  return guarded(() => checkObjects(databaseOf(deps, participant), deps.store(), parsed.data.sha256));
}

export async function performMediaObject(deps: AdminMediaDeps, input: { readonly bytes: Uint8Array; readonly fields: Readonly<Record<string, string>> }, participant?: UnitOfWork) {
  const hash = z.string().regex(/^[a-f0-9]{64}$/).safeParse(input.fields.sha256);
  if (!input.bytes.byteLength || !hash.success) throw new AppError("invalid", "file and sha256 are required.");
  return guarded(async () => {
    try {
      const object = await uploadObject(databaseOf(deps, participant), deps.store(), input.bytes, hash.data);
      return { ...object, ...objectDescriptor(object) };
    } catch (error) {
      if (error instanceof MediaInputError) throw new AppError("unsupported_media", error.message);
      throw error;
    }
  });
}

export async function performMediaAttach(deps: AdminMediaDeps, body: unknown, participant?: UnitOfWork) {
  const parsed = mediaAttachBody.safeParse(body);
  if (!parsed.success) throw new AppError("invalid", "Invalid media attachment.");
  const { owner, ownerId, kind, variant, sha256, alt, designStatus, transform, forceOversize } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { throw new AppError("invalid", "Invalid owner/kind."); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) throw new AppError("not_found", "Unknown owner.");
  return guarded(async () => {
    const db = databaseOf(deps, participant);
    const object = (await readObjects(db, [sha256]))[0];
    if (!object) throw new AppError("not_found", "Unknown media object: check or upload it first.");
    try { assertWithinBudget(kind as MediaKind, object.bytes, forceOversize); }
    catch (error) { if (error instanceof MediaBudgetError) throw new AppError("payload_too_large", error.message); throw error; }
    const saved = await swapMedia(db, owner, { ownerId, kind: kind as MediaKind, variant, ...objectDescriptor(object), alt, designStatus, transform });
    revalidate(deps, owner, course, kind, variant, participant);
    return summary(saved);
  });
}

export async function performMediaList(deps: AdminMediaDeps, query: unknown, participant?: UnitOfWork) {
  const parsed = mediaListQuery.safeParse(query);
  if (!parsed.success) throw new AppError("invalid", "Invalid query.");
  const { owner, ownerId, owners, kind, variant, all } = parsed.data;
  if (owners) {
    return guarded(async () => readOwnerList(databaseOf(deps, participant), parseMediaOwners(owners), { activeOnly: all !== "1", kind, variant }));
  }
  if (!owner && !ownerId) {
    return guarded(async () => {
      const db = databaseOf(deps, participant);
      const assets = (await (all ? listAllMedia : listActiveMedia)(db)).map((asset) => ({ ...summary(asset), ...(all ? { active: asset.isActive } : {}), alt: asset.alt }));
      return { assets: [...assets, ...await coverObjectInventory(db, await deps.owners(db).inventory())] };
    });
  }
  if (!owner || !ownerId) throw new AppError("invalid", "owner and ownerId go together.");
  if (kind) { try { mediaKey(owner, ownerId, kind, variant); } catch { throw new AppError("invalid", `Kind ${kind} is not valid for a ${owner}.`); } }
  if (!(await deps.courseOf(owner, ownerId))) throw new AppError("not_found", `Unknown ${owner}.`);
  return guarded(async () => {
    const versions = await listMediaVersions(databaseOf(deps, participant), owner, ownerId, kind, variant);
    return { versions: versions.map((asset) => ({ ...summary(asset), active: asset.isActive, alt: asset.alt, designStatus: asset.designStatus, createdAt: asset.createdAt.toISOString() })) };
  });
}

export async function performMediaRollback(deps: AdminMediaDeps, body: unknown, participant?: UnitOfWork) {
  const parsed = mediaRollbackBody.safeParse(body);
  if (!parsed.success) throw new AppError("invalid", "Invalid rollback request.");
  const { owner, ownerId, kind, variant, version } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { throw new AppError("invalid", `Kind ${kind} is not valid for a ${owner}.`); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) throw new AppError("not_found", `Unknown ${owner}.`);
  return guarded(async () => {
    const db = databaseOf(deps, participant);
    if (!(await listMediaVersions(db, owner, ownerId, kind, variant)).some((asset) => asset.version === version)) throw new AppError("not_found", "Version not found.");
    const restored = await rollbackMedia(db, owner, ownerId, kind, variant, version);
    revalidate(deps, owner, course, kind, variant, participant);
    return summary(restored);
  });
}

export async function performMediaDelete(deps: AdminMediaDeps, body: unknown, participant?: UnitOfWork) {
  const parsed = mediaDeleteBody.safeParse(body);
  if (!parsed.success) throw new AppError("invalid", "Invalid delete request.");
  const { owner, ownerId, kind, variant, version, apply, keepBytes } = parsed.data;
  try { mediaKey(owner, ownerId, kind, variant); } catch { throw new AppError("invalid", `Kind ${kind} is not valid for a ${owner}.`); }
  const course = await deps.courseOf(owner, ownerId);
  if (!course) throw new AppError("not_found", `Unknown ${owner}.`);
  const keepReason = (deletion: MediaDeletion, key: string) => keepBytes ? "keepBytes requested" : deletion.shared.has(key) ? "another row of this database uses the key" : null;
  const bytes = { deleted: [] as string[], kept: [] as { key: string; reason: string }[] };
  return guarded(async () => {
    let deletion: MediaDeletion;
    try {
      deletion = await deleteMedia(databaseOf(deps, participant), owner, ownerId, kind, variant, version, {
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
      if (error instanceof MediaConflictError) throw new AppError("state_conflict", error.message);
      if (error instanceof StorageError) throw new AppError("upstream_failed", `Stored object delete failed (${error.message}); no rows were deleted. Re-run the same command.`);
      throw error;
    }
    const activeAfter = deletion.activeAfter && { version: deletion.activeAfter.version, url: deletion.activeAfter.url };
    const alreadyAbsent = deletion.targets.length === 0 ? { alreadyAbsent: true as const } : {};
    if (!apply) {
      const plan = deletion.targets.map((asset) => ({ version: asset.version, variant: asset.variant, active: asset.isActive, key: asset.pathname, willDeleteBytes: !keepReason(deletion, asset.pathname), keepReason: keepReason(deletion, asset.pathname) ?? undefined }));
      return { dryRun: true, plan, activeAfter, ...alreadyAbsent };
    }
    if (deletion.targets.length) revalidate(deps, owner, course, kind, variant, participant);
    return { dryRun: false, deleted: deletion.targets.map((asset) => ({ version: asset.version, variant: asset.variant })), bytes, activeAfter, ...alreadyAbsent };
  });
}

export async function performMediaPrune(deps: AdminMediaDeps, body: unknown, participant?: UnitOfWork) {
  const parsed = mediaPruneBody.safeParse(body);
  if (!parsed.success) throw new AppError("invalid", "Expected {apply: boolean}.");
  return guarded(async () => {
    const report = await pruneInherited(databaseOf(deps, participant), parsed.data.apply, deps.owners);
    if (report.apply && report.courseIds.length) {
      const plan = { tags: report.courseIds.map(courseMediaTag), paths: [] as string[] };
      if (participant) participant.onAfterCommit(() => { deps.invalidate(plan); });
      else deps.invalidate(plan);
    }
    return report;
  });
}
