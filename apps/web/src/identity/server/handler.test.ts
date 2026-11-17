import { randomBytes } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

describe("auth route with incomplete configuration", () => {
  beforeEach(() => {
    vi.resetModules();
    for (const name of ["AUTH_SECRET", "AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET", "AUTH_URL", "APP_DATABASE_URL", "SITE_ENV"]) vi.stubEnv(name, "");
    vi.stubEnv("AUTH_URL", "http://127.0.0.1:3999");
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("returns an anonymous session without creating a DB connection", async () => {
    const { handleAuthRequest } = await import("./handler.ts");
    const response = await handleAuthRequest(new Request("http://127.0.0.1:3999/api/auth/get-session"));
    expect(response.status).toBe(200);
    expect(await response.json()).toBeNull();
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-request-id")).toBeTruthy();
  });

  it("makes sign-in unavailable and never pretends a DB sign-out succeeded without storage", async () => {
    const { handleAuthRequest } = await import("./handler.ts");
    for (const path of ["sign-in/social", "sign-out"]) {
      const response = await handleAuthRequest(new Request(`http://127.0.0.1:3999/api/auth/${path}`, { method: "POST" }));
      expect(response.status).toBe(503);
      expect(response.headers.get("x-request-id")).toBeTruthy();
      expect(await response.json()).toMatchObject({ code: "AUTH_UNAVAILABLE" });
    }
  });

  it("returns explicit unavailable feedback without Google credentials even with session configuration", async () => {
    vi.stubEnv("AUTH_SECRET", randomBytes(32).toString("hex"));
    vi.stubEnv("APP_DATABASE_URL", "postgres://localhost/tower_test_unused");
    const { handleAuthRequest } = await import("./handler.ts");
    const response = await handleAuthRequest(new Request("http://127.0.0.1:3999/api/auth/sign-in/social", { method: "POST" }));
    expect(response.status).toBe(503);
    expect(response.headers.get("x-request-id")).toBeTruthy();
    expect(await response.json()).toMatchObject({ code: "GOOGLE_SIGN_IN_UNAVAILABLE" });
  });

  it("redacts invalid configuration from the response and diagnostics", async () => {
    vi.stubEnv("AUTH_SECRET", randomBytes(32).toString("hex"));
    vi.stubEnv("APP_DATABASE_URL", "postgres://localhost/tower_test_unused");
    vi.stubEnv("AUTH_URL", "https://private-config.invalid/path");
    const diagnostic = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { handleAuthRequest } = await import("./handler.ts");
    const response = await handleAuthRequest(new Request("http://127.0.0.1:3999/api/auth/get-session"));
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private-config");
    expect(diagnostic).toHaveBeenCalledExactlyOnceWith(JSON.stringify({ event: "AUTH_REQUEST_FAILED", requestId: response.headers.get("x-request-id") }));
  });
});
