import { createHash } from "node:crypto";

/** JSON with object keys sorted at every level: equal values give equal strings regardless of key order. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item === undefined ? null : item)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return value === undefined ? "null" : JSON.stringify(value);
}

export const sha256Hex = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");

/** `admin_idempotency.request_sha256`: the canonical query and body of a request. */
export function requestHash(query: unknown, body: unknown): string {
  return sha256Hex(canonicalJson({ body: body ?? null, query: query ?? {} }));
}
