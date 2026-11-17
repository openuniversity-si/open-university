import { mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { MediaObjectStore } from "../ports/storage.ts";
import { StorageError } from "./storage-error.ts";

/** Bytes of a local upload. Image preparation calls this and imports only sharp. */
export function readUploadBytes(file: string): Promise<Buffer> {
  return readFile(file);
}

/** Test/offline store on a local directory; public URLs use the given host. */
export function createFsMediaStore(directory: string, host: string): MediaObjectStore {
  const locate = (pathname: string) => {
    const file = path.resolve(directory, pathname);
    if (!file.startsWith(`${path.resolve(directory)}${path.sep}`)) throw new StorageError("Storage pathname escapes the storage directory.");
    return file;
  };
  return {
    publicUrl: (pathname) => `https://${host}/${pathname}`,
    async head(pathname) { try { return { size: (await stat(locate(pathname))).size }; } catch { return null; } },
    async get(pathname) { try { return await readFile(locate(pathname)); } catch { return null; } },
    async put(pathname, bytes) {
      const file = locate(pathname);
      try { await stat(file); return "exists"; } catch { /* absent */ }
      await mkdir(path.dirname(file), { recursive: true }); await writeFile(file, bytes, { flag: "wx" }); return "created";
    },
    async delete(pathname) { await rm(locate(pathname), { force: true }); },
  };
}
