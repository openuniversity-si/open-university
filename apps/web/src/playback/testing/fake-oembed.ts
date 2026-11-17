import { mapLimited, metadataIsFresh, OEMBED_CONCURRENCY } from "../domain/oembed-schedule.ts";
import type { CachedVideoMetadata, OEmbedResolverPort, VideoIdentity } from "../ports/oembed.ts";

export interface FakeOEmbedDeps {
  readonly now: () => Date;
  readonly transport: (identity: VideoIdentity, signal?: AbortSignal) => Promise<CachedVideoMetadata>;
  readonly cache?: Map<string, CachedVideoMetadata>;
}

/** Deterministic resolver. No fetch and no server adapter. */
export function createFakeOEmbedResolver(deps: FakeOEmbedDeps): OEmbedResolverPort {
  const cache = deps.cache ?? new Map<string, CachedVideoMetadata>();
  const inflight = new Map<string, Promise<CachedVideoMetadata>>();
  const load = (identity: VideoIdentity, signal?: AbortSignal) => {
    const key = `${identity.provider}:${identity.externalId}`;
    const cached = cache.get(key);
    if (cached && metadataIsFresh(cached.verifiedAt, deps.now())) return Promise.resolve(cached);
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
      const resolved = new Map<string, CachedVideoMetadata>();
      await mapLimited(unique, OEMBED_CONCURRENCY, async (identity) => {
        resolved.set(`${identity.provider}:${identity.externalId}`, await load(identity, signal));
      });
      return input.flatMap((identity) => {
        const result = resolved.get(`${identity.provider}:${identity.externalId}`);
        return result ? [{ ...result, identity }] : [];
      });
    },
  };
}
