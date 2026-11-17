import { AUTH_COOKIE_PREFIX } from "../../kernel/brand-ids.ts";
import { CACHE } from "../../kernel/cache.ts";

export { AUTH_COOKIE_PREFIX };

export const SESSION_LIFETIME_SECONDS = CACHE.sessionLifetimeSeconds;
export const SESSION_UPDATE_AGE_SECONDS = CACHE.sessionUpdateSeconds;
export const SESSION_CACHE_SECONDS = CACHE.sessionCacheSeconds;
/** The session cookie is named `<prefix>.session_token` (`__Secure-` on HTTPS); the prefix lives in `kernel/brand-ids.ts`. */
export const SESSION_COOKIE_NAMES = [`${AUTH_COOKIE_PREFIX}.session_token`, `__Secure-${AUTH_COOKIE_PREFIX}.session_token`] as const;

export type AuthEnvironment = Readonly<Record<string, string | undefined>>;

/** `configured` is AUTH_URL and may be absent; the production origin is the fallback. */
export function resolveAuthBaseURL(configured: string | undefined, productionOrigin: string): string {
  const chosen = configured ?? productionOrigin;
  let url: URL;
  try { url = new URL(chosen); } catch { throw new Error("Invalid AUTH_URL; value redacted."); }
  const localHTTP = url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !localHTTP) || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("AUTH_URL must be an HTTPS origin (HTTP only on localhost); value redacted.");
  }
  return url.origin;
}

export function hasAuthStorage(env: AuthEnvironment, databaseConfigured: boolean): boolean {
  return Boolean(env.AUTH_SECRET?.trim() && databaseConfigured);
}
