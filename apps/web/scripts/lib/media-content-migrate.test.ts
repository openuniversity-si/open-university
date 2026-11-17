import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import type { AddressInfo } from "node:net";
import type * as Dns from "node:dns";
import sharp from "sharp";
import { describe, expect, it } from "vitest";
import type { MediaObject } from "../../src/media/server/objects.ts";
import type { MediaObjectStore } from "../../src/media/server/storage.ts";
import { StorageError } from "./r2.ts";
import { installMigrationDnsCache } from "./migrate-dns.ts";
import { applyContentBatches, assertSampleScope, auditContentSources, copyContent, planFromReferences, publicContentStore, contentBatches, publicFetch, selectContentSample, verifyInventory, type ContentPlan, type ContentReference } from "./media-content-migrate.ts";
import { createBulkR2Store, mapLimited, r2Concurrency } from "./r2-bulk.ts";

const nodeRequire = createRequire(import.meta.url);

describe("migration R2 concurrency", () => {
  it("defaults to 4 and accepts a positive integer", () => {
    expect(r2Concurrency({})).toBe(4);
    expect(r2Concurrency({ R2_CONCURRENCY: "" })).toBe(4);
    expect(r2Concurrency({ R2_CONCURRENCY: "   " })).toBe(4);
    expect(r2Concurrency({ R2_CONCURRENCY: "2" })).toBe(2);
  });
  it("rejects values that are not positive integers", () => {
    expect(() => r2Concurrency({ R2_CONCURRENCY: "0" })).toThrow(StorageError);
    expect(() => r2Concurrency({ R2_CONCURRENCY: "nope" })).toThrow(StorageError);
    expect(() => r2Concurrency({ R2_CONCURRENCY: "1.5" })).toThrow(StorageError);
    expect(() => r2Concurrency({ R2_CONCURRENCY: "-3" })).toThrow(StorageError);
  });
  it("runs at most R2_CONCURRENCY workers and stops new work after the first failure", async () => {
    let active = 0;
    let peak = 0;
    const gate = mapLimited([0, 1, 2, 3], async (item) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 30));
      active -= 1;
      if (item === 1) throw new Error("stop");
      return item;
    }, { R2_CONCURRENCY: "2" });
    await expect(gate).rejects.toThrow("stop");
    expect(peak).toBe(2);
  });
  it("resolves the public media host once for a bulk store", async () => {
    const dns = nodeRequire("node:dns") as typeof Dns;
    const original = dns.lookup;
    let calls = 0;
    dns.lookup = ((hostname: string, options: Dns.LookupOptions | ((err: NodeJS.ErrnoException | null, address: string, family: number) => void), callback?: (err: NodeJS.ErrnoException | null, address: string, family: number) => void) => {
      calls += 1;
      const done = typeof options === "function" ? options : callback;
      done?.(null, "203.0.113.7", 4);
    }) as typeof dns.lookup;
    createBulkR2Store({ R2_ENDPOINT: "http://127.0.0.1:9", R2_ACCESS_KEY_ID_RW: "AKIDTEST", R2_SECRET_ACCESS_KEY_RW: "secret", R2_REGION: "auto" }, "rw");
    const restore = installMigrationDnsCache(["media.openuniversity.si"]);
    const lookup = (hostname: string) => new Promise<string>((resolve, reject) => {
      dns.lookup(hostname, {}, (err, address) => { if (err) reject(err); else resolve(address); });
    });
    try {
      await expect(lookup("media.openuniversity.si")).resolves.toBe("203.0.113.7");
      await expect(lookup("media.openuniversity.si")).resolves.toBe("203.0.113.7");
      expect(calls).toBe(1);
    } finally {
      restore();
      dns.lookup = original;
    }
  });
});

const hash = (label: string) => createHash("sha256").update(label).digest("hex");

function ref(sha256: string, pathname: string, table = "catalog_media"): ContentReference {
  return { table, id: sha256.slice(0, 8), field: "asset", sha256, url: `https://media.openuniversity.si/${pathname}`, pathname, width: 2, height: 2, previous: null };
}

