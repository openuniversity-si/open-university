import type { CuratedV1 } from "../domain/curated.ts";
import type { AdapterDeps, AdapterInput, KeyValueCache, SourceAdapter } from "../ports/source-adapter.ts";

// D-018. Runs a source adapter against a recorded fetch. No network, no oEmbed, batches of at most 50.

export function memoryCache(): KeyValueCache {
  const values = new Map<string, string>();
  return {
    get: (key) => Promise.resolve(values.get(key) ?? null),
    set: (key, value) => { values.set(key, value); return Promise.resolve(); },
  };
}

export interface RecordedRun {
  readonly curated: CuratedV1;
  readonly calls: readonly string[];
}

/** Ingest with a stand-in fetch. An oEmbed URL fails the run. */
export async function ingestRecorded(adapter: SourceAdapter, input: AdapterInput, respond: (url: URL) => Response): Promise<RecordedRun> {
  const calls: string[] = [];
  const fetchImpl: typeof fetch = (resource) => {
    const url = new URL(typeof resource === "string" ? resource : resource instanceof URL ? resource.href : resource.url);
    calls.push(url.toString());
    if (url.pathname.toLowerCase().includes("oembed") || url.hostname.toLowerCase().includes("oembed")) {
      return Promise.reject(new Error("oEmbed request"));
    }
    return Promise.resolve(respond(url));
  };
  const deps: AdapterDeps = { fetch: fetchImpl, cache: memoryCache(), now: () => new Date("2026-10-22T13:00:00.000Z"), concurrency: 1 };
  const curated = await adapter.ingest(input, deps);
  return { curated, calls };
}

/** The lesson title is the one the recorded Data API video returned, and the scheduled video is counted and absent. */
export function assertOriginalTitle(curated: CuratedV1, title: string, skippedVideoId: string): void {
  const lessons = curated.courses.flatMap((course) => course.lessons ?? []);
  if (!lessons.some((lesson) => lesson.originalTitle === title)) throw new Error(`original title was not kept: ${title}`);
  if (lessons.some((lesson) => lesson.youtubeId === skippedVideoId)) throw new Error(`scheduled video ${skippedVideoId} was kept`);
  if (curated.provenance.titles !== "original") throw new Error("provenance.titles is not original");
  if (curated.provenance.counts.skippedScheduled < 1) throw new Error("skippedScheduled was not counted");
}

/** playlistItems asks for 50, and every videos.list call carries 1 to 50 ids. No call is oEmbed. */
export function assertFiftyPerCall(calls: readonly string[]): void {
  const videos = calls.filter((call) => call.includes("/videos?"));
  const pages = calls.filter((call) => call.includes("/playlistItems?"));
  if (videos.length === 0 || pages.length === 0) throw new Error("expected playlistItems and videos calls");
  for (const call of pages) {
    if (new URL(call).searchParams.get("maxResults") !== "50") throw new Error("playlistItems maxResults is not 50");
  }
  for (const call of videos) {
    const ids = new URL(call).searchParams.get("id")?.split(",").filter((id) => id !== "") ?? [];
    if (ids.length < 1 || ids.length > 50) throw new Error(`videos.list batch of ${String(ids.length)}`);
  }
  if (calls.some((call) => call.toLowerCase().includes("oembed"))) throw new Error("oEmbed request");
}
