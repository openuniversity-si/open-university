/** Immutable, content-addressed object store for public covers. Keys are the asset `pathname`. */
export interface MediaObjectStore {
  publicUrl(pathname: string): string;
  head(pathname: string): Promise<{ readonly size: number; readonly etag?: string } | null>;
  get(pathname: string): Promise<Buffer | null>;
  /** Never overwrites: an existing key returns "exists". */
  put(pathname: string, bytes: Uint8Array): Promise<"created" | "exists">;
  /** Server-side immutable copy, when the store supports it. */
  copy?(source: string, target: string): Promise<"created" | "exists">;
  /** Idempotent: an absent key is not an error. */
  delete(pathname: string): Promise<void>;
}

/** Key of a stored object URL. The bucket reader comes from the adapter. */
export function objectKeyFromUrl(value: string, bucketKey: (url: URL) => string | undefined): string | undefined {
  return bucketKey(new URL(value));
}
