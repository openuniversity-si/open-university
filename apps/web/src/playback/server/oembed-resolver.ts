import { AppError } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { mapLimited, metadataIsFresh, OEMBED_CONCURRENCY } from "../domain/oembed-schedule.ts";
import type { CachedVideoMetadata, OEmbed, OEmbedResolverPort, VideoIdentity, VideoMetadataResult } from "../ports/oembed.ts";
import type { CspDomains } from "../ports/source-driver.ts";
export { OEMBED_CHECKER, type EmbedStatus, type OEmbed, type OEmbedResult } from "../ports/oembed.ts";
/**
 * YouTube oEmbed, the official embed check (plan §4.1): 200 = ok, 401/403 = embed disabled, 400/404 = deleted or private
 * (oEmbed cannot tell which). Anything else is an upstream failure (502). Injected in the deps; tests never use the network.
 */

/** The oEmbed endpoint failed in a way that says nothing about the video (5xx, timeout, network). */
export class OEmbedUnavailableError extends AppError {
  constructor(status: number | string) { super("upstream_failed", `YouTube oEmbed failed (${String(status)}).`); this.name = "OEmbedUnavailableError"; }
}

export interface OEmbedTransport {
  (identity: VideoIdentity, signal?: AbortSignal): Promise<CachedVideoMetadata>;
}

/** Pool of 16, one lookup per id, cache fresh for under 24 hours. The transport is injected so tests never hit the network. */
export function createOEmbedResolver(deps: {
  readonly now: () => Date;
  readonly transport: OEmbedTransport;
  readonly cache?: Map<string, CachedVideoMetadata>;
}): OEmbedResolverPort {
  const cache = deps.cache ?? new Map<string, CachedVideoMetadata>();
  const inflight = new Map<string, Promise<CachedVideoMetadata>>();
  const load = (identity: VideoIdentity, signal?: AbortSignal) => {
    const key = `${identity.provider}:${identity.externalId}`;
    const cached = cache.get(key);
    if (cached && "verifiedAt" in cached && metadataIsFresh(cached.verifiedAt, deps.now())) return Promise.resolve(cached);
    const pending = inflight.get(key);
    if (pending) return pending;
    const promise = deps.transport(identity, signal).then((result) => {
      cache.set(key, result);
      return result;
    }).finally(() => { inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  };
  return {
    async resolveMany(input, signal) {
      const unique = [...new Map(input.map((identity) => [`${identity.provider}:${identity.externalId}`, identity])).values()];
      const resolved = new Map<string, VideoMetadataResult>();
      await mapLimited(unique, OEMBED_CONCURRENCY, async (identity) => {
        const result = await load(identity, signal);
        resolved.set(`${identity.provider}:${identity.externalId}`, { ...result, identity });
      });
      return input.map((identity) => {
        const result = resolved.get(`${identity.provider}:${identity.externalId}`);
        if (!result) throw new AppError("internal", "Missing oEmbed result.");
        return result;
      });
    },
  };
}

/** Frame, script and thumbnail origins. The driver registry copies them onto the registered embed driver. */
export function embedContentSources(): CspDomains {
  return {
    scriptSrc: ["https://www.youtube.com"],
    frameSrc: ["https://www.youtube.com"],
    mediaSrc: [],
    imgSrc: ["https://i.ytimg.com"],
    connectSrc: [],
  };
}

export function createOEmbed(fetchImpl: typeof fetch = fetch): OEmbed {
  return createYouTubeOEmbed(fetchImpl);
}

export function createYouTubeOEmbed(fetchImpl: typeof fetch = fetch): OEmbed {
  return async (youtubeId) => {
    const watch = `https://www.youtube.com/watch?v=${encodeURIComponent(youtubeId)}`;
    let response: Response;
    try {
      response = await fetchImpl(`https://www.youtube.com/oembed?url=${encodeURIComponent(watch)}&format=json`, { redirect: "error", signal: AbortSignal.timeout(LIMITS.oembedTimeoutMs) });
    } catch (error) {
      throw new OEmbedUnavailableError(error instanceof Error ? error.name : "network");
    }
    // An unread body keeps its socket until garbage collection; release it on every answer that is not read.
    if (!response.ok) await response.body?.cancel().catch(() => undefined);
    if (response.status === 401 || response.status === 403) return { status: "embed-disabled" };
    if (response.status === 400 || response.status === 404) return { status: "unavailable" };
    if (!response.ok) throw new OEmbedUnavailableError(response.status);
    const body = await response.json().catch(() => ({})) as { title?: unknown; author_name?: unknown };
    return {
      status: "ok",
      ...(typeof body.title === "string" ? { title: body.title } : {}),
      ...(typeof body.author_name === "string" ? { authorName: body.author_name } : {}),
    };
  };
}
