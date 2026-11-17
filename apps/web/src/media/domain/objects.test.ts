import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { objectKey, objectUrl } from "./objects.ts";
import "../server/public-hosts.ts";
import { MEDIA_PUBLIC_HOST, mediaUrlSchema, productionMediaPolicy } from "./types.ts";

const corpus = JSON.parse(readFileSync(new URL("./media-key-contract.json", import.meta.url), "utf8")) as {
  sha64: string; sha40: string; sha63: string; sha65: string; extensions: string[]; contentPath: string; legacyPath: string; rejectedPaths: string[];
};

const fill = (path: string, ext = "webp") => path
  .replaceAll("{sha64}", corpus.sha64)
  .replaceAll("{sha40}", corpus.sha40)
  .replaceAll("{sha63}", corpus.sha63)
  .replaceAll("{sha65}", corpus.sha65)
  .replaceAll("{sha64upper}", corpus.sha64.toUpperCase())
  .replaceAll("{ext}", ext);

describe("object keys", () => {
  it("builds the content-addressed key and the public URL from an explicit host", () => {
    expect(objectKey(corpus.sha64, "webp")).toBe(`m/${corpus.sha64}.webp`);
    expect(objectUrl({ sha256: corpus.sha64, ext: "webp" }, productionMediaPolicy)).toBe(`https://${MEDIA_PUBLIC_HOST}/m/${corpus.sha64}.webp`);
    expect(mediaUrlSchema.safeParse(`https://${MEDIA_PUBLIC_HOST}${fill(corpus.legacyPath)}`).success).toBe(true);
    expect(mediaUrlSchema.safeParse(`https://legacy-store.example${fill(corpus.legacyPath)}`).success).toBe(false);
    for (const ext of corpus.extensions) expect(mediaUrlSchema.safeParse(`https://${MEDIA_PUBLIC_HOST}${fill(corpus.contentPath, ext)}`).success).toBe(true);
    for (const path of corpus.rejectedPaths) expect(mediaUrlSchema.safeParse(`https://${MEDIA_PUBLIC_HOST}${fill(path)}`).success).toBe(false);
  });
});