describe("public media fetch", () => {
  it("retries a timeout and returns the first response", async () => {
    let calls = 0;
    const response = new Response(null, { status: 200 });
    const request = (() => {
      calls += 1;
      if (calls < 3) return Promise.reject(Object.assign(new TypeError("fetch failed"), { cause: { code: "ETIMEDOUT" } }));
      return Promise.resolve(response);
    }) as typeof fetch;
    await expect(publicFetch(request, "https://media.openuniversity.si/m/abc.png", "GET")).resolves.toBe(response);
    expect(calls).toBe(3);
  });
  it("stops after five pre-response failures", async () => {
    let calls = 0;
    const request = (() => { calls += 1; return Promise.reject(new TypeError("fetch failed")); }) as typeof fetch;
    await expect(publicFetch(request, "https://media.openuniversity.si/m/abc.png", "GET")).rejects.toThrow(/GET failed before a response/);
    expect(calls).toBe(5);
  });
});

describe("public inventory verification", () => {
  function registered(object: MediaObject): ContentReference {
    return { ...ref(object.sha256, `covers/owner/poster_9x16/${object.sha256}.png`), previous: object.sha256 };
  }
  it("verifies the cached GET and does not consult HEAD", async () => {
    // HEAD on media.openuniversity.si is uncached (DYNAMIC). A disagreeing HEAD must not fail a GET that is the registered object.
    const image = await png("red");
    const methods: string[] = [];
    const request = ((_url: string | URL | Request, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      methods.push(method);
      const response = method === "HEAD"
        ? new Response(null, { status: 503, headers: { "content-type": "text/html", "content-length": "0" } })
        : new Response(new Uint8Array(image.bytes), { status: 200, headers: { "content-type": "image/png", "content-length": String(image.bytes.length) } });
      return Promise.resolve(response);
    }) as typeof fetch;
    const report = await verifyInventory({ refs: [registered(image.object)], objects: [image.object] }, request);
    expect(methods).toEqual(["GET"]);
    expect(report).toMatchObject({ verified: 1, percent: 100, distinct: 1 });
  });
  it("reports the GET status, content-type and body length when they are not the registry object", async () => {
    const image = await png("blue");
    const reference = registered(image.object);
    const respond = (status: number, type: string, body: Buffer) => ((() => Promise.resolve(new Response(new Uint8Array(body), { status, headers: { "content-type": type, "content-length": String(body.length) } }))) as typeof fetch);
    await expect(verifyInventory({ refs: [reference], objects: [image.object] }, respond(503, "text/html", Buffer.from("nope")))).rejects.toThrow(/status=503 content-type=text\/html/);
    await expect(verifyInventory({ refs: [reference], objects: [image.object] }, respond(200, "text/plain", image.bytes))).rejects.toThrow(/status=200 content-type=text\/plain/);
    await expect(verifyInventory({ refs: [reference], objects: [{ ...image.object, bytes: image.object.bytes + 9 }] }, respond(200, "image/png", image.bytes))).rejects.toThrow(new RegExp(`bytes=${String(image.bytes.length)}`));
    await expect(verifyInventory({ refs: [reference], objects: [image.object] }, respond(200, "image/png", Buffer.from("x".repeat(image.bytes.length))))).rejects.toThrow(/checksum mismatch/);
  });
});

describe("public existence ignores an uncached HEAD", () => {
  function serve(bytes: Buffer, present: string, run: (request: typeof fetch, seen: { head: number; range: number; full: number }) => Promise<void>): Promise<void> {
    const seen = { head: 0, range: 0, full: 0 };
    const server = createServer((req, res) => {
      if (req.method === "HEAD") {
        seen.head += 1;
        res.writeHead(200, { "content-type": "text/html", "content-length": "0" });
        res.end();
        return;
      }
      if (req.url !== `/${present}`) {
        res.writeHead(404).end();
        return;
      }
      if (req.headers.range === "bytes=0-0") {
        seen.range += 1;
        res.writeHead(206, { "content-type": "image/png", "content-range": `bytes 0-0/${String(bytes.length)}`, "content-length": "1" });
        res.end(bytes.subarray(0, 1));
        return;
      }
      seen.full += 1;
      res.writeHead(200, { "content-type": "image/png", "content-length": String(bytes.length) });
      res.end(bytes);
    });
    return new Promise((resolve, reject) => {
      server.listen(0, "127.0.0.1", () => {
        const address = server.address() as AddressInfo;
        const request = ((input: string | URL | Request, init?: RequestInit) => {
          const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
          const next = new URL(raw);
          next.protocol = "http:";
          next.host = `127.0.0.1:${String(address.port)}`;
          return fetch(next, init);
        }) as typeof fetch;
        run(request, seen).then(() => {
          server.close(() => { resolve(); });
        }, (error: unknown) => {
          server.close(() => { reject(error instanceof Error ? error : new Error("fake server")); });
        });
      });
    });
  }
  it("reads size, audit and apply existence from a one-byte range", async () => {
    const image = await png("green");
    const key = `m/${image.object.sha256}.png`;
    const legacy = `covers/owner/poster_9x16/${image.object.sha256}.png`;
    await serve(image.bytes, key, async (request, seen) => {
      const store = publicContentStore(request);
      expect(await store.head(key)).toEqual({ size: image.bytes.length });
      const reference = ref(image.object.sha256, legacy);
      const planned = await planFromReferences([{ ...reference, pathname: key, url: `https://media.openuniversity.si/${key}` }], store);
      expect(planned.objects.map((object) => object.bytes)).toEqual([image.bytes.length]);
      const audit = await auditContentSources({ refs: [reference], objects: [image.object] }, store);
      expect(audit.missing).toMatchObject([{ pathname: legacy, contentKey: key, contentPresent: true }]);
      const present = { ...reference, pathname: key, previous: image.object.sha256 };
      expect(await copyContent({ version: 1, references: [present], objects: [image.object], sourceSha256: "plan" }, store)).toEqual({ copied: 0, verified: 1 });
      expect(seen).toMatchObject({ head: 0 });
      expect(seen.range).toBeGreaterThan(0);
      expect(seen.full).toBe(1);
    });
  });
  it("rejects a range whose total length is missing", async () => {
    const request = (() => Promise.resolve(new Response(new Uint8Array([1]), { status: 206, headers: { "content-length": "1", "content-type": "image/png" } }))) as typeof fetch;
    await expect(publicContentStore(request).head("m/abc.png")).rejects.toThrow(/no object length pathname=m\/abc.png/);
  });
});

