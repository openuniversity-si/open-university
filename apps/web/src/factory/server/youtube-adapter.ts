import { AppError, unprocessable } from "../../kernel/errors.ts";
import { parseCurated, type CuratedV1 } from "../domain/curated.ts";
import { youtubeDurationSeconds } from "../domain/iso-duration.ts";
import type { AdapterDeps, AdapterInput, SourceAdapter } from "../ports/source-adapter.ts";

// YouTube Data API v3 only (D-018): playlistItems.list + videos.list, 50 per call.
// snippet.title from videos.list is the original title. oEmbed is not used. No key, no call.

const API = "https://www.googleapis.com/youtube/v3";
const PAGE = 50;

export function createYouTubePlaylistAdapter(): SourceAdapter {
  return { id: "youtube-playlist@1", ingest };
}

async function ingest(input: AdapterInput, deps: AdapterDeps): Promise<CuratedV1> {
  if (input.apiKey.trim() === "") {
    throw new AppError("unconfigured", "YouTube Data API key is missing. Set YOUTUBE_API_KEY in the operator secret store. The adapter does not call YouTube without it.");
  }
  if (deps.concurrency < 1) throw unprocessable("Adapter concurrency is at least 1.");
  const positions = rangeOf(input.positions);
  const items = (await listPlaylist(input, deps, positions)).filter((item) => inRange(item, positions));
  const details = await listVideos(items.map((item) => item.videoId), input.apiKey, deps);
  let skippedScheduled = 0;
  const lessons = [];
  for (const item of items) {
    const video = details.get(item.videoId);
    if (video === undefined) throw unprocessable(`videos.list did not return ${item.videoId}.`);
    if (video.upcoming) { skippedScheduled += 1; continue; }
    lessons.push({
      youtubeId: item.videoId,
      originalTitle: video.title,
      durationSeconds: video.durationSeconds,
      uploadDate: video.uploadDate,
      position: item.position + 1,
      part: "lectures" as const,
    });
  }
  const parsed = parseCurated({
    format: "curated/v1",
    run: { id: input.runId, createdAt: deps.now().toISOString(), adapter: "youtube-playlist@1" },
    institution: input.institution,
    sources: [{ id: `yt-${input.institution.id}`, kind: "youtube-playlist", title: input.channelTitle, url: input.channelUrl, youtubeChannelId: input.channelId }],
    courses: [{
      sourcePlaylistId: input.playlistId,
      decision: "hold",
      holdReason: "needs-curation",
      title: input.playlistTitle,
      originalTitle: input.playlistTitle,
      ...(positions === undefined ? {} : { positions }),
      lessons,
    }],
    provenance: { titles: "original", fetchedAt: deps.now().toISOString(), counts: { videos: items.length, skippedScheduled } },
  });
  if (!parsed.ok) throw unprocessable(parsed.issues.map((issue) => issue.message).join("\n"), { issues: parsed.issues });
  return parsed.value;
}

interface PlaylistItem { readonly videoId: string; readonly position: number }
interface VideoDetail { readonly title: string; readonly durationSeconds: number; readonly uploadDate: string; readonly upcoming: boolean }

function rangeOf(positions: AdapterInput["positions"]): { readonly from: number; readonly to: number } | undefined {
  if (positions === undefined) return undefined;
  if (!Number.isInteger(positions.from) || !Number.isInteger(positions.to) || positions.from < 1 || positions.to < 1) {
    throw unprocessable("positions.from: playlist positions are positive integers.", { issues: [{ name: "positions.from", message: "positions.from: playlist positions are positive integers." }] });
  }
  if (positions.from > positions.to) {
    throw unprocessable("positions.from: positions.from is after positions.to.", { issues: [{ name: "positions", message: "positions.from: positions.from is after positions.to." }] });
  }
  return positions;
}

/** Lesson positions are 1-based. YouTube's snippet.position is 0-based. */
function inRange(item: PlaylistItem, positions: { readonly from: number; readonly to: number } | undefined): boolean {
  if (positions === undefined) return true;
  const position = item.position + 1;
  return position >= positions.from && position <= positions.to;
}

