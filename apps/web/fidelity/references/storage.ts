import { createHash } from "node:crypto";
import { mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { storedObjectKey } from "../../src/media/server/object-url.ts";
import { createS3Bucket, hasR2Credentials, r2Config, type R2Access, type S3Config } from "../../scripts/lib/r2.ts";

/** Tiny storage seam for reference images: private R2 bucket in operation, filesystem in tests. */
export interface ReferenceStorage {
  put(pathname: string, body: Buffer): Promise<{ readonly url: string }>;
  get(url: string): Promise<Buffer | null>;
  head(pathname: string): Promise<{ readonly url: string; readonly size: number } | null>;
  /** Used only by `fidelity:sync` pruning of superseded sets. */
  delete(urls: readonly string[]): Promise<void>;
}

export const sha256 = (bytes: Buffer): string => createHash("sha256").update(bytes).digest("hex");

export const R2_FIDELITY_BUCKET_DEFAULT = "the-tower-fidelity";

/**
 * Private R2 bucket `the-tower-fidelity` (S3 API). Only `fidelity:sync` calls `put`; the harness only reads.
 * Recorded URLs are this bucket's object URLs (`https://<account>.r2.cloudflarestorage.com/<bucket>/<key>`).
 */
export function createR2Storage(config: S3Config): ReferenceStorage {
  const bucket = createS3Bucket(config);
  return {
    async put(pathname, body) {
      await bucket.put(pathname, body, { contentType: "image/png", overwrite: true });
      return { url: bucket.objectUrl(pathname) };
    },
    async get(url) { return bucket.get(storedObjectKey(url, (value) => bucket.keyFromUrl(value))); },
    async head(pathname) {
      const result = await bucket.head(pathname);
      return result ? { url: bucket.objectUrl(pathname), size: result.size } : null;
    },
    async delete(urls) {
      for (const url of urls) await bucket.delete(storedObjectKey(url, (value) => bucket.keyFromUrl(value)));
    },
  };
}

type Env = Readonly<Record<string, string | undefined>>;
/** The private R2 bucket (`R2_FIDELITY_BUCKET`, default the-tower-fidelity). Returns null when no credential is configured. */
export function referenceStorageFromEnv(env: Env, access: R2Access): ReferenceStorage | null {
  return hasR2Credentials(env, access) ? createR2Storage(r2Config(env, env.R2_FIDELITY_BUCKET ?? R2_FIDELITY_BUCKET_DEFAULT, access)) : null;
}

/** Same contract on a local directory, addressed by file:// URLs. */
export function createFileSystemStorage(directory: string): ReferenceStorage {
  const locate = (pathname: string) => {
    const file = path.resolve(directory, pathname);
    if (!file.startsWith(`${path.resolve(directory)}${path.sep}`)) throw new Error("Storage pathname escapes the storage directory.");
    return file;
  };
  return {
    async put(pathname, body) {
      const file = locate(pathname);
      await mkdir(path.dirname(file), { recursive: true });
      await writeFile(file, body);
      return { url: pathToFileURL(file).href };
    },
    async get(url) {
      try {
        return await readFile(fileURLToPath(url));
      } catch {
        return null;
      }
    },
    async head(pathname) {
      const file = locate(pathname);
      try {
        return { url: pathToFileURL(file).href, size: (await stat(file)).size };
      } catch {
        return null;
      }
    },
    async delete(urls) {
      await Promise.all(urls.map((url) => rm(fileURLToPath(url), { force: true })));
    },
  };
}
