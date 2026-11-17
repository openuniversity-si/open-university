import { AppError } from "./errors.ts";

/** A readonly environment map. Callers pass a fixture; the facade is the only reader of the process map. */
export type EnvInput = Readonly<Record<string, string | undefined>>;

const profiles = new Map<string, unknown>();

/** The process map. Cached profiles do not observe later mutations; pass an input to bypass the cache. */
export function currentEnv(): EnvInput {
  return process.env;
}

export function resetEnvCache(): void {
  profiles.clear();
}

function remember<T>(name: string, input: EnvInput | undefined, parse: (env: EnvInput) => T): T {
  if (input) return parse(input);
  const hit = profiles.get(name);
  if (hit !== undefined) return hit as T;
  const value = parse(currentEnv());
  profiles.set(name, value);
  return value;
}

export function getWebPublicEnv(input?: EnvInput): Readonly<{ siteUrl: string; mediaPublicHost: string }> {
  return remember("web", input, (env) => {
    const siteUrl = (env.SITE_URL ?? env.NEXT_PUBLIC_SITE_URL ?? "").trim();
    if (siteUrl) {
      try {
        const url = new URL(siteUrl);
        if (url.username || url.password) throw new Error("credentials");
      } catch {
        throw new AppError("invalid", "SITE_URL is invalid.");
      }
    }
    const mediaPublicHost = (env.TOWER_MEDIA_PUBLIC_HOST ?? "").trim().toLowerCase();
    if (mediaPublicHost && (/[\s/]/.test(mediaPublicHost) || mediaPublicHost.includes("://"))) throw new AppError("invalid", "TOWER_MEDIA_PUBLIC_HOST is invalid.");
    return { siteUrl, mediaPublicHost };
  });
}

// Next inlines these member expressions from next.config.ts `env` at build time.
// Do not read them through currentEnv(): webpack cannot replace a dynamic lookup.
// The host adapter copies a published commit into TOWER_BUILD_COMMIT before this read.
const INLINED_VERSION = process.env.TOWER_APP_VERSION;
const INLINED_COMMIT = process.env.TOWER_BUILD_COMMIT;

function shortCommit(value: string | undefined): string {
  const sha = (value ?? "").trim();
  if (sha === "local") return "local";
  if (/^[a-fA-F0-9]{7,40}$/.test(sha)) return sha.slice(0, 7).toLowerCase();
  return "unknown";
}

export function getBuildEnv(input?: EnvInput): Readonly<{
  version: string;
  commit: string;
  diagnostics: "ok" | "unknown";
  phase: string;
  target: string;
}> {
  return remember("build", input, (env) => {
    const version = (env.TOWER_APP_VERSION ?? INLINED_VERSION ?? "").trim() || "unknown";
    const commit = shortCommit(env.TOWER_BUILD_COMMIT ?? INLINED_COMMIT);
    return {
      version,
      commit,
      diagnostics: version !== "unknown" && commit !== "unknown" ? "ok" : "unknown",
      phase: env.NEXT_PHASE ?? "",
      target: env.TOWER_BUILD_TARGET ?? "",
    };
  });
}

function hidden(value: string): { readonly present: boolean; readonly read: () => string } {
  return { present: value.length > 0, read: () => value };
}

export function getAdminEnv(input?: EnvInput): Readonly<{ mediaSecret: ReturnType<typeof hidden>; revalidateSecret: ReturnType<typeof hidden> }> {
  return remember("admin", input, (env) => ({
    mediaSecret: hidden(env.TOWER_ADMIN_MEDIA_SECRET ?? ""),
    revalidateSecret: hidden(env.TOWER_MEDIA_REVALIDATE_SECRET ?? ""),
  }));
}
