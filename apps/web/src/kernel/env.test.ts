import { describe, expect, it } from "vitest";
import { AppError } from "./errors.ts";
import { getDatabaseEnv } from "../platform/db/database-env.ts";
import { getMediaStorageEnv } from "../media/server/storage-env.ts";
import { getAuthEnv } from "../identity/server/config.ts";
import { buildEnvFromHost } from "../platform/host/env.ts";
import { getBuildEnv, getWebPublicEnv, resetEnvCache } from "./env.ts";

const sentinel = "postgres://sentinel-user:sentinel-pass@db.invalid/tower";

describe("environment profiles", () => {
  it("rejects an invalid database url, a non-integer pool and a write profile without credentials", () => {
    expect(() => getDatabaseEnv({ APP_DATABASE_URL: sentinel.replace("postgres", "http") })).toThrow(AppError);
    expect(() => { getDatabaseEnv({ APP_DATABASE_URL: "not a url" }); }).toThrow(/APP_DATABASE_URL/);
    try { getDatabaseEnv({ APP_DATABASE_URL: sentinel.replace("postgres", "http") }); } catch (error) {
      expect(String(error)).not.toContain("sentinel");
    }
    expect(() => { getDatabaseEnv({ APP_DATABASE_URL: sentinel, APP_POOL_MAX: "2.5" }); }).toThrow(/APP_POOL_MAX/);
    expect(getDatabaseEnv({ APP_DATABASE_URL: sentinel, APP_POOL_MAX: "8" }).maxPoolSize).toBe(8);
    expect(() => { getMediaStorageEnv({ MEDIA_ACCESS: "rw" }); }).toThrow(/R2_ACCESS_KEY_ID_RW/);
    expect(() => { getMediaStorageEnv({}); }).toThrow(/R2_ACCESS_KEY_ID_RW/);
    expect(getMediaStorageEnv({ R2_ACCESS_KEY_ID_RW: "id", R2_SECRET_ACCESS_KEY_RW: "secret" })).toEqual({ access: "rw" });
    expect(getMediaStorageEnv({ MEDIA_ACCESS: "ro", R2_ACCESS_KEY_ID_RO: "id", R2_SECRET_ACCESS_KEY_RO: "secret" })).toEqual({ access: "ro" });
  });

  it("keeps secrets out of serialized profiles and isolates the cache", () => {
    resetEnvCache();
    const auth = getAuthEnv({ AUTH_SECRET: "x".repeat(32), APP_DATABASE_URL: sentinel, AUTH_GOOGLE_SECRET: "google-sentinel" });
    expect(JSON.stringify(auth)).not.toContain("google-sentinel");
    expect(JSON.stringify(auth)).not.toContain(sentinel);
    expect(auth.secret.read()).toHaveLength(32);
    expect(() => { getAuthEnv({ AUTH_SECRET: "short-sentinel" }); }).toThrow(/AUTH_SECRET/);
    try { getAuthEnv({ AUTH_SECRET: "short-sentinel" }); } catch (error) { expect(String(error)).not.toContain("short-sentinel"); }
    expect(() => { getWebPublicEnv({ SITE_URL: "http://user:password@example.test" }); }).toThrow(/SITE_URL/);
    resetEnvCache();
    const build = getBuildEnv(buildEnvFromHost({
      BUILD_SHA: "43844ff7889838d7f040463ae3f9d76c46ae37c3",
      TOWER_APP_VERSION: "0.1.0",
    }));
    expect(build).toMatchObject({ version: "0.1.0", commit: "43844ff", diagnostics: "ok" });
    expect(build.commit).not.toBe("unknown");
    const first = getWebPublicEnv();
    const second = getWebPublicEnv();
    expect(second).toBe(first);
    resetEnvCache();
  });
});
