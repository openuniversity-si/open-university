import { AwsClient } from "aws4fetch";
import { DEFAULT_R2_BUDGET, withPhysicalSlot } from "./r2-slot.ts";
import { StorageError } from "./storage-error.ts";

export { StorageError } from "./storage-error.ts";

/**
 * Minimal S3-compatible client for Cloudflare R2 (and a local S3 server in tests), and for Amazon S3 itself
 * (`MEDIA_STORE=s3`, D-323 step 2). One request at a time, with its own timeout and retry. Bulk jobs use scripts/lib/r2-bulk.ts.
 * Credentials come only from env and are never echoed: every error carries method + status only.
 */
type Env = Readonly<Record<string, string | undefined>>;
export type R2Access = "rw" | "ro";
/** Which object store the site's media client talks to. Unset means "r2" (today's behaviour). */
export type MediaStoreMode = "r2" | "s3";
export interface S3Config {
  readonly endpoint: string; readonly bucket: string; readonly accessKeyId: string; readonly secretAccessKey: string; readonly region: string;
  /** Temporary role credentials (Lambda's AWS_SESSION_TOKEN); sent as X-Amz-Security-Token. */
  readonly sessionToken?: string;
  /** "r2" (default) uses Cloudflare's atomic copy condition; "s3" guards copy with a HEAD (S3 has no destination condition on copy). */
  readonly store?: MediaStoreMode;
  /** "path" (default): <endpoint>/<bucket>/<key>; "virtual": the bucket is in the endpoint's host, <endpoint>/<key>. */
  readonly addressing?: "path" | "virtual";
}

const localEndpoint = /^http:\/\/(?:127\.0\.0\.1|localhost|\[::1\]):\d+$/;

/** True when the env holds R2 credentials for `access` (RO falls back to the RW pair on the box). */
export function hasR2Credentials(env: Env, access: R2Access): boolean {
  const pair = access === "rw" ? ["R2_ACCESS_KEY_ID_RW", "R2_SECRET_ACCESS_KEY_RW"] : ["R2_ACCESS_KEY_ID_RO", "R2_SECRET_ACCESS_KEY_RO"];
  return Boolean((env[pair[0] ?? ""] && env[pair[1] ?? ""]) || (access === "ro" && env.R2_ACCESS_KEY_ID_RW && env.R2_SECRET_ACCESS_KEY_RW)) && Boolean(env.R2_ACCOUNT_ID || env.R2_ENDPOINT);
}

/** `MEDIA_STORE`: unset or "r2" keeps R2; "s3" selects Amazon S3; anything else is refused (no silent fallback). */
export function mediaStoreMode(env: Env): MediaStoreMode {
  const raw = (env.MEDIA_STORE ?? "").trim();
  if (raw === "" || raw === "r2") return "r2";
  if (raw === "s3") return "s3";
  throw new StorageError('MEDIA_STORE must be "r2" or "s3".');
}

/** True when the env holds S3 role credentials (Lambda: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY), the bucket and the region. */
export function hasS3Credentials(env: Env): boolean {
  return Boolean(env.AWS_ACCESS_KEY_ID && env.AWS_SECRET_ACCESS_KEY && env.MEDIA_S3_BUCKET && env.AWS_REGION);
}

/**
 * Amazon S3, virtual-hosted (AWS's default): https://<bucket>.s3.<region>.amazonaws.com/<key>, signed SigV4 for
 * service s3 in AWS_REGION. Credentials are the runtime role's (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
 * AWS_SESSION_TOKEN); RO and RW both use the role and its policy decides. No long-lived key is read.
 */
