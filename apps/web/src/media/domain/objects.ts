import { z } from "zod";
import { type PublicMediaPolicy } from "./types.ts";

export const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
export const objectSchema = z.object({
  sha256: sha256Schema, ext: z.enum(["jpg", "png", "webp", "avif"]), contentType: z.string(),
  bytes: z.number().int().positive(), width: z.number().int().positive(), height: z.number().int().positive(),
});
export type MediaObject = z.infer<typeof objectSchema>;
export type ObjectExtension = MediaObject["ext"];
export interface ObjectIdentity { readonly sha256: string; readonly ext: ObjectExtension }
export const objectKey = (sha256: string, ext: string) => `m/${sha256Schema.parse(sha256)}.${objectSchema.shape.ext.parse(ext)}`;
/** Public URL of one immutable object. The host comes from the caller, never from the environment. */
export function objectUrl(object: ObjectIdentity, policy: PublicMediaPolicy): string {
  if (!policy.acceptedHosts.includes(policy.host)) throw new Error("Media host is not an accepted public host.");
  return `https://${policy.host}/${objectKey(object.sha256, object.ext)}`;
}
export function objectDescriptor(object: MediaObject, policy: PublicMediaPolicy) {
  return { url: objectUrl(object, policy), pathname: objectKey(object.sha256, object.ext), width: object.width, height: object.height, sha256: object.sha256, mediaSha256: object.sha256 };
}
