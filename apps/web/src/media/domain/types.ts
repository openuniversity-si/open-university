import { z } from "zod";
import { coverKindsByOwner } from "../../kernel/cover-kinds.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { EXTENT } from "../../kernel/extent.ts";

/**
 * The one public host of the lesson and course images (the media bucket's custom domain, `R2_MEDIA_BUCKET_DEFAULT` in storage.ts,
 * 2026-10-11; it replaced media.thetower.si, which is retired with no fallback). Never write this string anywhere else: next/image,
 * the CSP, the URL schema and the tools all read it from here (`media-host.test.ts` fails on a second copy).
 * `TOWER_MEDIA_PUBLIC_HOST` is only a dev/test override, and only when the storage adapters register that bridge.
 */
export const MEDIA_PUBLIC_HOST = "media.openuniversity.si";
type Env = Readonly<Record<string, string | undefined>>;

/** Dev bridge. The adapters register it; this module does not name it. */
export interface MediaHostContribution {
  acceptsOverride(host: string): boolean;
}
let contribution: MediaHostContribution | undefined;
export function registerMediaHosts(next: MediaHostContribution): void {
  contribution = next;
}

/** Active public host. An override is accepted only after the storage adapters register their bridge. */
export function mediaPublicHost(env: Env): string {
  const host = env.TOWER_MEDIA_PUBLIC_HOST?.trim().toLowerCase();
  if (!host || host === MEDIA_PUBLIC_HOST) return MEDIA_PUBLIC_HOST;
  if (contribution?.acceptsOverride(host)) return host;
  throw new Error(`TOWER_MEDIA_PUBLIC_HOST, when set, must be ${MEDIA_PUBLIC_HOST} or the storage adapter bridge; remove it to use the default.`);
}
/** Every host a stored media URL may use: the active public host. There is no list of previous hosts. */
export function mediaPublicHosts(env: Env): string[] {
  return [mediaPublicHost(env)];
}
export const courseKinds = coverKindsByOwner.course;
export const lessonKinds = coverKindsByOwner.lesson;
export const subareaKinds = coverKindsByOwner.subarea;
export const areaKinds = coverKindsByOwner.area;
export const institutionKinds = coverKindsByOwner.institution;
export const ownerSchema = z.enum(["institution", "area", "subarea", "course", "lesson"]);
export const ownerIdSchema = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).max(LIMITS.mediaOwnerId);
export const variantSchema = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).max(LIMITS.mediaVariant);
export const transformSchema = z.tuple([z.tuple([z.number(), z.number(), z.number()]), z.tuple([z.number(), z.number(), z.number()])]).nullable();
export interface PublicMediaPolicy { readonly host: string; readonly acceptedHosts: readonly string[] }
/** Hosts for one deployment. Production code passes the facade map; domain code passes this map and never reads the environment. */
export function mediaPolicy(env: Env): PublicMediaPolicy {
  return { host: mediaPublicHost(env), acceptedHosts: mediaPublicHosts(env) };
}
/** The constant production host. Dev bridges pass `mediaPolicy(env)` instead. */
export const productionMediaPolicy: PublicMediaPolicy = {
  host: MEDIA_PUBLIC_HOST,
  acceptedHosts: [MEDIA_PUBLIC_HOST],
};
export { MEDIA_CACHE_CONTROL } from "../../kernel/cache.ts";
export const mediaContentType = (pathname: string) => { const ext = pathname.slice(pathname.lastIndexOf(".") + 1); return `image/${ext === "jpg" ? "jpeg" : ext}`; };
const mediaUrlMessage = "Expected a public Open University covers URL.";
function isMediaUrl(value: string, hosts: readonly string[]): boolean {
  const url = new URL(value);
  return url.protocol === "https:" && hosts.includes(url.hostname) && (url.pathname.startsWith("/covers/") || /^\/m\/[a-f0-9]{64}\.(jpg|png|webp|avif)$/.test(url.pathname)) && !url.search && !url.hash && !url.username && !url.password && !url.port;
}
/** URL grammar for an explicit host list. The production schema reads the registered hosts when a value is parsed. */
export function mediaUrlSchemaFor(hosts: readonly string[]) {
  return z.url().refine((value) => isMediaUrl(value, hosts), mediaUrlMessage);
}
export const mediaUrlSchema = z.url().refine((value) => isMediaUrl(value, productionMediaPolicy.acceptedHosts), mediaUrlMessage);
export const assetSchema = z.object({
  id: z.string(), ownerId: ownerIdSchema, kind: z.enum([...courseKinds, "cover_16x9", "cover_9x16", "og", "author_cover_9x16", "university_cover_9x16"]), variant: variantSchema,
  url: mediaUrlSchema, pathname: z.string().regex(/^(?:covers\/[a-z0-9-]+\/[a-z0-9_]+\/[a-f0-9]{40}|m\/[a-f0-9]{64})\.(?:jpg|png|webp|avif)$/),
  mediaSha256: z.string().regex(/^[a-f0-9]{64}$/).nullable().optional(),
  width: z.number().int().positive(), height: z.number().int().positive(), sha256: z.string().regex(/^[a-f0-9]{64}$/),
  alt: z.string().trim().min(EXTENT.one).max(LIMITS.mediaAlt), transform: transformSchema,
  designStatus: z.enum(["approved", "draft", "legacy"]), version: z.number().int().positive(),
  isActive: z.boolean(), createdAt: z.coerce.date(), updatedAt: z.coerce.date(),
}).refine((asset) => new URL(asset.url).pathname === `/${asset.pathname}`, "URL and pathname must agree.");
export type MediaAsset = z.infer<typeof assetSchema>;
export type MediaOwner = z.infer<typeof ownerSchema>;
export type MediaKind = MediaAsset["kind"];
export type AssetInput = Omit<MediaAsset, "id" | "version" | "isActive" | "createdAt" | "updatedAt">;
const kindsOf = (owner: MediaOwner): readonly [string, ...string[]] => coverKindsByOwner[owner];

/** Every owner is one row shape in `catalog_media` (INV-M1). `owner` is a closed enum, safe to interpolate. */
export function mediaKey(owner: MediaOwner, ownerId: string, kind: string, variant = "default") {
  ownerSchema.parse(owner); ownerIdSchema.parse(ownerId); variantSchema.parse(variant);
  z.enum(kindsOf(owner)).parse(kind);
  return { table: "catalog_media" as const, column: "owner_id" as const, owner, ownerId, kind, variant };
}
