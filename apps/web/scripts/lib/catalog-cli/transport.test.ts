import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ApiClient, fetchTransport, type Transport } from "./client.ts";
import { NetworkError } from "./errors.ts";
import { Output } from "./io.ts";

const credentials = { secrets: { prod: "k-prod", preview: "k-preview" } };
const request = (timeoutMs: number) => ({ method: "GET", url: "https://x0preview.lambda-url.us-east-1.on.aws/api/admin/catalog/courses/c-1", headers: {}, timeoutMs, admin: true });
const hanging = (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch;
const endless = (() => Promise.resolve(new Response(new ReadableStream({ start() { /* never enqueues or closes */ } }), { status: 200 }))) as unknown as typeof fetch;
const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

describe("fetchTransport deadline", () => {
  it("times out a request that never answers, even when fetch ignores the signal", async () => {
    await expect(fetchTransport(credentials, "preview", hanging)(request(50))).rejects.toThrow(new NetworkError("GET /api/admin/catalog/courses/c-1: timeout after 0.05 s"));
  });

  it("times out a body that never ends after the headers arrived", async () => {
    await expect(fetchTransport(credentials, "preview", endless)(request(50))).rejects.toThrow("timeout after 0.05 s");
  });

  it("keeps the process alive until the deadline instead of draining with exit 13", () => {
    const dir = mkdtempSync(join(tmpdir(), "transport-"));
    const script = join(dir, "hang.ts");
    writeFileSync(script, [
      `import { fetchTransport } from ${JSON.stringify(here("./client.ts"))};`,
      "const hanging = () => new Promise(() => undefined);",
      "try {",
      `  await fetchTransport({ secrets: { prod: "p", preview: "v" } }, "preview", hanging)({ method: "GET", url: "https://x0preview.lambda-url.us-east-1.on.aws/a", headers: {}, timeoutMs: 200, admin: true });`,
      "} catch (error) { console.error(String(error.message)); process.exitCode = 7; }",
    ].join("\n"));
    const result = spawnSync(process.execPath, [script], { encoding: "utf8", timeout: 20_000 });
    expect([result.status, result.stderr.trim()]).toEqual([7, "GET /a: timeout after 0.2 s"]);
  });

  it("retries a GET whose first attempt timed out", async () => {
    let calls = 0;
    const flaky = ((...args: Parameters<typeof fetch>) => { calls += 1; return calls === 1 ? hanging(...args) : Promise.resolve(Response.json({ ok: true, data: { course: { id: "c-1" } }, requestId: "r" })); }) as typeof fetch;
    const inner = fetchTransport(credentials, "preview", flaky);
    const transport: Transport = (wire) => inner({ ...wire, timeoutMs: 50 });
    const client = new ApiClient({
      origin: "https://x0preview.lambda-url.us-east-1.on.aws", target: "preview", transport, actor: "cli", uuid: () => "00000000-0000-4000-8000-000000000001",
      sleep: () => Promise.resolve(), dryRun: false, out: new Output({ stdout: () => undefined, stderr: () => undefined, prompt: null }, false, []),
      fixedKey: undefined, intent: () => ({ command: "course get", args: {}, files: {}, window: "w" }),
    });
    const result = await client.call("GET /courses/:id", { params: { id: "c-1" } });
    expect(calls).toBe(2);
    expect(result.data).toEqual({ course: { id: "c-1" } });
  });
});

function clientFor(transport: Transport): ApiClient {
  return new ApiClient({
    origin: "https://x0preview.lambda-url.us-east-1.on.aws", target: "preview", transport, actor: "cli", uuid: () => "00000000-0000-4000-8000-000000000001",
    sleep: () => Promise.resolve(), dryRun: false, out: new Output({ stdout: () => undefined, stderr: () => undefined, prompt: null }, false, []),
    fixedKey: undefined, intent: () => ({ command: "check", args: {}, files: {}, window: "w" }),
  });
}

const dropped = (code: string) => Object.assign(new Error("other side closed"), { code, cause: Object.assign(new Error("read ECONNRESET"), { code: "ECONNRESET" }) });

describe("read-only POST retry", () => {
  it("retries a read-only POST after a network error and then succeeds", async () => {
    let calls = 0;
    const fetchImpl = (() => {
      calls += 1;
      if (calls === 1) return Promise.reject(new TypeError("fetch failed", { cause: dropped("UND_ERR_SOCKET") }));
      return Promise.resolve(Response.json({ ok: true, data: { missing: [], objects: [] }, requestId: "r" }));
    }) as typeof fetch;
    const client = clientFor(fetchTransport(credentials, "preview", fetchImpl));
    const result = await client.adminCall({ routeId: "media:POST /check", params: {}, query: {}, payload: { kind: "json", value: { sha256: ["ab".repeat(32)] } } }, (raw) => raw);
    expect(calls).toBe(2);
    expect(result.data).toEqual({ missing: [], objects: [] });
    expect(client.sent.map((entry) => entry.idempotencyKey)).toEqual([null]);
  });

  it("retries a read-only catalog POST through the same rule", async () => {
    let calls = 0;
    const fetchImpl = (() => {
      calls += 1;
      if (calls === 1) return Promise.reject(new TypeError("fetch failed", { cause: dropped("ECONNRESET") }));
      return Promise.resolve(Response.json({ ok: true, data: { environment: "preview", complete: true, references: [] }, requestId: "r" }));
    }) as typeof fetch;
    const result = await clientFor(fetchTransport(credentials, "preview", fetchImpl)).call("POST /lifecycle/inventory");
    expect(calls).toBe(2);
    expect(result.data).toEqual({ environment: "preview", complete: true, references: [] });
  });

  it("does not retry an unkeyed write", async () => {
    let calls = 0;
    const fetchImpl = (() => {
      calls += 1;
      return Promise.reject(new TypeError("fetch failed", { cause: dropped("UND_ERR_SOCKET") }));
    }) as typeof fetch;
    const client = clientFor(fetchTransport(credentials, "preview", fetchImpl));
    await expect(client.call("POST /redirects", { body: { from: "/c/a", to: "/c/b" } })).rejects.toThrow(NetworkError);
    expect(calls).toBe(1);
    expect(client.sent.map((entry) => entry.idempotencyKey)).toEqual([null]);
  });
});

describe("fetchTransport cause", () => {
  it("names the cause code and message and keeps the secret, header and body out", async () => {
    const secret = "k-preview";
    const body = `{"sha256":["${"cd".repeat(32)}"],"note":"${secret}"}`;
    const header = `Bearer ${secret}`;
    const cause = Object.assign(new Error(`other side closed ${header} ${body}`), {
      code: "UND_ERR_SOCKET",
      cause: Object.assign(new Error("read ECONNRESET"), { code: "ECONNRESET" }),
    });
    const fetchImpl = (() => Promise.reject(new TypeError("fetch failed", { cause }))) as typeof fetch;
    const error = await fetchTransport(credentials, "preview", fetchImpl)({
      method: "POST", url: "https://x0preview.lambda-url.us-east-1.on.aws/api/admin/media/check?x=query-sentinel",
      headers: { authorization: header }, body, timeoutMs: 1000, admin: true,
    }).then(() => { throw new Error("expected a network error"); }, (caught: unknown) => caught);
    expect(error).toBeInstanceOf(NetworkError);
    const message = (error as Error).message;
    expect(message).toBe("POST /api/admin/media/check: TypeError: UND_ERR_SOCKET ECONNRESET other side closed");
    expect(message).not.toContain(secret);
    expect(message).not.toContain(body);
    expect(message).not.toContain("query-sentinel");
    expect(message).not.toContain("authorization");
  });
});

describe("runToCompletion", () => {
  it("turns a drained event loop into a visible non-zero exit", () => {
    const dir = mkdtempSync(join(tmpdir(), "drain-"));
    const script = join(dir, "drain.ts");
    writeFileSync(script, [
      `import { runToCompletion } from ${JSON.stringify(here("./drain.ts"))};`,
      "await runToCompletion(() => new Promise((_, reject) => AbortSignal.timeout(30_000).addEventListener(\"abort\", reject)));",
    ].join("\n"));
    const result = spawnSync(process.execPath, [script], { encoding: "utf8", timeout: 20_000 });
    expect(result.status).toBe(7);
    expect(result.stderr).toContain("the process stopped with a request still pending and no answer; nothing was confirmed");
  });

  it("keeps main's exit code when it settles", () => {
    const dir = mkdtempSync(join(tmpdir(), "drain-ok-"));
    const script = join(dir, "ok.ts");
    writeFileSync(script, `import { runToCompletion } from ${JSON.stringify(here("./drain.ts"))};\nawait runToCompletion(() => Promise.resolve(4));\n`);
    const result = spawnSync(process.execPath, [script], { encoding: "utf8", timeout: 20_000 });
    expect([result.status, result.stderr]).toEqual([4, ""]);
  });
});
