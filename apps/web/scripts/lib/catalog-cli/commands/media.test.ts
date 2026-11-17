import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, symlinkSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ApiClient, type Transport, type WireResponse } from "../client.ts";
import type { PreparedMedia } from "../client.ts";
import { checkPublicAsset, mediaKeyFor, uploadPrepared, type MediaCliDeps, type MediaIntent } from "./media.ts";
import { EXIT } from "../errors.ts";
import { Output } from "../io.ts";
import { fakeApi, runCli } from "../cli.test-helpers.ts";

const intent: MediaIntent = { target: "preview", owner: "course", ownerId: "course-6", kind: "poster_9x16", variant: "default", alt: "Poster", forceOversize: false };
const media: PreparedMedia = { bytes: new Uint8Array([1, 2, 3]), sha256: "ab".repeat(32), extension: "webp", contentType: "image/webp", width: 8, height: 8 };

function scripted(responses: readonly WireResponse[], now = () => 0, deadlineMs = 120_000): { client: ApiClient; sent: () => string[]; calls: () => string[] } {
  let index = 0;
  const calls: string[] = [];
  const transport: Transport = (request) => {
    calls.push(new URL(request.url).pathname);
    const response = responses[index];
    index += 1;
    if (!response) return Promise.reject(new Error("no scripted response"));
    return Promise.resolve(response);
  };
  const client = new ApiClient({
    origin: "https://tower0test.lambda-url.us-east-1.on.aws", target: "preview", transport, actor: "cli", uuid: () => "00000000-0000-4000-8000-000000000001",
    sleep: () => Promise.resolve(), dryRun: false, now, deadlineMs, out: new Output({ stdout: () => undefined, stderr: () => undefined, prompt: null }, false, []),
    fixedKey: undefined, intent: () => ({ command: "media", args: {}, files: {}, window: "w" }),
  });
  client.confirmed = true;
  return { client, sent: () => client.sent.map((entry) => entry.key), calls: () => calls };
}

const ok = (data: unknown, status = 200, headers: Record<string, string> = {}): WireResponse => ({ status, headers: new Headers(headers), text: JSON.stringify({ ok: true, data, requestId: "req-1" }) });
const fail = (status: number, code: string, message: string, headers: Record<string, string> = {}): WireResponse => ({ status, headers: new Headers(headers), text: JSON.stringify({ ok: false, error: { code, message }, requestId: "req-1" }) });

function deps(client: ApiClient, extra: Partial<MediaCliDeps> = {}): MediaCliDeps {
  return { client: { call: (input, decode) => client.adminCall(input, decode) }, prepare: () => Promise.resolve(media), confirm: () => Promise.resolve(), keyFor: mediaKeyFor, ...extra };
}

describe("media upload", () => {
  it("uploads new bytes and attaches them under different keys (the journal refuses one key on two routes)", async () => {
    // admin_idempotency.key is global: a key seen on /objects and then sent to /attach is a 422 idempotency_mismatch.
    const journal = new Map<string, string>();
    const sent: { path: string; key: string | undefined }[] = [];
    const transport: Transport = (request) => {
      const path = new URL(request.url).pathname;
      const key = Object.entries(request.headers).find(([name]) => name.toLowerCase() === "idempotency-key")?.[1];
      sent.push({ path, key });
      if (key !== undefined) {
        const seen = journal.get(key);
        if (seen !== undefined && seen !== path) return Promise.resolve(fail(422, "idempotency_mismatch", "This Idempotency-Key was used for a different request; use a new key."));
        journal.set(key, path);
      }
      if (path.endsWith("/check")) return Promise.resolve(ok({ missing: [media.sha256], objects: [] }));
      return Promise.resolve(ok({ sha256: media.sha256 }));
    };
    const client = new ApiClient({
      origin: "https://tower0test.lambda-url.us-east-1.on.aws", target: "preview", transport, actor: "cli", uuid: () => "00000000-0000-4000-8000-000000000001",
      sleep: () => Promise.resolve(), dryRun: false, now: () => 0, deadlineMs: 120_000, out: new Output({ stdout: () => undefined, stderr: () => undefined, prompt: null }, false, []),
      fixedKey: undefined, intent: () => ({ command: "media", args: {}, files: {}, window: "w" }),
    });
    client.confirmed = true;
    await uploadPrepared(deps(client), { media, intent, dryRun: false, attach: true });
    expect(sent.map((entry) => entry.path.replace("/api/admin/media", ""))).toEqual(["/check", "/objects", "/attach"]);
    const [objects, attach] = [sent[1]?.key, sent[2]?.key];
    expect(objects).toBe(mediaKeyFor("media:POST /objects", intent, media.sha256));
    expect(attach).toBe(mediaKeyFor("media:POST /attach", intent, media.sha256));
    expect(objects).not.toBe(attach);
  });

  it("sends no mutating call on a dry-run and no object upload when the check hits", async () => {
    const dry = scripted([]);
    const result = await uploadPrepared(deps(dry.client), { media, intent, dryRun: true, attach: true });
    expect(result.sha256).toBe(media.sha256);
    expect(dry.sent()).toEqual([]);
    const hit = scripted([ok({ missing: [], objects: [{ sha256: media.sha256, url: result.url }] }), ok({ sha256: media.sha256, url: result.url })]);
    await uploadPrepared(deps(hit.client), { media, intent, dryRun: false, attach: true });
    expect(hit.sent()).toEqual(["media:POST /check", "media:POST /attach"]);
  });

  it("retries 429 with the same key, stops at the deadline, and does not retry 422", async () => {
    const retried = scripted([
      fail(429, "rate_limited", "slow", { "retry-after": "0" }),
      ok({ missing: [media.sha256], objects: [] }),
      ok({ sha256: media.sha256, url: `https://media.openuniversity.si/m/${media.sha256}.webp` }),
    ], () => 0);
    const keys: string[] = [];
    const original = retried.client;
    const seeing: MediaCliDeps = { ...deps(original), client: { call: (input, decode) => { if (input.idempotencyKey) keys.push(input.idempotencyKey); return original.adminCall(input, decode); } } };
    await uploadPrepared(seeing, { media, intent, dryRun: false, attach: false });
    expect(keys).toEqual([mediaKeyFor("media:POST /objects", intent, media.sha256)]);
    expect(retried.calls().filter((path) => path.endsWith("/check")).length).toBe(2);
    const late = scripted([fail(429, "rate_limited", "slow", { "retry-after": "100" })], () => 0, 1_000);
    await expect(uploadPrepared(deps(late.client), { media, intent, dryRun: false, attach: false })).rejects.toThrow(/deadline/);
    const mismatch = scripted([fail(422, "idempotency_mismatch", "different body")]);
    await expect(uploadPrepared(deps(mismatch.client), { media, intent, dryRun: false, attach: false })).rejects.toThrow(/different body/);
    expect(mismatch.sent()).toEqual(["media:POST /check"]);
  });

  it("does not attach or call the catalog when the object upload fails", async () => {
    const broken = scripted([ok({ missing: [media.sha256], objects: [] }), fail(502, "upstream_failed", "down"), fail(502, "upstream_failed", "down"), fail(502, "upstream_failed", "down")]);
    await expect(uploadPrepared(deps(broken.client), { media, intent, dryRun: false, attach: true })).rejects.toThrow(/down/);
    expect(broken.sent().filter((key) => key === "media:POST /objects")).toHaveLength(1);
    expect(broken.sent()).not.toContain("media:POST /attach");
    expect(broken.sent().some((key) => key.startsWith("catalog:"))).toBe(false);
  });
});

