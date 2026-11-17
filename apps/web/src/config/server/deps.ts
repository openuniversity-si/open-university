import "server-only";
import { currentEnv } from "../../kernel/env.ts";
import { adminRateLimiter } from "../../platform/security/rate-limit.ts";
import { appPool } from "../../platform/db/pool.ts";
import type { ConfigAdminDeps } from "./admin.ts";
import { invalidateConfig } from "./invalidate.ts";
import { configRepository } from "./repository.ts";

/** The same secret and the same limiter as the catalog admin API. */
export function configAdminDeps(): ConfigAdminDeps {
  return {
    secret: currentEnv().TOWER_ADMIN_MEDIA_SECRET,
    limiter: adminRateLimiter,
    documents: configRepository(appPool()),
    invalidate: invalidateConfig,
  };
}
