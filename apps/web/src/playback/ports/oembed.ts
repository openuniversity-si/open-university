/** Video metadata resolved outside a catalog transaction. */
export interface VideoIdentity {
  readonly provider: string;
  readonly externalId: string;
}

export type CachedVideoMetadata =
  | { readonly status: "resolved"; readonly verifiedAt: string; readonly title?: string; readonly authorName?: string; readonly durationSeconds?: number; readonly channelId?: string }
  | { readonly status: "unavailable"; readonly verifiedAt: string }
  | { readonly status: "unsupported"; readonly verifiedAt: string };

export type VideoMetadataResult = CachedVideoMetadata & { readonly identity: VideoIdentity };

export interface OEmbedResolverPort {
  /** Input order is preserved. Duplicate identities share one lookup. */
  resolveMany(input: readonly VideoIdentity[], signal?: AbortSignal): Promise<readonly VideoMetadataResult[]>;
}

/** YouTube oEmbed verdict used by catalog publish. 200 = ok, 401/403 = embed disabled, 400/404 = deleted or private. */
export type EmbedStatus = "ok" | "embed-disabled" | "unavailable";
export interface OEmbedResult {
  readonly status: EmbedStatus;
  readonly title?: string;
  readonly authorName?: string;
}
export type OEmbed = (youtubeId: string) => Promise<OEmbedResult>;

/** Written to `lesson_videos.checked_by`. The server reexports this same binding and deps inject it. */
export const OEMBED_CHECKER = "oembed";
