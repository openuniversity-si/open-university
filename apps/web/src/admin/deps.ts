import "server-only";
import { currentEnv } from "../kernel/env.ts";
import { adminRateLimiter } from "../platform/security/rate-limit.ts";
import { appPool } from "../platform/db/pool.ts";
import { invalidateMedia } from "../media/server/invalidate.ts";
import { database } from "../media/server/index.ts";
import { catalogCourseOf, catalogOwners } from "../catalog/server/media-owners.ts";
import { createWritableMediaStore } from "../media/server/storage.ts";
import type { AdminMediaDeps } from "../media/server/admin.ts";
import { performMediaAttach, performMediaCheck, performMediaDelete, performMediaList, performMediaObject, performMediaPrune, performMediaRollback, performMediaUpload } from "../media/server/actions.ts";
import { catalogAdminJournal } from "../catalog/server/admin-journal.ts";
import { adminAuthorization, type AdminHandler, type DispatchDeps } from "./http-dispatcher.ts";

/** Server env only; credentials are never returned or logged. */
export function adminMediaDeps(): AdminMediaDeps {
  return {
    secret: currentEnv().TOWER_ADMIN_MEDIA_SECRET,
    limiter: adminRateLimiter,
    db: database,
    store: () => createWritableMediaStore(currentEnv()),
    invalidate: invalidateMedia,
    courseOf: catalogCourseOf(database),
    owners: catalogOwners,
  };
}

export function mediaHandlers(deps: AdminMediaDeps): ReadonlyMap<string, AdminHandler> {
  return new Map<string, AdminHandler>([
    ["media:GET /", ({ query, participant }) => performMediaList(deps, query, participant).then((data) => ({ data }))],
    ["media:POST /", ({ body, participant }) => performMediaUpload(deps, body as { bytes: Uint8Array; fields: Record<string, string> }, participant).then((data) => ({ data }))],
    ["media:DELETE /", ({ body, participant }) => performMediaDelete(deps, body, participant).then((data) => ({ data }))],
    ["media:POST /check", ({ body, participant }) => performMediaCheck(deps, body, participant).then((data) => ({ data }))],
    ["media:POST /objects", ({ body, participant }) => performMediaObject(deps, body as { bytes: Uint8Array; fields: Record<string, string> }, participant).then((data) => ({ data }))],
    ["media:POST /attach", ({ body, participant }) => performMediaAttach(deps, body, participant).then((data) => ({ data }))],
    ["media:POST /rollback", ({ body, participant }) => performMediaRollback(deps, body, participant).then((data) => ({ data }))],
    ["media:POST /prune-inherited", ({ body, participant }) => performMediaPrune(deps, body, participant).then((data) => ({ data }))],
  ]);
}

export { catalogMediaGateway } from "../catalog/server/media-gateway.ts";

export function mediaDispatchDeps(deps: AdminMediaDeps = adminMediaDeps()): DispatchDeps {
  return {
    handlers: mediaHandlers(deps),
    authorize: (request) => adminAuthorization(request, deps),
    journal: catalogAdminJournal(appPool),
  };
}
