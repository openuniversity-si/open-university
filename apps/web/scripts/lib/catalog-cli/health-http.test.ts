import { createServer } from "node:http";
import { once } from "node:events";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { fakeApi, runCli, ORIGIN } from "./cli.test-helpers.ts";
import { rateRetryDelay } from "./client.ts";

it("publish --batch exits zero on its first invocation when public pages are challenged", async () => {
  const api = fakeApi();
  const paths: string[] = [];
  const server = createServer((req, res) => { void (async () => {
    const path = req.url ?? "/";
    paths.push(path);
    if (!path.startsWith("/api/")) { res.writeHead(429); res.end("edge challenge"); return; }
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(Buffer.from(chunk as Uint8Array));
    const body = Buffer.concat(chunks).toString();
    const response = await api.transport({ method: req.method ?? "GET", url: ORIGIN + path, headers: {}, ...(body ? { body } : {}), timeoutMs: 1000, admin: path.startsWith("/api/admin/") });
    res.writeHead(response.status, Object.fromEntries(response.headers)); res.end(response.text);
  })().catch((error: unknown) => { res.destroy(error instanceof Error ? error : new Error("fake server failed")); }); });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("missing HTTP address");
  const directory = mkdtempSync(join(tmpdir(), "health-batch-"));
  const batch = join(directory, "batch.json"); writeFileSync(batch, JSON.stringify(["course-6"]));
  try {
    const result = await runCli(["publish", "--batch", batch, "--note", "API verification", "--yes", "--target", "preview"], { deps: {
      transport: () => async (request) => {
        const url = new URL(request.url);
        const response = await fetch(`http://127.0.0.1:${String(address.port)}${url.pathname}${url.search}`, { method: request.method, headers: request.headers, body: request.body });
        return { status: response.status, headers: response.headers, text: await response.text() };
      },
    } });
    expect(result.code, result.stderr).toBe(0);
    expect(paths.filter((path) => path.startsWith("/api/health"))).toEqual(["/api/health?course=freud"]);
    expect(paths.every((path) => path.startsWith("/api/"))).toBe(true);
    expect(api.requests.filter((request) => request.key === "POST /courses/publish-batch")).toHaveLength(1);
  } finally { await new Promise<void>((resolve) => server.close(() => { resolve(); })); rmSync(directory, { recursive: true }); }
});

it("parses Retry-After seconds and HTTP dates as minimum waits, then adds bounded exponential jitter", () => {
  expect(rateRetryDelay("10", 0, 0, 0)).toBe(10500);
  expect(rateRetryDelay("Thu, 01 Jan 1970 00:00:10 GMT", 1, 1000, 1)).toBe(11000);
  expect(rateRetryDelay("invalid", 2, 0, 0)).toBe(2000);
  expect(rateRetryDelay(null, 3, 0, 1)).toBe(8000);
});
