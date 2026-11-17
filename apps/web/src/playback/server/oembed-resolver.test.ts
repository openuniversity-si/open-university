import { describe, expect, it, vi } from "vitest";
import { OEMBED_CHECKER as checkerFromPort } from "../ports/oembed.ts";
import { createYouTubeOEmbed, OEMBED_CHECKER, OEmbedUnavailableError } from "./oembed-resolver.ts";

describe("YouTube oEmbed check", () => {
  it("reexports the same checker the port declares", () => {
    expect(OEMBED_CHECKER).toBe(checkerFromPort);
    expect(OEMBED_CHECKER).toBe("oembed");
  });

  const respond = (status: number, body: unknown = {}) => vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));

  it("maps 200, 401/403 and 400/404 to ok, embed-disabled and unavailable", async () => {
    const fetchOk = respond(200, { title: "Lecture 1", author_name: "YaleCourses" });
    expect(await createYouTubeOEmbed(fetchOk as unknown as typeof fetch)("abcdefghijk")).toEqual({ status: "ok", title: "Lecture 1", authorName: "YaleCourses" });
    expect(String((fetchOk.mock.calls[0] as unknown[])[0])).toBe("https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabcdefghijk&format=json");
    for (const [status, expected] of [[401, "embed-disabled"], [403, "embed-disabled"], [400, "unavailable"], [404, "unavailable"]] as const) {
      expect((await createYouTubeOEmbed(respond(status) as unknown as typeof fetch)("abcdefghijk")).status).toBe(expected);
    }
    expect(await createYouTubeOEmbed(respond(200, "not an object") as unknown as typeof fetch)("abcdefghijk")).toEqual({ status: "ok" });
  });

  it("throws an upstream failure for 5xx and network errors (never a verdict on the video)", async () => {
    await expect(createYouTubeOEmbed(respond(503) as unknown as typeof fetch)("abcdefghijk")).rejects.toBeInstanceOf(OEmbedUnavailableError);
    const offline = vi.fn(() => Promise.reject(new TypeError("fetch failed")));
    await expect(createYouTubeOEmbed(offline as unknown as typeof fetch)("abcdefghijk")).rejects.toThrow("YouTube oEmbed failed (TypeError).");
  });

  it("releases the body of every answer it does not read, so no socket waits for garbage collection", async () => {
    for (const status of [400, 401, 403, 404, 503]) {
      let cancelled = false;
      const body = new ReadableStream({ cancel() { cancelled = true; } });
      const fetchImpl = vi.fn(() => Promise.resolve(new Response(body, { status })));
      await createYouTubeOEmbed(fetchImpl as unknown as typeof fetch)("abcdefghijk").catch(() => undefined);
      expect(cancelled, String(status)).toBe(true);
    }
  });
});
