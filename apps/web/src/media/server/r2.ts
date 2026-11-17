import { AwsClient } from "aws4fetch";
import { DEFAULT_R2_BUDGET, withPhysicalSlot } from "./r2-slot.ts";
import { StorageError } from "./storage-error.ts";

export { StorageError } from "./storage-error.ts";

/**
 * Minimal S3-compatible client for Cloudflare R2 (and a local S3 server in tests).
 * One request at a time, with its own timeout and retry. Bulk jobs use scripts/lib/r2-bulk.ts.
 * Credentials come only from env and are never echoed: every error carries method + status only.
 */
type Env = Readonly<Record<string, string | undefined>>;
export type R2Access = "rw" | "ro";
export interface S3Config { readonly endpoint: string; readonly bucket: string; readonly accessKeyId: string; readonly secretAccessKey: string; readonly region: string }

const localEndpoint = /^http:\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+$/;

/** True when the env holds R2 credentials for `access` (RO falls back to the RW pair on the box). */
export function hasR2Credentials(env: Env, access: R2Access): boolean {
  const pair = access === "rw" ? ["R2_ACCESS_KEY_ID_RW", "R2_SECRET_ACCESS_KEY_RW"] : ["R2_ACCESS_KEY_ID_RO", "R2_SECRET_ACCESS_KEY_RO"];
  return Boolean((env[pair[0] ?? ""] && env[pair[1] ?? ""]) || (access === "ro" && env.R2_ACCESS_KEY_ID_RW && env.R2_SECRET_ACCESS_KEY_RW)) && Boolean(env.R2_ACCOUNT_ID || env.R2_ENDPOINT);
}

export function r2Config(env: Env, bucket: string, access: R2Access): S3Config {
  const ro = access === "ro" && env.R2_ACCESS_KEY_ID_RO && env.R2_SECRET_ACCESS_KEY_RO;
  const accessKeyId = ro ? env.R2_ACCESS_KEY_ID_RO : env.R2_ACCESS_KEY_ID_RW;
  const secretAccessKey = ro ? env.R2_SECRET_ACCESS_KEY_RO : env.R2_SECRET_ACCESS_KEY_RW;
  if (!accessKeyId || !secretAccessKey) throw new StorageError(`R2 ${access === "rw" ? "R2_ACCESS_KEY_ID_RW/R2_SECRET_ACCESS_KEY_RW" : "R2_ACCESS_KEY_ID_RO/R2_SECRET_ACCESS_KEY_RO"} are required.`);
  let endpoint: string;
  if (env.R2_ENDPOINT) {
    // Only a local S3 test server may override the Cloudflare endpoint.
    if (!localEndpoint.test(env.R2_ENDPOINT)) throw new StorageError("R2_ENDPOINT may only point at a local test server (http://127.0.0.1:<port>).");
    endpoint = env.R2_ENDPOINT;
  } else {
    if (!/^[a-f0-9]{32}$/.test(env.R2_ACCOUNT_ID ?? "")) throw new StorageError("R2_ACCOUNT_ID must be the 32-hex Cloudflare account id.");
    endpoint = `https://${env.R2_ACCOUNT_ID ?? ""}.r2.cloudflarestorage.com`;
  }
  if (!/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(bucket)) throw new StorageError("Invalid R2 bucket name.");
  return { endpoint, bucket, accessKeyId, secretAccessKey, region: env.R2_REGION ?? "auto" };
}

export interface S3Bucket {
  readonly bucket: string;
  objectUrl(key: string): string;
  /** Maps an object URL of this bucket back to its key. */
  keyFromUrl(url: string): string;
  head(key: string): Promise<{ readonly size: number; readonly etag: string } | null>;
  get(key: string): Promise<Buffer | null>;
  /** `overwrite: false` sends `If-None-Match: *`; an existing object returns "exists" and is never replaced. */
  put(key: string, body: Uint8Array, options: { readonly contentType: string; readonly cacheControl?: string; readonly overwrite?: boolean }): Promise<"created" | "exists">;
  copy(source: string, target: string, contentType: string, cacheControl: string): Promise<"created" | "exists">;
  delete(key: string): Promise<void>;
}

function checkKey(key: string) {
  if (!key || key.startsWith("/") || key.split("/").some((part) => part === "" || part === "." || part === "..")) throw new StorageError("Invalid storage key.");
  return key;
}

