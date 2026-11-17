import { catalogLifecycleRefs, previewCourseCount } from "../../catalog/server/lifecycle-refs.ts";
import type { HandlerContext } from "../../catalog/server/http.ts";
import type { Outcome } from "../../catalog/server/mutation.ts";
import { AppError } from "../../kernel/errors.ts";
import { resetPreviewEnvironment } from "../lifecycle.ts";
import type { LifecycleEnvironment, LifecycleObject } from "../../media/domain/figure-ports.ts";
import type { lifecycleGcBody, lifecycleResetBody } from "../lifecycle-body.ts";
import { requestIdentity, scopedPermission, verifyAdminScope } from "../permissions.ts";
import { capturePreviewSnapshot, clearOrphaned, deleteOrphanedRow, listLifecycleRows, listObjectKeys, markOrphaned, objectExtension, rehearsePreviewSnapshot, resetPreviewQueue, restorePreviewSnapshot } from "../../media/server/lifecycle.ts";
import type { z } from "zod";

type GcBody = z.infer<typeof lifecycleGcBody>;
const DESTRUCTIVE = new Set(["delete-row", "copy-aside", "remove"]);

/** The credential's environment: a production deployment is never treated as preview (preview reset included). */
function environmentOf(context: HandlerContext<unknown, unknown, unknown>): "preview" | "prod" {
  return requestIdentity(context.deps, context.actor).environment;
}

function authorize(context: HandlerContext<unknown, unknown, unknown>, destructive: boolean): void {
  const identity = requestIdentity(context.deps, context.actor);
  const environment = identity.environment;
  verifyAdminScope(identity, scopedPermission("catalog:write", environment), environment);
  if (destructive) verifyAdminScope(identity, scopedPermission("media:gc:execute", environment), environment);
}

export function inventoryLifecycle(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  authorize(context, false);
  const environment = environmentOf(context);
  return catalogLifecycleRefs(context.db).then((catalog) => listLifecycleRows(context.db, catalog.refs).then((references) => ({
    data: { environment, complete: catalog.complete, references },
  })));
}

export function mutateLifecycle(context: HandlerContext<unknown, unknown, GcBody>): Promise<Outcome> {
  authorize(context, DESTRUCTIVE.has(context.body.op));
  const body = context.body;
  const answer = (data: unknown): Promise<Outcome> => context.mutate(async (tx) => {
    await tx.audit({ action: "lifecycle.gc", entityKind: "media", entityId: body.op, after: data });
    return { data };
  });
  if (body.op === "storage-list") {
    return listObjectKeys(context.db, body.cursor ?? "").then((page) => answer(page));
  }
  if (body.op === "mark") return markOrphaned(context.db, body.sha256).then((status) => answer({ status }));
  if (body.op === "clear") return clearOrphaned(context.db, body.sha256).then(() => answer({ status: "cleared" }));
  if (body.op === "barrier" || body.op === "revalidate") return answer({ ok: true });
  if (body.op === "delete-row") return deleteOrphanedRow(context.db, body.sha256).then((deleted) => answer({ deleted }));
  if (body.op === "exists") {
    return objectExtension(context.db, body.sha256).then((ext) => {
      if (!ext) return answer({ present: false });
      return context.deps.store().head(`m/${body.sha256}.${ext}`).then((head) => answer({ present: head !== null }));
    });
  }
  if (body.op === "copy-aside") {
    return objectExtension(context.db, body.sha256).then((ext) => {
      if (!ext) return answer({ ok: false });
      const key = `m/${body.sha256}.${ext}`;
      const backup = `retention/${body.sha256}.${ext}`;
      const store = context.deps.store();
      if (store.copy) return store.copy(key, backup).then(() => answer({ ok: true }), () => answer({ ok: false }));
      return store.get(key).then((bytes) => bytes ? store.put(backup, bytes).then(() => answer({ ok: true })) : answer({ ok: false }));
    });
  }
  return objectExtension(context.db, body.sha256).then((ext) => {
    if (!ext) return answer({ ok: false });
    return context.deps.store().delete(`m/${body.sha256}.${ext}`).then(() => answer({ ok: true }), () => answer({ ok: false }));
  });
}

export function resetLifecyclePreview(context: HandlerContext<unknown, unknown, z.infer<typeof lifecycleResetBody>>): Promise<Outcome> {
  authorize(context, !context.body.dryRun);
  const environment = environmentOf(context);
  if (environment !== "preview") return Promise.reject(new AppError("forbidden", "Production preview reset is rejected."));
  let snapshotId = "";
  const preview: LifecycleEnvironment = {
    name: "preview",
    listInventory: () => Promise.resolve({ environment: "preview", complete: true, references: [] as readonly LifecycleObject[] }),
    markOrphan: () => Promise.resolve("already"),
    clearOrphan: () => Promise.resolve(),
    barrier: () => Promise.resolve(true),
    revalidate: () => Promise.resolve(true),
    snapshot: () => previewCourseCount(context.db).then((courses) => capturePreviewSnapshot(context.db, courses).then((snap) => {
      snapshotId = snap?.id ?? "";
      return snap;
    })),
    restore: (id) => restorePreviewSnapshot(context.db, id),
    reset: () => resetPreviewQueue(context.db, snapshotId),
    rehearse: (id) => previewCourseCount(context.db).then((courses) => rehearsePreviewSnapshot(context.db, id, courses)),
    deleteRow: () => Promise.resolve(false),
  };
  const prod: LifecycleEnvironment = { ...preview, name: "prod", barrier: () => Promise.resolve(false), reset: () => Promise.resolve(false) };
  return context.mutate(async (tx) => {
    const report = await resetPreviewEnvironment({
      environments: ["prod", "preview"],
      now: context.deps.now,
      ports: { prod, preview },
      storage: { list: () => Promise.resolve({ keys: [], cursor: null, complete: true }), copyAside: () => Promise.resolve(false), remove: () => Promise.resolve(false), exists: () => Promise.resolve(false) },
      jobs: { claim: () => Promise.resolve({ acquired: true, token: "preview" }), receipt: () => Promise.resolve(), complete: () => Promise.resolve() },
    }, { dryRun: context.body.dryRun, environment: "preview" });
    await tx.audit({ action: "lifecycle.reset", entityKind: "environment", entityId: "preview", after: report });
    return { data: report };
  });
}
