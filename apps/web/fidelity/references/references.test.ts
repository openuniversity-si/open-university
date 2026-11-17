import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { cacheReferenceImage, materializeActiveSet } from "./active.ts";
import { safeErrorMessage } from "./connect.ts";
import { createFigmaClient, planExportRoots, planImages, pngSize, rootGeometry, slug } from "./figma.ts";
import { fakePage, solidPng } from "./fixtures.test-helpers.ts";
import type { ReferenceImage, SqlClient } from "./repository.ts";
import { createFileSystemStorage, sha256 } from "./storage.ts";

describe("Figma export plan", () => {
  it("exports production screens, their scroll content and state canvases, never external mocks or labels", () => {
    const roots = planExportRoots([fakePage()]);
    expect(roots.map((root) => [root.nodeId, root.kind, root.baseKey, root.frameWidth])).toEqual([
      ["29:399", "screen", "home-mobile-390--29-399", 39],
      ["29:400", "scroll", "home-mobile-390-scroll--29-400", 39],
      ["293:14610", "state", "state-a--293-14610", 160],
      ["293:14640", "state", "state-b--293-14640", 160],
    ]);
    const images = planImages(roots);
    expect(images).toHaveLength(8);
    expect(images.map((image) => image.screenKey)).toContain("home-mobile-390--29-399@2x");
    expect(images.find((image) => image.screenKey === "state-b--293-14640@1x")?.viewport).toBe("160@1x");
  });

  it("refuses suggestion, backup and archived pages", () => {
    for (const name of ["Suggestions — Header Fade", "Backup TopNav", "⛔ Archived — States"]) {
      expect(() => planExportRoots([{ ...fakePage(), name }])).toThrow(/not a production page/);
    }
  });

  it("records visible geometry relative to each root", () => {
    const page = fakePage();
    const screen = page.children?.[0];
    if (!screen) throw new Error("fixture");
    const nodes = rootGeometry(screen);
    expect(nodes.find((node) => node.nodeId === "I29:525;21:37")).toEqual({ rootNodeId: "29:399", nodeId: "I29:525;21:37", name: "Left", x: 2, y: 1, width: 2, height: 3 });
    expect(nodes.some((node) => node.nodeId === "29:524")).toBe(false);
    expect(nodes[0]).toMatchObject({ nodeId: "29:399", x: 0, y: 0 });
  });

  it("builds path-safe keys", () => {
    expect(slug("Course Detail — Mobile 390 (Genesis · prototype target)")).toBe("course-detail-mobile-390-genesis-prototype-target");
    expect(slug("Ação Ü")).toBe("acao-u");
  });

  it("reads PNG dimensions and rejects other bytes", async () => {
    expect(pngSize(await solidPng(7, 3, 1))).toEqual({ width: 7, height: 3 });
    expect(() => pngSize(Buffer.from("<svg/>"))).toThrow(/Not a PNG/);
  });
});

describe("Figma read-only client", () => {
  it("sends only GETs, honours Retry-After, and never sends the token to the render CDN", async () => {
    const calls: { url: string; method: string | undefined; token: string | null }[] = [];
    const waits: number[] = [];
    let first = true;
    const client = createFigmaClient("secret-pat", (url, init) => {
      calls.push({ url, method: init?.method, token: new Headers(init?.headers).get("x-figma-token") });
      if (url.startsWith("https://api.figma.com/") && first) {
        first = false;
        return Promise.resolve(new Response("", { status: 429, headers: { "retry-after": "3" } }));
      }
      if (url.startsWith("https://api.figma.com/")) return Promise.resolve(Response.json({ err: null, images: { "1:2": "https://cdn.example/render.png" } }));
      return Promise.resolve(new Response(new Uint8Array([1, 2, 3])));
    }, (ms) => { waits.push(ms); return Promise.resolve(); });
    const urls = await client.renderUrls("file", ["1:2"], 2, "123");
    expect(await client.download(urls.get("1:2") ?? "")).toEqual(Buffer.from([1, 2, 3]));
    expect(waits).toEqual([3000]);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
    expect(calls[1]?.url).toContain("version=123");
    expect(calls[1]?.url).toContain("use_absolute_bounds=true");
    expect(calls.filter((call) => call.url.startsWith("https://api.figma.com/v1/images/file")).every((call) => call.token === "secret-pat")).toBe(true);
    expect(calls.at(-1)?.token).toBeNull();
  });

  it("reports HTTP failures without the token", async () => {
    const client = createFigmaClient("secret-pat", () => Promise.resolve(new Response("", { status: 403 })));
    await expect(client.file("file")).rejects.toThrow(/^Figma GET \/v1\/files\/file failed with HTTP 403\.$/);
  });
});