/**
 * Fetch threw before any HTTP response. Conditional PUT/copy (`If-None-Match` / `cf-copy-destination-if-none-match`)
 * and DELETE (404 is success) are safe to send again. A hung TLS handshake to R2 is the common case: measured 19/10/2026,
 * about 1% of new connections wait until the abort signal, so a short timeout and several new attempts beat three 60s waits.
 */
export interface StorageClock {
  now(): number;
  wait(ms: number): Promise<void>;
  /** Bounded extra delay. Zero is a valid clock for tests. */
  jitter(attempt: number): number;
}

const defaultClock: StorageClock = {
  now: () => Date.now(),
  wait: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  jitter: (attempt) => Math.min(25, attempt),
};

export function createS3Bucket(config: S3Config, clock: StorageClock = defaultClock): S3Bucket {
  const client = new AwsClient({ accessKeyId: config.accessKeyId, secretAccessKey: config.secretAccessKey, service: "s3", region: config.region });
  const budget = DEFAULT_R2_BUDGET;
  const objectUrl = (key: string) => `${config.endpoint}/${config.bucket}/${checkKey(key).split("/").map(encodeURIComponent).join("/")}`;
  async function send(method: string, key: string, init: { body?: Uint8Array; headers?: Record<string, string> } = {}) {
    const started = clock.now();
    for (let attempt = 1; ; attempt++) {
      if (clock.now() - started > budget.totalTimeoutMs) throw new StorageError(`Storage ${method} exceeded its deadline.`);
      try {
        return await withPhysicalSlot(() => client.fetch(objectUrl(key), { method, ...init, redirect: "error", signal: AbortSignal.timeout(budget.attemptTimeoutMs) } as RequestInit));
      } catch (error) {
        if (error instanceof StorageError) throw error;
        if (attempt < budget.attempts && clock.now() - started <= budget.totalTimeoutMs) {
          await clock.wait(50 * attempt + clock.jitter(attempt));
          continue;
        }
        throw new StorageError(`Storage ${method} failed before a response; details redacted.`);
      }
    }
  }
  const fail = (method: string, status: number) => new StorageError(`Storage ${method} returned HTTP ${String(status)}.`);
  return {
    bucket: config.bucket,
    objectUrl,
    keyFromUrl(value) {
      const url = new URL(value);
      const path = url.pathname.split("/").map(decodeURIComponent).join("/");
      const prefix = `/${config.bucket}/`;
      if (`${url.protocol}//${url.host}` === new URL(config.endpoint).origin && path.startsWith(prefix)) return checkKey(path.slice(prefix.length));
      if (url.protocol === "https:" && url.hostname.endsWith(".r2.cloudflarestorage.com") && path.startsWith(prefix)) return checkKey(path.slice(prefix.length));
      throw new StorageError("URL does not belong to this bucket.");
    },
    async head(key) {
      const response = await send("HEAD", key);
      if (response.status === 404) return null;
      if (!response.ok) throw fail("HEAD", response.status);
      return { size: Number(response.headers.get("content-length") ?? -1), etag: (response.headers.get("etag") ?? "").replaceAll('"', "") };
    },
    async get(key) {
      const response = await send("GET", key);
      if (response.status === 404) return null;
      if (!response.ok) throw fail("GET", response.status);
      return Buffer.from(await response.arrayBuffer());
    },
    async put(key, body, options) {
      // Explicit length: Next's patched fetch can stream a Uint8Array body without Content-Length, and R2 answers 411.
      const headers: Record<string, string> = { "Content-Type": options.contentType, "Content-Length": String(body.byteLength) };
      if (options.cacheControl) headers["Cache-Control"] = options.cacheControl;
      if (!options.overwrite) headers["If-None-Match"] = "*";
      const response = await send("PUT", key, { body, headers });
      if (response.status === 412 && !options.overwrite) return "exists";
      if (!response.ok) throw fail("PUT", response.status);
      return "created";
    },
    async copy(source, target, contentType, cacheControl) {
      const response = await send("PUT", target, { headers: {
        "x-amz-copy-source": `/${config.bucket}/${checkKey(source).split("/").map(encodeURIComponent).join("/")}`,
        "cf-copy-destination-if-none-match": "*", "x-amz-metadata-directive": "REPLACE",
        "Content-Type": contentType, "Cache-Control": cacheControl,
      } });
      if (response.status === 412) return "exists";
      const xml = await response.text();
      if (!response.ok || !xml.includes("CopyObjectResult") || xml.includes("<Error>")) throw fail("COPY", response.status);
      return "created";
    },
    async delete(key) {
      const response = await send("DELETE", key);
      if (!response.ok && response.status !== 404) throw fail("DELETE", response.status);
    },
  };
}
