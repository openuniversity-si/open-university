import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ revalidateTag: vi.fn(), revalidatePath: vi.fn(), unstable_cache: (read: () => unknown) => read }));
vi.mock("next/headers", () => ({ draftMode: () => Promise.resolve({ isEnabled: false }), cookies: () => Promise.resolve({ get: () => undefined }) }));
import { adminRateLimiter } from "../platform/security/rate-limit.ts";
import { adminCatalogDeps } from "../catalog/server/deps.ts";
import { GET as catalogGet } from "../app/api/admin/catalog/[...route]/route.ts";
import { DELETE as mediaDelete, GET as mediaGet, POST as mediaPost } from "../app/api/admin/media/[[...route]]/route.ts";

describe("Next wiring of the admin catalog API", () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

  it("reads the media admin secret and shares the instance limiter", () => {
    vi.stubEnv("TOWER_ADMIN_MEDIA_SECRET", "from-env");
    const deps = adminCatalogDeps();
    expect(deps.secret).toBe("from-env");
    expect(deps.limiter).toBe(adminRateLimiter);
    expect(deps.now()).toBeInstanceOf(Date);
    expect(deps.uuid()).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("route exports answer through the shared guard before touching the database", async () => {
    vi.stubEnv("TOWER_ADMIN_MEDIA_SECRET", "");
    const unconfigured = await catalogGet(new Request("https://tower.test/api/admin/catalog/courses/course-1"));
    expect(unconfigured.status).toBe(503);
    expect(unconfigured.headers.get("cache-control")).toBe("no-store");
    vi.stubEnv("TOWER_ADMIN_MEDIA_SECRET", "from-env");
    const unauthorized = await catalogGet(new Request("https://tower.test/api/admin/catalog/doctor", { headers: { "x-request-id": "next-1" } }));
    expect(unauthorized.status).toBe(401);
    expect(await unauthorized.json()).toEqual({ ok: false, error: { code: "unauthorized", message: "Unauthorized." }, requestId: "next-1" });
  });

  it("accepts Next's context on a static route, whose params promise resolves to undefined", async () => {
    vi.stubEnv("TOWER_ADMIN_MEDIA_SECRET", "from-env");
    const headers = { authorization: "Bearer from-env", "x-forwarded-for": "192.0.2.77" };
    vi.spyOn(adminRateLimiter, "authenticated").mockResolvedValue(0);
    const response = await catalogGet(new Request("https://tower.test/api/admin/catalog/texts", { headers }), { params: Promise.resolve(undefined) });
    expect(response.status).toBe(400);
    expect(((await response.json()) as { error: { message: string } }).error.message).toBe("Invalid query.");
  });

  it("serves the media root and a subpath from the optional catch-all", async () => {
    vi.stubEnv("TOWER_ADMIN_MEDIA_SECRET", "");
    expect((await mediaGet(new Request("https://tower.test/api/admin/media"))).status).toBe(503);
    expect((await mediaPost(new Request("https://tower.test/api/admin/media/check", { method: "POST" }))).status).toBe(503);
    expect((await mediaDelete(new Request("https://tower.test/api/admin/media", { method: "DELETE" }))).status).toBe(503);
  });
});
