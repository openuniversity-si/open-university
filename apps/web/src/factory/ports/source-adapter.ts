import type { CuratedV1 } from "../domain/curated.ts";

// One source shape in, one curated/v1 out (docs/architecture/FACTORY.md). The YouTube adapter is S13.

export interface KeyValueCache {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
}

export interface AdapterDeps {
  readonly fetch: typeof fetch;
  readonly cache: KeyValueCache;
  readonly now: () => Date;
  readonly concurrency: number;
}

/** What the operator already knows. The adapter fills sources, courses and provenance. */
export interface AdapterInput {
  readonly runId: string;
  readonly institution: CuratedV1["institution"];
  readonly playlistId: string;
  readonly playlistTitle: string;
  readonly channelId: string;
  readonly channelTitle: string;
  readonly channelUrl: string;
  /** Empty when the operator secret store has no key. The adapter stops instead of calling the network. */
  readonly apiKey: string;
  /** Inclusive 1-based playlist positions. Absent means the whole playlist. */
  readonly positions?: { readonly from: number; readonly to: number };
}

export interface SourceAdapter {
  readonly id: string;
  /** Courses of one institution, with original titles and real durations. */
  ingest(input: AdapterInput, deps: AdapterDeps): Promise<CuratedV1>;
}