export function s3Config(env: Env): S3Config {
  const bucket = env.MEDIA_S3_BUCKET ?? "";
  const region = env.AWS_REGION ?? "";
  const accessKeyId = env.AWS_ACCESS_KEY_ID;
  const secretAccessKey = env.AWS_SECRET_ACCESS_KEY;
  if (!accessKeyId || !secretAccessKey) throw new StorageError("S3 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are required (the runtime role).");
  if (!/^[a-z]{2}(?:-[a-z]+)+-\d$/.test(region)) throw new StorageError("AWS_REGION must be an AWS region (e.g. us-east-1).");
  // No dots: a dotted name breaks TLS on the virtual-hosted wildcard certificate.
  if (!/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(bucket)) throw new StorageError("MEDIA_S3_BUCKET must be a dotless S3 bucket name.");
  const sessionToken = env.AWS_SESSION_TOKEN;
  return { endpoint: `https://${bucket}.s3.${region}.amazonaws.com`, bucket, accessKeyId, secretAccessKey, region, store: "s3", addressing: "virtual", ...(sessionToken ? { sessionToken } : {}) };
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
  const client = new AwsClient({ accessKeyId: config.accessKeyId, secretAccessKey: config.secretAccessKey, ...(config.sessionToken ? { sessionToken: config.sessionToken } : {}), service: "s3", region: config.region });
  // The physical slot and the budget apply to both stores: they bound this process's in-flight requests, whatever the host.
  const budget = DEFAULT_R2_BUDGET;
  const s3 = config.store === "s3";
  const virtual = config.addressing === "virtual";
  const encodeKey = (key: string) => checkKey(key).split("/").map(encodeURIComponent).join("/");
  const objectUrl = (key: string) => virtual ? `${config.endpoint}/${encodeKey(key)}` : `${config.endpoint}/${config.bucket}/${encodeKey(key)}`;
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
  async function head(key: string) {
    const response = await send("HEAD", key);
    if (response.status === 404) return null;
    if (!response.ok) throw fail("HEAD", response.status);
    return { size: Number(response.headers.get("content-length") ?? -1), etag: (response.headers.get("etag") ?? "").replaceAll('"', "") };
  }
  return {
    bucket: config.bucket,
    objectUrl,
    keyFromUrl(value) {
      const url = new URL(value);
      const path = url.pathname.split("/").map(decodeURIComponent).join("/");
      const prefix = `/${config.bucket}/`;
      if (virtual && `${url.protocol}//${url.host}` === new URL(config.endpoint).origin && path.length > 1) return checkKey(path.slice(1));
      if (`${url.protocol}//${url.host}` === new URL(config.endpoint).origin && path.startsWith(prefix)) return checkKey(path.slice(prefix.length));
      if (url.protocol === "https:" && url.hostname.endsWith(".r2.cloudflarestorage.com") && path.startsWith(prefix)) return checkKey(path.slice(prefix.length));
      throw new StorageError("URL does not belong to this bucket.");
    },
    head,
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
      let response = await send("PUT", key, { body, headers });
      // S3 answers 409 ConditionalRequestConflict while a concurrent write to the key is in flight; AWS says retry.
      // The retry then gets 412 (the other write landed) or 200. R2 never answers 409 here.
      if (s3 && response.status === 409 && !options.overwrite) {
        await clock.wait(50 + clock.jitter(1));
        response = await send("PUT", key, { body, headers });
      }
      if (response.status === 412 && !options.overwrite) return "exists";
      if (!response.ok) throw fail("PUT", response.status);
      return "created";
    },
    async copy(source, target, contentType, cacheControl) {
      if (s3) {
        // S3's CopyObject takes conditions on the source (x-amz-copy-source-if-*), not on the destination, so the
        // "never replace" contract is a HEAD then the copy. Race window: a write to `target` between the two requests
        // is replaced. Targets are content-addressed (m/<sha256>.<ext>), so the replacement carries the same bytes,
        // and the bucket is versioned, so the earlier version stays recoverable.
        if (await head(target)) return "exists";
        const response = await send("PUT", target, { headers: {
          "x-amz-copy-source": `/${config.bucket}/${encodeKey(source)}`, "x-amz-metadata-directive": "REPLACE",
          "Content-Type": contentType, "Cache-Control": cacheControl,
        } });
        const xml = await response.text();
        if (!response.ok || !xml.includes("CopyObjectResult") || xml.includes("<Error>")) throw fail("COPY", response.status);
        return "created";
      }
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
