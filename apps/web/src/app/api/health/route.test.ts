import { expect, it, vi } from "vitest";
vi.mock("@tower/catalog", () => ({ getCatalogState: () => Promise.resolve({ catalog: { number: 12, courses: [{ slug: "present" }] }, sha: "digest", source: "database" }) }));
vi.mock("@/site/server/build-info", () => ({
  getBuildInfo: () => ({ version: "0.1.0", commit: "abc1234", diagnostics: "ok", engine: "tower-playback-engine:youtube" }),
}));
import { GET } from "./route.ts";
it("confirms presence in the active release, including every requested course", async () => {
  const response = await GET(new Request("https://site.test/api/health?course=present&course=missing"));
  expect(response.status).toBe(404);
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(await response.json()).toEqual({
    status: "ok",
    version: "0.1.0",
    commit: "abc1234",
    diagnostics: "ok",
    engine: "tower-playback-engine:youtube",
    catalog: { release: 12, sha: "digest", source: "database" },
    courses: [{ slug: "present", present: true }, { slug: "missing", present: false }],
  });
  expect((await GET(new Request("https://site.test/api/health?course=present"))).status).toBe(200);
  expect((await GET(new Request("https://site.test/api/health"))).status).toBe(200);
});
