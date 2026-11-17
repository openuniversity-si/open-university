import { createHash, timingSafeEqual } from "node:crypto";
import { CACHE } from "../kernel/cache.ts";
import { requestAddress } from "../platform/host/request-address.ts";
import type { AdminRateLimiter } from "../platform/security/rate-limit.ts";

export { adminRateLimiter, createAdminRateLimiter, type AdminRateLimiter } from "../platform/security/rate-limit.ts";

/** Shared by the media and catalog admin APIs (ADR-18): one secret, one limiter, the same answers. */
export interface AdminGuardDeps {
  readonly secret: string | undefined;
  readonly limiter: AdminRateLimiter;
}
export type AdminDenial =
  | { readonly status: 503; readonly reason: "unconfigured" }
  | { readonly status: 429; readonly reason: "rate_limited"; readonly retryAfter: number }
  | { readonly status: 401; readonly reason: "unauthorized" };

export const ADMIN_NO_STORE = { "Cache-Control": CACHE.responseNoStore } as const;

export function clientIp(request: Request): string {
  return requestAddress(request.headers);
}

/** `Authorization: Bearer <TOWER_ADMIN_MEDIA_SECRET>`, compared in constant time over SHA-256 digests. */
export function adminAuthorized(header: string | null, secret: string | undefined): boolean {
  if (!secret || !header?.startsWith("Bearer ")) return false;
  const hash = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(hash(header.slice(7)), hash(secret));
}

/** null when the request may proceed; otherwise why not. A wrong or missing token counts as a failed auth for the IP. */
export async function authorizeAdmin(request: Request, deps: AdminGuardDeps): Promise<AdminDenial | null> {
  if (!deps.secret) return { status: 503, reason: "unconfigured" };
  if (adminAuthorized(request.headers.get("authorization"), deps.secret)) {
    try {
      const retryAfter = await deps.limiter.authenticated(createHash("sha256").update(deps.secret).digest("hex"));
      return retryAfter ? { status: 429, reason: "rate_limited", retryAfter } : null;
    } catch { return { status: 503, reason: "unconfigured" }; }
  }
  const ip = clientIp(request);
  if (!deps.limiter.allow(ip)) return { status: 429, reason: "rate_limited", retryAfter: deps.limiter.retryAfter() };
  deps.limiter.fail(ip);
  return { status: 401, reason: "unauthorized" };
}

/** Every admin response is JSON and never cached. */
export function adminReply(body: unknown, status = 200, headers: Readonly<Record<string, string>> = {}): Response {
  return Response.json(body, { status, headers: { ...headers, ...ADMIN_NO_STORE } });
}