describe("content sample and batches", () => {
  const course = hash("course");
  const lesson = hash("lesson");
  const hero = hash("hero");
  const early = hash("early");
  const references = [
    ref(early, `covers/owner/still_16x9/${early}.png`),
    ref(hero, `covers/owner/hero_desktop_16x9/${hero}.png`),
    ref(lesson, `covers/lesson/cover_16x9/${lesson}.png`),
    ref(course, `covers/owner/poster_9x16/${course}.png`),
    ref(course, `covers/owner/poster_9x16/${course}.png`),
  ];

  it("keeps a stable sha256 sample with one course poster, lesson cover and hero", () => {
    const sample = selectContentSample(references, 3);
    expect(sample.map((item) => item.sha256)).toEqual([hero, lesson, course, course]);
    expect(selectContentSample([...references].reverse(), 3).map((item) => item.sha256).sort()).toEqual([course, course, hero, lesson].sort());
    expect(selectContentSample(references, 4).map((item) => item.sha256)).toEqual([early, hero, lesson, course, course]);
  });

  it("allows an already migrated row outside the sample and rejects a pointer to different bytes", () => {
    const outside = ref(early, `covers/owner/still_16x9/${early}.png`);
    const selected = selectContentSample(references, 3);
    expect(() => { assertSampleScope(references, selected); }).not.toThrow();
    expect(() => { assertSampleScope([{ ...outside, previous: outside.sha256 }, ...selected], selected); }).not.toThrow();
    expect(() => { assertSampleScope([{ ...outside, previous: course }, ...selected], selected); }).toThrow(/outside the sample/);
  });

  it("rejects a sample that cannot hold every required kind", () => {
    expect(() => selectContentSample(references, 2)).toThrow(/at least 3/);
    expect(() => selectContentSample(references.filter((item) => !item.pathname.includes("hero_")), 3)).toThrow(/hero/);
    expect(() => selectContentSample(references, 1.5)).toThrow(StorageError);
  });

  it("slices batches in sha256 order without mutating the plan", () => {
    const objects = [{ sha256: "b" }, { sha256: "a" }, { sha256: "c" }];
    expect(contentBatches(objects, 2)).toEqual([[{ sha256: "a" }, { sha256: "b" }], [{ sha256: "c" }]]);
    expect(objects.map((item) => item.sha256)).toEqual(["b", "a", "c"]);
    expect(() => contentBatches(objects, 0)).toThrow(StorageError);
  });

  it("stops a failing batch before later batches and does not record it", async () => {
    const objects = [object("aa"), object("bb"), object("cc")].sort((a, b) => a.sha256.localeCompare(b.sha256));
    const seen: string[] = [];
    const backfills: string[][] = [];
    const persisted: string[][] = [];
    const reports: { index: number; failed: number }[] = [];
    await expect(applyContentBatches(plan(objects), throwingStore(seen), {
      batchSize: 1,
      backfill: (hashes) => { backfills.push([...hashes]); return Promise.resolve(hashes.length); },
      onBatch: (report) => { reports.push({ index: report.index, failed: report.failed }); },
      persist: (done) => { persisted.push([...done]); return Promise.resolve(); },
    })).rejects.toThrow("copy failed");
    expect(seen).toEqual([objects[0]?.sha256]);
    expect(backfills).toEqual([]);
    expect(persisted).toEqual([]);
    expect(reports).toEqual([{ index: 1, failed: 1 }]);
  });

  it("resumes from completed hashes and skips objects already stored", async () => {
    const first = await png("red");
    const second = await png("blue");
    const files = new Map<string, Buffer>([[source(first.object), first.bytes], [source(second.object), second.bytes]]);
    const store = memoryStore(files);
    const planned = plan([first.object, second.object], [ref(first.object.sha256, source(first.object)), ref(second.object.sha256, source(second.object))]);
    const backfills: string[][] = [];
    const persisted: string[][] = [];
    const firstRun = await applyContentBatches(planned, store, {
      batchSize: 1,
      backfill: (hashes) => { backfills.push([...hashes]); return Promise.resolve(1); },
      onBatch: () => {},
      persist: (done) => { persisted.push([...done]); return Promise.resolve(); },
    });
    const ordered = [first.object.sha256, second.object.sha256].sort((a, b) => a.localeCompare(b));
    expect(firstRun).toMatchObject({ copied: 2, skipped: 0, verified: 2, updated: 2 });
    expect(files.has(`m/${first.object.sha256}.png`)).toBe(true);
    expect(persisted[0]).toEqual([ordered[0]]);
    const secondRun = await applyContentBatches(planned, store, {
      batchSize: 1,
      backfill: (hashes) => { backfills.push([...hashes]); return Promise.resolve(0); },
      onBatch: () => {},
      persist: (done) => { persisted.push([...done]); return Promise.resolve(); },
    });
    expect(secondRun).toMatchObject({ copied: 0, skipped: 2, verified: 2, updated: 0 });
    const resumed = await applyContentBatches(planned, store, {
      batchSize: 1, completed: [ordered[0] ?? ""],
      backfill: (hashes) => { backfills.push([...hashes]); return Promise.resolve(0); },
      onBatch: () => {},
      persist: (done) => { persisted.push([...done]); return Promise.resolve(); },
    });
    expect(resumed.copied).toBe(0);
    expect(resumed.skipped).toBe(2);
    expect(backfills[0]).toEqual([ordered[0]]);
    expect(backfills.at(-1)).toEqual([ordered[1]]);
  });

  it("leaves a completed batch committed when the next batch fails", async () => {
    const anchor = hash("anchor");
    let made = await png("#112233");
    for (let n = 0; made.object.sha256.localeCompare(anchor) > 0 && n < 40; n += 1) made = await png(`#${n.toString(16).padStart(6, "0")}`);
    expect(made.object.sha256.localeCompare(anchor)).toBeLessThan(0);
    const later = object("anchor");
    const files = new Map<string, Buffer>([[source(made.object), made.bytes]]);
    const persisted: string[][] = [];
    const backfills: string[][] = [];
    await expect(applyContentBatches(plan([made.object, later]), memoryStore(files), {
      batchSize: 1,
      backfill: (hashes) => { backfills.push([...hashes]); return Promise.resolve(1); },
      onBatch: () => {},
      persist: (done) => { persisted.push([...done]); return Promise.resolve(); },
    })).rejects.toThrow("missing source");
    expect(backfills).toEqual([[made.object.sha256]]);
    expect(persisted).toEqual([[made.object.sha256]]);
    expect(files.has(`m/${later.sha256}.png`)).toBe(false);
  });
});

