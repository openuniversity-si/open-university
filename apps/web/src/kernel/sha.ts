import { createHash } from "node:crypto";

/** `catalog_releases.payload_sha256`: SHA-256 of the schema-ordered JSON (`releaseSchema.parse` output, or v1 as stored). */
export function releaseSha(payload: object): string {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}
