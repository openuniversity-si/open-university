import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import type { AdapterInput } from "../ports/source-adapter.ts";
import { assertFiftyPerCall, assertOriginalTitle, ingestRecorded } from "../testing/adapter-contract.ts";
import { createYouTubePlaylistAdapter } from "./youtube-adapter.ts";

const sha = (digit: string) => digit.repeat(64);
const TRANSLATED = "General Mechanics - Lecture 01";
const ORIGINAL = "Mecânica Geral - Aula 01";
const SCHEDULED = "bcdefghijkl";

interface PlaylistPage { readonly items: readonly unknown[]; readonly nextPageToken?: string }
interface Fixture { readonly playlistPages: readonly PlaylistPage[]; readonly videos: Readonly<Record<string, unknown>> }

const fixture = JSON.parse(readFileSync(new URL("../testing/fixtures/youtube-playlist.json", import.meta.url), "utf8")) as Fixture;

function input(apiKey = "recorded-key"): AdapterInput {
  return {
    runId: "brasil-2026-10-22",
    institution: {
      id: "usp", slug: "usp", name: "USP", fullName: "Universidade de São Paulo", place: "São Paulo, Brazil",
      kind: "institution", monogram: "USP",
      cover: { poster: sha("b"), og: sha("c"), alt: "Universidade de São Paulo", credit: "Photo: USP", sourceUrl: "https://www.usp.br", license: "CC BY 4.0" },
      homeRow: { after: "iit-madras", visible: true },
    },
    playlistId: "PLmecanica01",
    playlistTitle: "Mecânica Geral",
    channelId: `UC${"a".repeat(22)}`,
    channelTitle: "USP",
    channelUrl: "https://www.youtube.com/@usp",
    apiKey,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function respondRecorded(url: URL): Response {
  if (url.pathname.endsWith("/playlistItems")) {
    const token = url.searchParams.get("pageToken");
    const page = fixture.playlistPages[token === null ? 0 : Number(token)];
    return page === undefined ? json({ error: "missing page" }, 404) : json(page);
  }
  if (url.pathname.endsWith("/videos")) {
    const ids = url.searchParams.get("id")?.split(",").filter((id) => id !== "") ?? [];
    return json({ items: ids.flatMap((id) => { const video = fixture.videos[id]; return video === undefined ? [] : [video]; }) });
  }
  return json({ error: "unknown" }, 404);
}

describe("YouTube playlist adapter", () => {
  it("keeps the Data API title, skips the scheduled video, and never calls oEmbed", async () => {
    const { curated, calls } = await ingestRecorded(createYouTubePlaylistAdapter(), input(), respondRecorded);
    assertOriginalTitle(curated, ORIGINAL, SCHEDULED);
    assertFiftyPerCall(calls);
    const lesson = curated.courses[0]?.lessons?.[0];
    expect(lesson?.originalTitle).toBe(ORIGINAL);
    expect(lesson?.originalTitle).not.toBe(TRANSLATED);
    expect(JSON.stringify(curated)).not.toContain(TRANSLATED);
    expect(lesson?.durationSeconds).toBe(3120);
    expect(lesson?.uploadDate).toBe("2021-03-02");
    expect(lesson?.position).toBe(1);
    expect(curated.courses[0]?.decision).toBe("hold");
    expect(curated.courses[0]?.holdReason).toBe("needs-curation");
    expect(curated.provenance.counts).toEqual({ videos: 2, skippedScheduled: 1 });
    expect(curated.run.adapter).toBe("youtube-playlist@1");
    expect(calls.every((call) => new URL(call).searchParams.get("key") === "recorded-key")).toBe(true);
    expect(calls.some((call) => call.toLowerCase().includes("oembed"))).toBe(false);
  });

  it("asks for 50 videos per videos.list call", async () => {
    const total = 51;
    const idOf = (index: number) => `v${String(index).padStart(10, "0")}`;
    const video = (index: number) => ({
      id: idOf(index),
      snippet: { title: `Aula ${String(index + 1)}`, publishedAt: "2021-03-02T12:00:00Z", liveBroadcastContent: "none" },
      contentDetails: { duration: "PT52M" },
    });
    const pages: PlaylistPage[] = [
      { items: Array.from({ length: 50 }, (_, index) => ({ snippet: { title: "ignored", position: index }, contentDetails: { videoId: idOf(index) } })), nextPageToken: "1" },
      { items: [{ snippet: { title: "ignored", position: 50 }, contentDetails: { videoId: idOf(50) } }] },
    ];
    const { curated, calls } = await ingestRecorded(createYouTubePlaylistAdapter(), input(), (url) => {
      if (url.pathname.endsWith("/playlistItems")) {
        const token = url.searchParams.get("pageToken");
        const page = pages[token === null ? 0 : Number(token)];
        return page === undefined ? json({ error: "missing page" }, 404) : json(page);
      }
      if (url.pathname.endsWith("/videos")) {
        const ids = url.searchParams.get("id")?.split(",").filter((item) => item !== "") ?? [];
        return json({ items: ids.map((id) => video(Number(id.slice(1)))) });
      }
      return json({ error: "unknown" }, 404);
    });
    assertFiftyPerCall(calls);
    const videoCalls = calls.filter((call) => call.includes("/videos?")).map((call) => new URL(call).searchParams.get("id")?.split(",") ?? []);
    expect(videoCalls.map((ids) => ids.length)).toEqual([50, 1]);
    expect(calls.filter((call) => call.includes("/playlistItems?")).map((call) => new URL(call).searchParams.get("maxResults"))).toEqual(["50", "50"]);
    expect(curated.courses[0]?.lessons).toHaveLength(total);
    expect(curated.provenance.counts.skippedScheduled).toBe(0);
  });

  it("keeps only the playlist positions in the range and does not request the others", async () => {
    const idOf = (position: number) => `vid${String(position).padStart(8, "0")}`;
    const item = (position: number) => ({ snippet: { title: "ignored", position }, contentDetails: { videoId: idOf(position) } });
    const pages: PlaylistPage[] = [
      { items: [item(0), item(1)], nextPageToken: "1" },
      { items: [item(2)] },
    ];
    const { curated, calls } = await ingestRecorded(createYouTubePlaylistAdapter(), { ...input(), positions: { from: 2, to: 3 } }, (url) => {
      if (url.pathname.endsWith("/playlistItems")) {
        const token = url.searchParams.get("pageToken");
        const page = pages[token === null ? 0 : Number(token)];
        return page === undefined ? json({ error: "missing page" }, 404) : json(page);
      }
      if (url.pathname.endsWith("/videos")) {
        const ids = url.searchParams.get("id")?.split(",").filter((value) => value !== "") ?? [];
        return json({ items: ids.map((id) => ({ id, snippet: { title: `Aula ${id}`, publishedAt: "2021-03-02T12:00:00Z", liveBroadcastContent: "none" }, contentDetails: { duration: "PT52M" } })) });
      }
      return json({ error: "unknown" }, 404);
    });
    expect(curated.courses[0]?.positions).toEqual({ from: 2, to: 3 });
    expect(curated.courses[0]?.lessons?.map((lesson) => lesson.position)).toEqual([2, 3]);
    expect(curated.provenance.counts).toEqual({ videos: 2, skippedScheduled: 0 });
    const videoIds = calls.filter((call) => call.includes("/videos?")).flatMap((call) => new URL(call).searchParams.get("id")?.split(",") ?? []);
    expect(videoIds).toEqual([idOf(1), idOf(2)]);
    expect(calls.filter((call) => call.includes("/playlistItems?"))).toHaveLength(2);
  });

  it("stops paging once the playlist position range is passed", async () => {
    const idOf = (position: number) => `end${String(position).padStart(8, "0")}`;
    const { calls } = await ingestRecorded(createYouTubePlaylistAdapter(), { ...input(), positions: { from: 1, to: 1 } }, (url) => {
      if (url.pathname.endsWith("/playlistItems")) {
        return json({
          items: [
            { snippet: { title: "ignored", position: 0 }, contentDetails: { videoId: idOf(0) } },
            { snippet: { title: "ignored", position: 1 }, contentDetails: { videoId: idOf(1) } },
          ],
          nextPageToken: "more",
        });
      }
      if (url.pathname.endsWith("/videos")) {
        return json({ items: [{ id: idOf(0), snippet: { title: "Aula 1", publishedAt: "2021-03-02T12:00:00Z", liveBroadcastContent: "none" }, contentDetails: { duration: "PT52M" } }] });
      }
      return json({ error: "unknown" }, 404);
    });
    expect(calls.filter((call) => call.includes("/playlistItems?"))).toHaveLength(1);
    expect(calls.some((call) => call.includes("pageToken=more"))).toBe(false);
  });

  it("names an inverted position range and makes no request", async () => {
    const calls: string[] = [];
    const fetchImpl: typeof fetch = (resource) => {
      calls.push(typeof resource === "string" ? resource : resource instanceof URL ? resource.href : resource.url);
      return Promise.resolve(json({}));
    };
    await expect(createYouTubePlaylistAdapter().ingest({ ...input(), positions: { from: 4, to: 2 } }, {
      fetch: fetchImpl, cache: { get: () => Promise.resolve(null), set: () => Promise.resolve() }, now: () => new Date("2026-10-22T13:00:00.000Z"), concurrency: 1,
    })).rejects.toMatchObject({ message: expect.stringMatching(/positions\.from/) as string });
    expect(calls).toEqual([]);
  });

  it("stops before any request when the key is missing", async () => {
    const calls: string[] = [];
    const fetchImpl: typeof fetch = (resource) => {
      calls.push(typeof resource === "string" ? resource : resource instanceof URL ? resource.href : resource.url);
      return Promise.resolve(json({}));
    };
    await expect(createYouTubePlaylistAdapter().ingest(input(""), {
      fetch: fetchImpl, cache: { get: () => Promise.resolve(null), set: () => Promise.resolve() }, now: () => new Date("2026-10-22T13:00:00.000Z"), concurrency: 1,
    })).rejects.toMatchObject({ code: "unconfigured", message: expect.stringMatching(/YouTube Data API key/) as string });
    expect(calls).toEqual([]);
  });

  it("redacts the key when the Data API refuses the call", async () => {
    const secret = "super-secret-key";
    await expect(ingestRecorded(createYouTubePlaylistAdapter(), input(secret), () => json({ error: "quota" }, 403))).rejects.toBeInstanceOf(AppError);
    try {
      await ingestRecorded(createYouTubePlaylistAdapter(), input(secret), () => json({ error: "quota" }, 403));
    } catch (error) {
      expect(error).toBeInstanceOf(AppError);
      expect(error instanceof AppError ? error.code : "").toBe("upstream_failed");
      expect(error instanceof Error ? error.message : "").not.toContain(secret);
      expect(error instanceof Error ? error.message : "").toContain("key=redacted");
    }
  });
});