function object(label: string): MediaObject {
  const sha256 = hash(label);
  return { sha256, ext: "png", contentType: "image/png", bytes: 1, width: 2, height: 2 };
}
function plan(objects: MediaObject[], references: ContentReference[] = objects.map((item) => ref(item.sha256, source(item)))): ContentPlan {
  return { version: 1, references, objects, sourceSha256: "plan" };
}
function source(object: MediaObject) { return `covers/owner/poster_9x16/${object.sha256}.png`; }
function throwingStore(seen: string[]): MediaObjectStore {
  return {
    publicUrl: (pathname) => pathname,
    head: () => Promise.resolve(null), get: () => Promise.resolve(null), put: () => Promise.resolve("created"), delete: () => Promise.resolve(),
    copy: (_source, target) => { seen.push(target.split("/")[1]?.split(".")[0] ?? ""); return Promise.reject(new Error("copy failed")); },
  };
}
async function png(color: string) {
  const bytes = await sharp({ create: { width: 2, height: 2, channels: 3, background: color } }).png().toBuffer();
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const object: MediaObject = { sha256, ext: "png", contentType: "image/png", bytes: bytes.length, width: 2, height: 2 };
  return { bytes, object };
}
function memoryStore(files: Map<string, Buffer>): MediaObjectStore {
  return {
    publicUrl: (pathname) => pathname,
    head: (pathname) => { const bytes = files.get(pathname); return Promise.resolve(bytes ? { size: bytes.length } : null); },
    get: (pathname) => Promise.resolve(files.get(pathname) ?? null),
    put: (pathname, bytes) => { if (files.has(pathname)) return Promise.resolve("exists" as const); files.set(pathname, Buffer.from(bytes)); return Promise.resolve("created" as const); },
    copy: (sourcePath, target) => {
      const bytes = files.get(sourcePath);
      if (!bytes) return Promise.reject(new Error("missing source"));
      if (files.has(target)) return Promise.resolve("exists" as const);
      files.set(target, bytes);
      return Promise.resolve("created" as const);
    },
    delete: (pathname) => { files.delete(pathname); return Promise.resolve(); },
  };
}