async function listPlaylist(input: AdapterInput, deps: AdapterDeps, positions: { readonly to: number } | undefined): Promise<PlaylistItem[]> {
  const items: PlaylistItem[] = [];
  const seen = new Set<string>();
  let pageToken: string | undefined;
  do {
    if (pageToken !== undefined) {
      if (seen.has(pageToken)) throw unprocessable("playlistItems: repeated pageToken.");
      seen.add(pageToken);
    }
    const payload = await getJson(deps, endpoint("playlistItems", {
      part: "snippet,contentDetails", playlistId: input.playlistId, maxResults: String(PAGE),
      ...(pageToken === undefined ? {} : { pageToken }),
    }, input.apiKey));
    const page = readPlaylist(payload);
    let stop = false;
    for (const item of page.items) {
      if (positions !== undefined && item.position + 1 > positions.to) { stop = true; break; }
      items.push(item);
    }
    pageToken = stop ? undefined : page.nextPageToken;
  } while (pageToken !== undefined);
  return items;
}

async function listVideos(ids: readonly string[], apiKey: string, deps: AdapterDeps): Promise<Map<string, VideoDetail>> {
  const details = new Map<string, VideoDetail>();
  for (let index = 0; index < ids.length; index += PAGE) {
    const chunk = ids.slice(index, index + PAGE);
    const payload = await getJson(deps, endpoint("videos", {
      part: "snippet,contentDetails", id: chunk.join(","), maxResults: String(PAGE),
    }, apiKey));
    for (const video of readVideos(payload)) details.set(video.id, video.detail);
  }
  return details;
}

function endpoint(path: string, params: Readonly<Record<string, string>>, apiKey: string): string {
  const url = new URL(`${API}/${path}`);
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value);
  url.searchParams.set("key", apiKey);
  return url.toString();
}

async function getJson(deps: AdapterDeps, url: string): Promise<unknown> {
  const cached = await deps.cache.get(url);
  if (cached !== null) return JSON.parse(cached) as unknown;
  const response = await deps.fetch(url);
  if (!response.ok) throw new AppError("upstream_failed", `YouTube Data API answered ${String(response.status)} for ${redact(url)}.`);
  const text = await response.text();
  await deps.cache.set(url, text);
  return JSON.parse(text) as unknown;
}

function redact(url: string): string {
  return url.replace(/([?&]key=)[^&]*/g, "$1redacted");
}

function asObject(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw unprocessable(`${name}: expected an object.`);
  return value as Record<string, unknown>;
}

function readPlaylist(payload: unknown): { items: PlaylistItem[]; nextPageToken?: string } {
  const body = asObject(payload, "playlistItems");
  if (!Array.isArray(body.items)) throw unprocessable("playlistItems.items: expected a list.");
  const items = body.items.map((item, index) => {
    const row = asObject(item, `playlistItems.items.${String(index)}`);
    const details = asObject(row.contentDetails, `playlistItems.items.${String(index)}.contentDetails`);
    const snippet = asObject(row.snippet, `playlistItems.items.${String(index)}.snippet`);
    if (typeof details.videoId !== "string" || typeof snippet.position !== "number") {
      throw unprocessable(`playlistItems.items.${String(index)}: videoId and position are required.`);
    }
    return { videoId: details.videoId, position: snippet.position };
  });
  return { items, ...(typeof body.nextPageToken === "string" ? { nextPageToken: body.nextPageToken } : {}) };
}

function readVideos(payload: unknown): { id: string; detail: VideoDetail }[] {
  const body = asObject(payload, "videos");
  if (!Array.isArray(body.items)) throw unprocessable("videos.items: expected a list.");
  return body.items.map((item, index) => {
    const row = asObject(item, `videos.items.${String(index)}`);
    const snippet = asObject(row.snippet, `videos.items.${String(index)}.snippet`);
    const details = asObject(row.contentDetails, `videos.items.${String(index)}.contentDetails`);
    if (typeof row.id !== "string" || typeof snippet.title !== "string") throw unprocessable(`videos.items.${String(index)}: id and title are required.`);
    const upcoming = snippet.liveBroadcastContent === "upcoming";
    const durationSeconds = youtubeDurationSeconds(typeof details.duration === "string" ? details.duration : "");
    const published = typeof snippet.publishedAt === "string" ? snippet.publishedAt.slice(0, 10) : "";
    if (!upcoming && (durationSeconds === null || durationSeconds < 1 || !/^\d{4}-\d{2}-\d{2}$/.test(published))) {
      throw unprocessable(`videos.${row.id}: durationSeconds and uploadDate are required.`);
    }
    return { id: row.id, detail: { title: snippet.title, durationSeconds: durationSeconds ?? 0, uploadDate: published || "1970-01-01", upcoming } };
  });
}
