import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import sharp from "sharp";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { createS3Bucket, r2Config, StorageError } from "./r2.ts";
import { createR2MediaStore, uploadMedia } from "../../../scripts/lib/media-storage.ts";
import { createR2Storage } from "../../../fidelity/references/storage.ts";
import { startFakeS3 } from "../../../scripts/lib/s3-fake.test-helpers.ts";

const host = `pub-${"a".repeat(32)}.r2.dev`;
const secret = "fake-secret-value-never-printed";
let s3: Awaited<ReturnType<typeof startFakeS3>>;
let env: Record<string, string>;
beforeAll(async () => {
  process.env.TOWER_MEDIA_PUBLIC_HOST = host;
  s3 = await startFakeS3("AKIDTEST");
  env = { TOWER_MEDIA_PUBLIC_HOST: host, R2_ENDPOINT: s3.endpoint, R2_REGION: "us-east-1", R2_ACCESS_KEY_ID_RW: "AKIDTEST", R2_SECRET_ACCESS_KEY_RW: secret };
});
afterAll(async () => { await s3.close(); delete process.env.TOWER_MEDIA_PUBLIC_HOST; });

describe("R2 config", () => {
  it("only lets a local test server override the Cloudflare endpoint", () => {
    expect(() => r2Config({ ...env, R2_ENDPOINT: "https://evil.example" }, "open-university-media", "rw")).toThrow(StorageError);
    expect(() => r2Config({ R2_ACCOUNT_ID: "nope", R2_ACCESS_KEY_ID_RW: "a", R2_SECRET_ACCESS_KEY_RW: "b" }, "open-university-media", "rw")).toThrow(StorageError);
    expect(r2Config({ R2_ACCOUNT_ID: "f".repeat(32), R2_ACCESS_KEY_ID_RW: "a", R2_SECRET_ACCESS_KEY_RW: "b" }, "open-university-media", "ro").endpoint).toBe(`https://${"f".repeat(32)}.r2.cloudflarestorage.com`);
  });
  it("never puts credentials in error messages", async () => {
    const bucket = createS3Bucket(r2Config({ ...env, R2_ACCESS_KEY_ID_RW: "WRONGKEY" }, "open-university-media", "rw"));
    const error = await bucket.get("covers/x/thumb/a.jpg").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(StorageError);
    expect(String(error)).not.toContain(secret); expect(String(error)).not.toContain("WRONGKEY");
  });
});

