import { describe, expect, it } from "vitest";
import { adminAuthorized, adminRateLimiter, adminReply, authorizeAdmin, clientIp, createAdminRateLimiter } from "./auth.ts";
import { adminRateLimiter as singleton } from "../platform/security/rate-limit.ts";
import { createAdminRateLimiter as fromMedia } from "../media/server/admin.ts";

const secret = "test-admin-secret";
const request = (headers: Record<string, string> = {}) => new Request("https://tower.test/api/admin/catalog/courses", { headers });
const bearer = (token: string, ip = "203.0.113.7") => request({ authorization: `Bearer ${token}`, "x-forwarded-for": `${ip}, 10.0.0.1` });

describe("shared admin guard", () => {
  it("answers 503 without a secret, before counting anything", async () => {
    const limiter = createAdminRateLimiter({ requests: 1, failures: 1 });
    expect(await authorizeAdmin(bearer("x"), { secret: undefined, limiter })).toEqual({ status: 503, reason: "unconfigured" });
    expect(await authorizeAdmin(bearer(secret), { secret, limiter })).toBeNull();
  });

  it("answers 401 for a missing or wrong Bearer and counts each as a failed auth for the IP", async () => {
    const limiter = createAdminRateLimiter({ requests: 100, failures: 2 });
    const deps = { secret, limiter };
    expect(await authorizeAdmin(request({ "x-forwarded-for": "198.51.100.1" }), deps)).toEqual({ status: 401, reason: "unauthorized" });
    expect(await authorizeAdmin(bearer("wrong", "198.51.100.1"), deps)).toEqual({ status: 401, reason: "unauthorized" });
    // Failed authentication exhausts the IP allowance; a valid Bearer still has its own quota.
    expect(await authorizeAdmin(bearer("wrong", "198.51.100.1"), deps)).toMatchObject({ status: 429, reason: "rate_limited", retryAfter: expect.any(Number) as number });
    expect(await authorizeAdmin(bearer(secret, "198.51.100.1"), deps)).toBeNull();
    expect(await authorizeAdmin(bearer(secret, "198.51.100.2"), deps)).toBeNull();
  });

  it("answers 429 above the request limit and recovers in the next window", async () => {
    let now = 0;
    const limiter = createAdminRateLimiter({ requests: 2, failures: 10, authenticated: 2 }, 60_000, () => now);
    const deps = { secret, limiter };
    expect(await authorizeAdmin(bearer(secret), deps)).toBeNull();
    expect(await authorizeAdmin(bearer(secret), deps)).toBeNull();
    expect(await authorizeAdmin(bearer(secret), deps)).toEqual({ status: 429, reason: "rate_limited", retryAfter: 60 });
    now = 60_000;
    expect(await authorizeAdmin(bearer(secret), deps)).toBeNull();
  });

  it("keeps the production limits: 30 requests and 10 failed auths per IP per minute", () => {
    const requests = createAdminRateLimiter();
    expect(Array.from({ length: 31 }, () => requests.allow("a")).filter(Boolean)).toHaveLength(30);
    const failures = createAdminRateLimiter();
    for (let index = 0; index < 10; index += 1) failures.fail("b");
    expect(failures.allow("b")).toBe(false);
  });

  it("admits 600 authenticated requests across IPs, independent of anonymous traffic", async () => {
    const limiter = createAdminRateLimiter({ requests: 1, failures: 1, authenticated: 600 });
    const deps = { secret, limiter };
    await authorizeAdmin(bearer("wrong"), deps);
    for (let i = 0; i < 600; i++) expect(await authorizeAdmin(bearer(secret, String(i % 2)), deps)).toBeNull();
    const denial = await authorizeAdmin(bearer(secret, "third-ip"), deps);
    expect(denial).toMatchObject({ status: 429, retryAfter: expect.any(Number) as number });
    expect(await authorizeAdmin(bearer("another-secret"), { secret: "another-secret", limiter })).toBeNull();
  });

  it("fails closed when the shared counter is unavailable", async () => {
    const limiter = { ...createAdminRateLimiter(), authenticated: () => Promise.reject(new Error("offline")) };
    expect(await authorizeAdmin(bearer(secret), { secret, limiter })).toMatchObject({ status: 503 });
  });

  it("compares tokens in constant time over digests, so length differences do not throw", () => {
    expect(adminAuthorized(`Bearer ${secret}`, secret)).toBe(true);
    expect(adminAuthorized(`Bearer ${secret}-longer`, secret)).toBe(false);
    expect(adminAuthorized(secret, secret)).toBe(false);
    expect(adminAuthorized(null, secret)).toBe(false);
    expect(adminAuthorized(`Bearer ${secret}`, undefined)).toBe(false);
  });

  it("takes the first forwarded address, then x-real-ip", () => {
    expect(clientIp(request({ "x-forwarded-for": " 192.0.2.4 , 10.0.0.1" }))).toBe("192.0.2.4");
    expect(clientIp(request({ "x-real-ip": "192.0.2.5" }))).toBe("192.0.2.5");
    expect(clientIp(request())).toBe("unknown");
  });

  it("marks every reply no-store, whatever headers the caller adds", async () => {
    const reply = adminReply({ ok: true }, 201, { "Cache-Control": "public, max-age=60", "x-request-id": "r-1" });
    expect(reply.status).toBe(201);
    expect(reply.headers.get("cache-control")).toBe("no-store");
    expect(reply.headers.get("x-request-id")).toBe("r-1");
    expect(await reply.json()).toEqual({ ok: true });
    expect(adminReply({ error: "x" }, 401).headers.get("cache-control")).toBe("no-store");
  });

  it("shares one limiter per instance between media and catalog, and media re-exports the factory", () => {
    expect(adminRateLimiter).toBe(singleton);
    expect(fromMedia).toBe(createAdminRateLimiter);
  });
});