describe("migration source integrity", () => {
  async function fixture() {
    const bytes = await sharp({ create: { width: 2, height: 2, channels: 3, background: "red" } }).png().toBuffer();
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const reference = { ...ref(sha256, "covers/owner/poster_9x16/legacy.png"), previous: sha256 };
    const object: MediaObject = { sha256, ext: "png", bytes: bytes.length, width: 2, height: 2, contentType: "image/png" };
    const key = `m/${sha256}.png`;
    const store = publicContentStore((url, options) => {
      if ((typeof url === "string" ? url : url instanceof URL ? url.href : url.url).endsWith(key)) return Promise.resolve(new Response(options?.method === "HEAD" ? null : bytes, { headers: { "content-length": String(bytes.length) } }));
      return Promise.resolve(new Response(null, { status: 404 }));
    });
    return { bytes, reference, object, key, store };
  }
  it("plans and re-applies registered content with no legacy source or storage writes, including after rollback", async () => {
    const { reference, object, store } = await fixture();
    for (const previous of [reference.sha256, null]) {
      const plan = await planFromReferences([{ ...reference, previous }], store, [object]);
      expect(plan.objects).toEqual([object]);
      expect(await copyContent(plan, store)).toEqual({ copied: 0, verified: 1 });
    }
  });
  it("fails closed for missing registered content and corrupt bytes", async () => {
    const { reference, object, store } = await fixture();
    await expect(planFromReferences([reference], { ...store, get: () => Promise.resolve(null) }, [object])).rejects.toThrow(/Missing migrated content: catalog_media.*pathname=m\//);
    await expect(planFromReferences([reference], { ...store, get: () => Promise.resolve(Buffer.from("corrupt")) }, [object])).rejects.toThrow(/checksum/);
    await expect(planFromReferences([reference], store, [{ ...object, bytes: object.bytes + 1 }])).rejects.toThrow(/metadata mismatch/);
    await expect(planFromReferences([reference], store)).rejects.toThrow(/Missing legacy media source: catalog_media.*pathname=covers\//);
  });
  it("reports dangling legacy identities and the presence of registered content", async () => {
    const { reference, object, store } = await fixture();
    const report = await auditContentSources({ refs: [reference], objects: [object] }, store);
    expect(report.missingLegacyPaths).toBe(1);
    expect(report.missing[0]).toMatchObject({ pathname: reference.pathname, contentPresent: true, references: [{ id: reference.id }] });
  });
  it("public storage rejects writes, HTTP failures, redirects and unsafe paths", async () => {
    const store = publicContentStore((_url, options) => {
      expect(options?.redirect).toBe("error");
      return Promise.resolve(new Response(null, { status: 403 }));
    });
    await expect(store.head("m/test.png")).rejects.toThrow(/status=403.*pathname=m/);
    await expect(store.get("m/test.png")).rejects.toThrow(/status=403/);
    await expect(store.put("m/test.png", Buffer.from("x"))).rejects.toThrow(/cannot create/);
    await expect(store.delete("m/test.png")).rejects.toThrow(/cannot delete/);
    await expect(store.head("../test.png")).rejects.toThrow(/Invalid public media key/);
  });
});
