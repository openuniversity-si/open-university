import { createHmac, hkdfSync } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { handlePreviewRequest, type PreviewRouteDeps } from "./preview-route.ts";
import { PREVIEW_LABEL, PREVIEW_MAX_MINUTES, safePreviewTarget, signPreviewToken, verifyPreviewToken } from "./preview-token.ts";

const secret = "test-admin-secret";
const now = new Date("2026-10-11T12:00:00.000Z");
const later = (minutes: number) => new Date(now.getTime() + minutes * 60_000);

describe("preview tokens", () => {
  it("verifies a fresh token with its scope and expiry", () => {
    const { token, expiresAt } = signPreviewToken(secret, "course-6", 30, now);
    expect(expiresAt.toISOString()).toBe("2026-10-11T12:30:00.000Z");
    expect(verifyPreviewToken(secret, token, later(29))).toEqual({ exp: expiresAt.getTime() / 1000, scope: "course-6" });
    expect(verifyPreviewToken(secret, signPreviewToken(secret, null, 5, now).token, now)?.scope).toBeNull();
  });

  it("caps the lifetime at 60 minutes and refuses an expired token", () => {
    const { token, expiresAt } = signPreviewToken(secret, null, 600, now);
    expect(expiresAt.getTime() - now.getTime()).toBe(PREVIEW_MAX_MINUTES * 60_000);
    expect(verifyPreviewToken(secret, token, later(60))).toBeNull();
    expect(signPreviewToken(secret, null, 0, now).expiresAt.getTime() - now.getTime()).toBe(60_000);
  });

  it("refuses tampered, re-scoped, foreign and malformed tokens alike", () => {
    const { token } = signPreviewToken(secret, "course-6", 30, now);
    const [payload, signature] = token.split(".") as [string, string];
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Record<string, unknown>;
    const rescoped = Buffer.from(JSON.stringify({ ...claims, scope: "course-7" })).toString("base64url");
    const extended = Buffer.from(JSON.stringify({ ...claims, exp: Number(claims.exp) + 3600 })).toString("base64url");
    for (const forged of [`${rescoped}.${signature}`, `${extended}.${signature}`, `${payload}.${signature[0] === "A" ? "B" : "A"}${signature.slice(1)}`, `${payload}.${signature}.x`, payload, "", "a.b", "x".repeat(600)]) {
      expect(verifyPreviewToken(secret, forged, now)).toBeNull();
    }
    expect(verifyPreviewToken("another-secret", token, now)).toBeNull();
    expect(verifyPreviewToken(undefined, token, now)).toBeNull();
    expect(verifyPreviewToken(secret, null, now)).toBeNull();
  });

  it("signs with a key derived from the secret, never the raw secret", () => {
    const { token } = signPreviewToken(secret, null, 5, now);
    const [payload] = token.split(".") as [string];
    const raw = createHmac("sha256", secret).update(payload).digest("base64url");
    expect(verifyPreviewToken(secret, `${payload}.${raw}`, now)).toBeNull();
  });

  it("refuses a correctly signed payload with the wrong version or shape", () => {
    const key = Buffer.from(hkdfSync("sha256", secret, "", PREVIEW_LABEL, 32));
    const sign = (claims: unknown) => {
      const payload = Buffer.from(typeof claims === "string" ? claims : JSON.stringify(claims)).toString("base64url");
      return `${payload}.${createHmac("sha256", key).update(payload).digest("base64url")}`;
    };
    const exp = now.getTime() / 1000 + 600;
    expect(verifyPreviewToken(secret, sign({ v: 1, exp, scope: null }), now)).toEqual({ exp, scope: null });
    for (const claims of [{ v: 2, exp, scope: null }, { v: 1, exp: String(exp), scope: null }, { v: 1, exp, scope: 7 }, "not json"]) {
      expect(verifyPreviewToken(secret, sign(claims), now)).toBeNull();
    }
  });
});

describe("preview redirect target (anti open-redirect)", () => {
  it("keeps same-site catalog paths and the Home", () => {
    expect(safePreviewTarget("/")).toBe("/");
    expect(safePreviewTarget("/c/genesis")).toBe("/c/genesis");
    expect(safePreviewTarget("/c/genesis/lecture-1?x=1")).toBe("/c/genesis/lecture-1?x=1");
  });

  it("refuses hosts, protocol-relative, backslash and non-catalog paths", () => {
    for (const bad of [null, "//evil.example", "/\\evil.example", "https://evil.example/c/x", "javascript:alert(1)", "c/genesis", "/api/admin/catalog", "/c/../api", "/ c/x", "/c/x\n", `/${"c".repeat(400)}`]) {
      expect(safePreviewTarget(bad), String(bad)).toBeNull();
    }
  });
});

describe("GET /api/catalog/preview", () => {
  const deps = (overrides: Partial<PreviewRouteDeps> = {}): PreviewRouteDeps & { enable: ReturnType<typeof vi.fn>; disable: ReturnType<typeof vi.fn> } => ({
    secret, now: () => now, enable: vi.fn(() => Promise.resolve()), disable: vi.fn(() => Promise.resolve()), ...overrides,
  } as PreviewRouteDeps & { enable: ReturnType<typeof vi.fn>; disable: ReturnType<typeof vi.fn> });
  const get = (query: string, routeDeps: PreviewRouteDeps) => handlePreviewRequest(new Request(`https://tower.test/api/catalog/preview?${query}`), routeDeps);

  it("enables draft mode for the token's lifetime and redirects 307 to the target, uncached and unindexed", async () => {
    const { token } = signPreviewToken(secret, "course-6", 10, now);
    const routeDeps = deps();
    const response = await get(new URLSearchParams({ token, to: "/c/draft-course" }).toString(), routeDeps);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://tower.test/c/draft-course");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-robots-tag")).toBe("noindex");
    expect(routeDeps.enable).toHaveBeenCalledWith(token, 600);
  });

  it("answers a generic 401 for expired or forged tokens, and 400 for an unsafe target, enabling nothing", async () => {
    const routeDeps = deps();
    const expired = signPreviewToken(secret, null, 1, new Date(now.getTime() - 120_000)).token;
    for (const query of [new URLSearchParams({ token: expired, to: "/" }), new URLSearchParams({ token: "forged.token", to: "/" }), new URLSearchParams({ to: "/" })]) {
      const response = await get(query.toString(), routeDeps);
      expect(response.status).toBe(401);
      expect(await response.text()).toBe("Unauthorized.");
      expect(response.headers.get("cache-control")).toBe("no-store");
    }
    const { token } = signPreviewToken(secret, null, 10, now);
    expect((await get(new URLSearchParams({ token, to: "//evil.example" }).toString(), routeDeps)).status).toBe(400);
    expect(routeDeps.enable).not.toHaveBeenCalled();
    expect((await get(new URLSearchParams({ token }).toString(), deps({ secret: undefined }))).status).toBe(401);
  });

  it("leaves preview with exit=1", async () => {
    const routeDeps = deps();
    const response = await get("exit=1", routeDeps);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://tower.test/");
    expect(routeDeps.disable).toHaveBeenCalledOnce();
  });
});
