import { readFileSync } from "node:fs";
import { expect, test } from "./fixtures/no-video-guard.ts";

const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string };

test("GET /api/health returns the build identity, the catalog release and nothing else", async ({ request }) => {
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(response.headers()["cache-control"]).toBe("no-store");

  const body: unknown = await response.json();
  expect(body).toEqual({
    status: "ok",
    version,
    commit: expect.stringMatching(/^([0-9a-f]{7}|local)$/),
    diagnostics: "ok",
    // E2E runs on the test build: the alias swapped in the fake engine (ADR-11).
    engine: "tower-playback-engine:fake",
    // ADR-17: the test build serves the versioned snapshot (release #1) through the fake catalog.
    catalog: { release: 1, sha: expect.stringMatching(/^[0-9a-f]{64}$/), source: "fake" },
  });
});
