import "server-only";
import { currentEnv } from "../../kernel/env.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import { randomUUID } from "node:crypto";
import { adminRateLimiter } from "../../platform/security/rate-limit.ts";
import { appPool } from "../../platform/db/pool.ts";
import { invalidateMedia } from "../../media/server/invalidate.ts";
import { createWritableMediaStore } from "../../media/server/storage.ts";
import { invalidateCatalog } from "./invalidate.ts";
import type { AdminCatalogDeps } from "./http.ts";
import { parseEditorial } from "../../config/domain/documents.ts";
import { readServed } from "../../config/server/read.ts";
import { adminDeployment } from "../../platform/host/env.ts";
import { createOEmbed, OEMBED_CHECKER } from "../../playback/server/oembed-resolver.ts";

const oembed = createOEmbed();

/** Server env only (the media pattern): the same secret and the same per-instance limiter as /api/admin/media. */
export function adminCatalogDeps(): AdminCatalogDeps {
  return {
    secret: currentEnv().TOWER_ADMIN_MEDIA_SECRET,
    environment: adminDeployment(currentEnv()),
    limiter: adminRateLimiter,
    pool: appPool,
    invalidateCatalog,
    invalidateMedia,
    oembed,
    oembedChecker: OEMBED_CHECKER,
    store: () => createWritableMediaStore(currentEnv()),
    now: () => new Date(),
    uuid: randomUUID,
    log: ({ event, requestId, ...fields }) => { logStructured("info", event, fields, requestId === undefined ? undefined : { requestId }); },
    readStatusTransitions: async () => parseEditorial(await readServed("editorial")).statusTransitions,
  };
}

export { catalogMediaGateway } from "./media-gateway.ts";
