import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createFsMediaStore } from "./fs-store.ts";
import { StorageError } from "./storage-error.ts";

describe("filesystem media store", () => {
  it("stores bytes once and deletes them", async () => {
    const directory = await mkdtemp(join(tmpdir(), "tower-fs-store-"));
    try {
      const store = createFsMediaStore(directory, "media.test");
      const key = "m/abc.jpg";
      expect(store.publicUrl(key)).toBe(`https://media.test/${key}`);
      expect(await store.put(key, Uint8Array.of(1, 2, 3))).toBe("created");
      expect(await store.put(key, Uint8Array.of(9))).toBe("exists");
      expect(await store.get(key)).toEqual(Buffer.from([1, 2, 3]));
      expect(await store.head(key)).toEqual({ size: 3 });
      await store.delete(key);
      await store.delete(key);
      expect(await store.get(key)).toBeNull();
      expect(await store.head(key)).toBeNull();
    } finally { await rm(directory, { recursive: true, force: true }); }
  });

  it("refuses a pathname that escapes the directory", async () => {
    const directory = await mkdtemp(join(tmpdir(), "tower-fs-store-"));
    try {
      const store = createFsMediaStore(directory, "media.test");
      await expect(store.put("../outside.jpg", Uint8Array.of(1))).rejects.toThrow(StorageError);
    } finally { await rm(directory, { recursive: true, force: true }); }
  });
});
