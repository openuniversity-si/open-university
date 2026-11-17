import { PREVIEW_COOKIE_NAME } from "../../kernel/brand-ids.ts";
import { createHmac, hkdfSync, randomBytes, timingSafeEqual } from "node:crypto";

// Preview tokens (ADR-18): HMAC-SHA256 under a key derived from the admin secret (HKDF, label catalog-preview-v1), never the
// secret itself; payload {v, exp, scope, nonce}. Verification is constant-time and every failure is the same `null`.

export const PREVIEW_LABEL = "catalog-preview-v1";
export const PREVIEW_COOKIE = PREVIEW_COOKIE_NAME;
export const PREVIEW_MAX_MINUTES = 60;

export interface PreviewClaims { readonly exp: number; readonly scope: string | null }

const derive = (secret: string) => Buffer.from(hkdfSync("sha256", secret, "", PREVIEW_LABEL, 32));
const encode = (value: Buffer | string) => Buffer.from(value).toString("base64url");

export function signPreviewToken(secret: string, scope: string | null, ttlMinutes: number, now: Date): { token: string; expiresAt: Date } {
  const minutes = Math.min(Math.max(Math.trunc(ttlMinutes), 1), PREVIEW_MAX_MINUTES);
  const exp = Math.floor(now.getTime() / 1000) + minutes * 60;
  const payload = encode(JSON.stringify({ v: 1, exp, scope, nonce: randomBytes(9).toString("base64url") }));
  const signature = encode(createHmac("sha256", derive(secret)).update(payload).digest());
  return { token: `${payload}.${signature}`, expiresAt: new Date(exp * 1000) };
}

export function verifyPreviewToken(secret: string | undefined, token: string | null | undefined, now: Date): PreviewClaims | null {
  if (!secret || !token || token.length > 512) return null;
  const [payload, signature, extra] = token.split(".");
  if (!payload || !signature || extra !== undefined) return null;
  const expected = createHmac("sha256", derive(secret)).update(payload).digest();
  const given = Buffer.from(signature, "base64url");
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return null;
  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { v?: unknown; exp?: unknown; scope?: unknown };
    if (claims.v !== 1 || typeof claims.exp !== "number" || !(claims.scope === null || typeof claims.scope === "string")) return null;
    if (claims.exp * 1000 <= now.getTime()) return null;
    return { exp: claims.exp, scope: claims.scope };
  } catch {
    return null;
  }
}

/** The redirect target of the public preview route: a same-site path, `/` or under `/c/` (anti open-redirect), else null. */
export function safePreviewTarget(to: string | null): string | null {
  if (to === null || to.length > 300 || !to.startsWith("/") || to.startsWith("//") || /[\\\s]/.test(to) || Array.from(to).some((character) => (character.codePointAt(0) ?? 0) < 0x20)) return null;
  let url: URL;
  try { url = new URL(to, "https://preview.invalid"); } catch { return null; }
  if (url.origin !== "https://preview.invalid") return null;
  if (url.pathname !== "/" && !url.pathname.startsWith("/c/")) return null;
  return `${url.pathname}${url.search}`;
}