describe("reference cache and storage", () => {
  async function stored(red: number) {
    const directory = await mkdtemp(path.join(tmpdir(), "tower-fidelity-"));
    const storage = createFileSystemStorage(path.join(directory, "store"));
    const bytes = await solidPng(4, 2, red);
    const { url } = await storage.put("fidelity/1/home--1-2@1x.png", bytes);
    const image: ReferenceImage = { nodeId: "1:2", screenKey: "home--1-2@1x", viewport: "390@1x", blobUrl: url, sha256: sha256(bytes), width: 4, height: 2 };
    return { directory, storage, bytes, image, cache: path.join(directory, "cache") };
  }

  it("downloads once, then serves verified bytes from the sha256 cache", async () => {
    const { storage, bytes, image, cache } = await stored(9);
    expect(await storage.head("fidelity/1/home--1-2@1x.png")).toMatchObject({ size: bytes.length });
    expect(await storage.head("fidelity/1/absent.png")).toBeNull();
    const first = await cacheReferenceImage(image, storage, cache);
    expect(first).toEqual({ file: path.join(cache, `${image.sha256}.png`), downloaded: true });
    expect(await readFile(first.file)).toEqual(bytes);
    expect((await cacheReferenceImage(image, storage, cache)).downloaded).toBe(false);
    await writeFile(first.file, "corrupted");
    expect((await cacheReferenceImage(image, storage, cache)).downloaded).toBe(true);
  });

  it("fails on a stored image that does not match tower_tooling", async () => {
    const { storage, image, cache } = await stored(9);
    await expect(cacheReferenceImage({ ...image, sha256: "0".repeat(64) }, storage, cache)).rejects.toThrow(/sha256/);
    await expect(cacheReferenceImage({ ...image, width: 5, sha256: image.sha256 }, storage, path.join(cache, "other"))).rejects.toThrow(/dimensions/);
    await expect(cacheReferenceImage({ ...image, blobUrl: `${image.blobUrl}.missing` }, storage, path.join(cache, "third"))).rejects.toThrow(/missing from the fidelity store/);
  });

  it("downloads identical renders once even when several screens share their bytes", async () => {
    const { storage, image, cache } = await stored(9);
    let gets = 0;
    const counting = { ...storage, get: (url: string) => { gets++; return storage.get(url); } };
    const row = (screenKey: string) => ({ node_id: "1:2", screen_key: screenKey, viewport: "390@1x", blob_url: image.blobUrl, sha256: image.sha256, width: 4, height: 2 });
    const db: SqlClient = {
      query: (text) => Promise.resolve({ rows: text.includes("fidelity_reference_set") ? [{ id: "1", figma_file_key: "file", figma_version_id: "9", created_at: "2026-10-08", is_active: true, note: null }]
        : text.includes("fidelity_reference_image") ? ["a@1x", "b@1x", "c@1x"].map(row) : [] }),
    };
    const local = await materializeActiveSet(db, counting, cache, () => undefined);
    expect(gets).toBe(1);
    expect(new Set(Object.values(local.files))).toEqual(new Set([path.join(cache, `${image.sha256}.png`)]));
    expect(Object.keys(local.files)).toEqual(["a@1x", "b@1x", "c@1x"]);
  });

  it("keeps filesystem pathnames inside the store", async () => {
    const { storage } = await stored(1);
    await expect(storage.put("../escape.png", Buffer.from("x"))).rejects.toThrow(/escapes/);
  });
});

describe("secret-safe errors", () => {
  it("redacts known secret values and any connection string", () => {
    const env = { R2_SECRET_ACCESS_KEY_RW: "r2-secret-abc", FIGMA_TOKEN: "figd_xyz" };
    expect(safeErrorMessage(new Error("bad r2-secret-abc and figd_xyz at postgresql://u:p@h/db?x=1"), env))
      .toBe("bad [R2_SECRET_ACCESS_KEY_RW] and [FIGMA_TOKEN] at [redacted connection string]");
  });
});