describe("R2 media store", () => {
  it("copies server-side with an atomic destination condition, sends no image body and never overwrites", async () => {
    const bucket = createS3Bucket(r2Config(env, "open-university-media", "rw"));
    await bucket.put("covers/copy/source.jpg", Buffer.from("original"), { contentType: "image/jpeg" });
    const sent = vi.spyOn(globalThis, "fetch");
    try {
      expect(await bucket.copy("covers/copy/source.jpg", "m/copy.jpg", "image/jpeg", "public, max-age=31536000, immutable")).toBe("created");
      const request = sent.mock.calls.map(([value]) => value).find((value): value is Request => value instanceof Request && value.headers.has("x-amz-copy-source"));
      expect(request?.headers.get("cf-copy-destination-if-none-match")).toBe("*");
      expect(request?.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
      expect((await request?.clone().arrayBuffer())?.byteLength).toBe(0);
      await bucket.put("covers/copy/other.jpg", Buffer.from("different"), { contentType: "image/jpeg" });
      expect(await bucket.copy("covers/copy/other.jpg", "m/copy.jpg", "image/jpeg", "immutable")).toBe("exists");
      expect(String(await bucket.get("m/copy.jpg"))).toBe("original");
    } finally { sent.mockRestore(); }
  });
  it("retries any pre-response failure, including reset and timeout, at most five attempts", async () => {
    const bucket = createS3Bucket(r2Config(env, "open-university-media", "rw"));
    await bucket.put("covers/retry/a.jpg", Buffer.from("bytes"), { contentType: "image/jpeg" });
    const failed = (name: string, code?: string) => Object.assign(new TypeError("fetch failed"), { name, cause: code ? { code } : undefined });
    const real = globalThis.fetch;
    const sent = vi.spyOn(globalThis, "fetch");
    try {
      sent.mockImplementationOnce(() => Promise.reject(failed("TimeoutError", "UND_ERR_CONNECT_TIMEOUT")));
      expect((await bucket.head("covers/retry/a.jpg"))?.size).toBe(5);
      expect(sent).toHaveBeenCalledTimes(2);
      sent.mockClear();
      sent.mockImplementationOnce(() => Promise.reject(failed("TypeError", "ECONNRESET")));
      expect((await bucket.head("covers/retry/a.jpg"))?.size).toBe(5);
      expect(sent).toHaveBeenCalledTimes(2);
      sent.mockClear();
      sent.mockImplementation(() => Promise.reject(failed("TimeoutError")));
      await expect(bucket.put("m/retry.jpg", Buffer.from("x"), { contentType: "image/jpeg" })).rejects.toThrow("failed before a response");
      expect(sent).toHaveBeenCalledTimes(5);
    } finally { sent.mockRestore(); globalThis.fetch = real; }
  });
  it("uploads immutable keys with the R2 public URL and never overwrites", async () => {
    const dir = await mkdtemp(resolve(tmpdir(), "tower-r2-test-"));
    try {
      const file = resolve(dir, "cover.png");
      await writeFile(file, await sharp({ create: { width: 16, height: 9, channels: 3, background: "teal" } }).png().toBuffer());
      const store = createR2MediaStore(env, "rw");
      const asset = await uploadMedia("lesson", "genesis-1", "cover_16x9", "default", file, store, { alt: "Genesis lesson 1", designStatus: "approved", transform: null });
      expect(new URL(asset.url).hostname).toBe(host);
      expect(s3.objects.has(`/open-university-media/${asset.pathname}`)).toBe(true);
      expect(await store.put(asset.pathname, Buffer.from("other bytes"))).toBe("exists");
      expect((await store.get(asset.pathname))?.length).toBe((await store.head(asset.pathname))?.size);
      const puts = s3.requests.filter((request) => request.startsWith("PUT")).length;
      await uploadMedia("lesson", "genesis-1", "cover_16x9", "default", file, store, { alt: "Genesis lesson 1", designStatus: "approved", transform: null });
      expect(s3.requests.filter((request) => request.startsWith("PUT")).length).toBe(puts);
    } finally { await rm(dir, { recursive: true, force: true }); }
  });

  it("serves a hashed poster as immutable for a year (P8: content-addressed covers/<owner>/<kind>/<sha>.webp)", async () => {
    const dir = await mkdtemp(resolve(tmpdir(), "tower-r2-test-"));
    const sent = vi.spyOn(globalThis, "fetch");
    try {
      const file = resolve(dir, "poster.webp");
      await writeFile(file, await sharp({ create: { width: 9, height: 16, channels: 3, background: "navy" } }).webp().toBuffer());
      const asset = await uploadMedia("course", "course-1", "poster_9x16", "default", file, createR2MediaStore(env, "rw"), { alt: "Genesis", designStatus: "approved", transform: null });
      expect(asset.pathname).toMatch(/^m\/[0-9a-f]{64}\.webp$/);
      const put = sent.mock.calls.map(([request]) => request).find((request): request is Request => request instanceof Request && request.method === "PUT");
      expect(put?.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
    } finally { sent.mockRestore(); await rm(dir, { recursive: true, force: true }); }
  });
});

describe("R2 fidelity store", () => {
  it("resolves the Cloudflare object URL of the bucket to its key", async () => {
    const storage = createR2Storage(r2Config(env, "the-tower-fidelity", "rw"));
    const { url } = await storage.put("fidelity/123/home-mobile.png", Buffer.from("png"));
    expect(url).toBe(`${s3.endpoint}/the-tower-fidelity/fidelity/123/home-mobile.png`);
    expect((await storage.head("fidelity/123/home-mobile.png"))?.size).toBe(3);
    expect(String(await storage.get(`https://${"a".repeat(32)}.r2.cloudflarestorage.com/the-tower-fidelity/fidelity/123/home-mobile.png`))).toBe("png");
    await storage.delete([url]);
    expect(await storage.get(url)).toBeNull();
    await expect(storage.get("https://evil.example/the-tower-fidelity/x.png")).rejects.toThrow(StorageError);
  });
});