describe("media command parity", () => {
  const app = fileURLToPath(new URL("../../../../", import.meta.url));
  it("lists the nine commands and refuses read-only writes", async () => {
    const help = await runCli(["media", "--help"]);
    for (const name of ["put", "object-put", "list", "rollback", "delete", "check", "prune-inherited", "install", "migrate-content"]) expect(help.stdout).toContain(name);
    for (const flag of ["--course", "--lesson", "--subarea", "--variant", "--version", "--all", "--force-oversize", "--budget", "--registry", "--read-only-api", "--apply", "--report", "--dry-run"]) expect(help.stdout).toContain(flag);
    const readonly = fakeApi();
    const refused = await runCli(["media", "prune-inherited", "--read-only-api", "--apply", "--target", "preview"], { api: readonly });
    expect(refused.code).toBe(EXIT.usage);
    expect(readonly.requests.some((request) => request.method !== "GET" && request.key.startsWith("media:"))).toBe(false);
    expect((await runCli(["covers", "course-6", "--dir", "/tmp", "--parallel", "33", "--target", "preview"])).code).toBe(EXIT.usage);
    expect((await runCli(["covers", "course-6", "--dir", "/tmp", "--parallel", "0", "--target", "preview"])).code).toBe(EXIT.usage);
  });

  it("delegates the installed symlink to tower-catalog media without calling itself", () => {
    const wrapper = join(app, "tooling/tower-media");
    const lines = readFileSync(wrapper, "utf8").trim().split("\n");
    expect(lines.length).toBeLessThanOrEqual(10);
    expect(readFileSync(wrapper, "utf8")).not.toMatch(/curl|budget_of/);
    const dir = mkdtempSync(join(tmpdir(), "tower-media-link-"));
    symlinkSync(wrapper, join(dir, "tower-media"));
    const result = spawnSync(join(dir, "tower-media"), ["--help"], { encoding: "utf8" });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("migrate-content");
    expect(result.stdout).not.toContain("recursive");
  });

  it("checks the public GET when HEAD would describe a different object", async () => {
    const bytes = Buffer.from("public-object");
    const hash = createHash("sha256").update(bytes).digest("hex");
    const seen = { head: 0, get: 0 };
    const server = createServer((req, res) => {
      if (req.method === "HEAD") {
        seen.head += 1;
        res.writeHead(200, { "content-type": "text/html", "content-length": "0" });
        res.end();
        return;
      }
      seen.get += 1;
      res.writeHead(200, { "content-type": "image/png", "content-length": String(bytes.length) });
      res.end(bytes);
    });
    await new Promise<void>((resolve) => { server.listen(0, "127.0.0.1", () => { resolve(); }); });
    const port = (server.address() as AddressInfo).port;
    try {
      const probe = await checkPublicAsset(fetch, `http://127.0.0.1:${String(port)}/m/${hash}.png`);
      expect(probe).toMatchObject({ status: 200, type: "image/png", hash });
      expect(probe.bytes.byteLength).toBe(bytes.length);
      expect(seen).toEqual({ head: 0, get: 1 });
    } finally {
      await new Promise<void>((resolve) => { server.close(() => { resolve(); }); });
    }
  });
});
