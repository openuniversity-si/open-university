import { describe, expect, it } from "vitest";
import { runFactory, type FactoryIo } from "./factory-cli.ts";

const sha = (digit: string) => digit.repeat(64);
const lesson = { youtubeId: "abcdefghijk", originalTitle: "Mecânica Geral - Aula 01", durationSeconds: 3120, uploadDate: "2021-03-02", position: 1, part: "lectures" };
const course = {
  sourcePlaylistId: "PLmecanica01", decision: "include", id: "usp-mecanica-geral", slug: "mecanica-geral",
  title: "Mecânica Geral", originalTitle: "Mecânica Geral - 2021", language: "Portuguese", areaId: "physics", subareaId: "mechanics",
  license: "youtube-standard", rights: "accepted-risk", canonicalUrl: "https://www.youtube.com/playlist?list=PLmecanica01",
  year: 2021, coverFrom: "own", sharedWith: [] as string[],
  cover: { poster: sha("a"), heroes: { desktop: sha("d"), present: sha("e"), mobile: sha("f") } },
  lecturer: { id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" },
  lessons: [lesson],
};
const valid = {
  format: "curated/v1",
  run: { id: "brasil-2026-10-22", createdAt: "2026-10-22T10:00:00-03:00", adapter: "youtube-playlist@1" },
  institution: {
    id: "usp", slug: "usp", name: "USP", fullName: "Universidade de São Paulo", place: "São Paulo, Brazil",
    kind: "institution", monogram: "USP",
    cover: { poster: sha("b"), og: sha("c"), alt: "Universidade de São Paulo", credit: "Photo: USP", sourceUrl: "https://www.usp.br", license: "CC BY 4.0" },
    homeRow: { after: "iit-madras", visible: true },
  },
  sources: [{ id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp", youtubeChannelId: `UC${"a".repeat(22)}` }],
  courses: [course, { sourcePlaylistId: "PLalgebra001", decision: "hold", holdReason: "needs-title" }],
  provenance: { titles: "original", fetchedAt: "2026-10-22T10:00:00-03:00", counts: { videos: 1, skippedScheduled: 0 } },
};

function io(files: Record<string, string>) {
  const stdout: string[] = [];
  const stderr: string[] = [];
  const fake: FactoryIo = {
    stdout: (text) => { stdout.push(text); },
    stderr: (text) => { stderr.push(text); },
    readFile: (path) => {
      const text = files[path];
      if (text === undefined) return Promise.reject(new Error("missing"));
      return Promise.resolve(text);
    },
  };
  return { fake, stdout, stderr };
}

describe("tower-factory", () => {
  it("validates a curated file and reports held courses", async () => {
    const harness = io({ "run.json": JSON.stringify(valid) });
    expect(await runFactory(["validate", "run.json", "--json"], harness.fake)).toBe(0);
    expect(JSON.parse(harness.stdout.join(""))).toEqual({ ok: true, data: { run: "brasil-2026-10-22", courses: 2, held: 1 } });
  });

  it("names a zero duration and a translated title", async () => {
    const zero = io({ "run.json": JSON.stringify({ ...valid, courses: [{ ...course, lessons: [{ ...lesson, durationSeconds: 0 }] }] }) });
    expect(await runFactory(["validate", "run.json"], zero.fake)).toBe(1);
    expect(zero.stderr.join("")).toMatch(/durationSeconds/);
    const translated = io({ "run.json": JSON.stringify({ ...valid, provenance: { ...valid.provenance, titles: "translated" } }) });
    expect(await runFactory(["validate", "run.json", "--json"], translated.fake)).toBe(1);
    const body = JSON.parse(translated.stdout.join("")) as { ok: false; error: { issues: { name: string }[] } };
    expect(body.ok).toBe(false);
    expect(body.error.issues.map((issue) => issue.name)).toContain("provenance.titles");
  });

  it("converts to a batch envelope and leaves the held course out", async () => {
    const harness = io({ "run.json": JSON.stringify(valid) });
    expect(await runFactory(["convert", "run.json", "--json"], harness.fake)).toBe(0);
    const body = JSON.parse(harness.stdout.join("")) as { ok: true; data: { batch: { version: number; courses: { course: { id: string } }[] }; held: { course: string }[] } };
    expect(body.ok).toBe(true);
    expect(body.data.batch.version).toBe(2);
    expect(body.data.batch.courses.map((entry) => entry.course.id)).toEqual(["usp-mecanica-geral"]);
    expect(body.data.held).toEqual([{ course: "unnamed", reason: "needs-title" }]);
  });

  it("rejects an unknown command", async () => {
    const harness = io({});
    expect(await runFactory(["publish"], harness.fake)).toBe(2);
    expect(harness.stderr.join("")).toMatch(/unknown command/);
  });

  it("does not call YouTube when the operator key is absent", async () => {
    const calls: string[] = [];
    const harness = io({ "spec.json": JSON.stringify(ingestSpec()) });
    const code = await runFactory(["ingest", "spec.json"], harness.fake, {
      env: {},
      fetch: (resource) => {
        calls.push(typeof resource === "string" ? resource : resource instanceof URL ? resource.href : resource.url);
        return Promise.resolve(new Response("{}", { status: 200 }));
      },
    });
    expect(code).toBe(2);
    expect(calls).toEqual([]);
    expect(harness.stderr.join("")).toMatch(/YOUTUBE_API_KEY/);
  });

  it("writes unapproved texts and lets the reviewer stamp its own actor", async () => {
    const curated = {
      ...valid,
      courses: [{ ...course, lessons: [lesson, { ...lesson, youtubeId: "bcdefghijkl", originalTitle: "Aula de 22/10/2026", position: 2 }] }],
    };
    const generated = io({ "run.json": JSON.stringify(curated) });
    expect(await runFactory(["texts", "run.json", "--language", "Portuguese", "--noun", "Aula", "--json"], generated.fake)).toBe(0);
    const body = JSON.parse(generated.stdout.join("")) as { ok: true; data: { texts: { approved: boolean; text: string; flags: string[] }[] } };
    expect(body.data.texts.every((text) => !text.approved)).toBe(true);
    expect(body.data.texts.find((text) => text.flags.includes("placeholder-title"))?.text).toBe("Aula de 22/10/2026");
    const review = io({ "texts.json": JSON.stringify(body.data.texts) });
    expect(await runFactory(["review", "texts.json", "--json"], review.fake, { now: () => new Date("2026-10-22T13:00:00.000Z") })).toBe(0);
    const reviewed = JSON.parse(review.stdout.join("")) as { ok: true; data: { approved: boolean; approvedBy: string | null; flags: string[] }[] };
    const open = reviewed.data.filter((text) => text.flags.includes("placeholder-title"));
    const closed = reviewed.data.filter((text) => text.flags.length === 0);
    expect(open.every((text) => !text.approved && text.approvedBy === null)).toBe(true);
    expect(closed.every((text) => text.approved && text.approvedBy === "factory-text-reviewer@1")).toBe(true);
  });

  it("rejects a text the generator tried to approve", async () => {
    const forged = [{
      entityKind: "course", entityId: "usp-mecanica-geral", field: "description", text: "Mecânica Geral", language: "Portuguese",
      approved: true, approvedBy: "factory-text-generator@1", approvedAt: "2026-10-22T13:00:00.000Z", flags: [], actor: "factory-text-generator@1",
    }];
    const harness = io({ "texts.json": JSON.stringify(forged) });
    expect(await runFactory(["review", "texts.json"], harness.fake)).toBe(1);
    expect(harness.stderr.join("")).toMatch(/generator/);
  });

  it("ingests a recorded playlist and keeps the key out of the output", async () => {
    const secret = "recorded-key";
    const harness = io({ "spec.json": JSON.stringify(ingestSpec()) });
    const code = await runFactory(["ingest", "spec.json", "--json"], harness.fake, {
      env: { YOUTUBE_API_KEY: secret },
      fetch: recordedFetch(secret),
      now: () => new Date("2026-10-22T13:00:00.000Z"),
    });
    expect(code).toBe(0);
    const body = JSON.parse(harness.stdout.join("")) as { ok: true; data: { courses: { lessons?: { originalTitle: string }[] }[]; provenance: { titles: string; counts: { skippedScheduled: number } } } };
    expect(body.data.courses[0]?.lessons?.[0]?.originalTitle).toBe("Mecânica Geral - Aula 01");
    expect(body.data.provenance.titles).toBe("original");
    expect(body.data.provenance.counts.skippedScheduled).toBe(0);
    expect(harness.stdout.join("")).not.toContain(secret);
    expect(harness.stderr.join("")).not.toContain(secret);
  });
});

function ingestSpec() {
  return {
    runId: "brasil-2026-10-22",
    institution: valid.institution,
    playlistId: "PLmecanica01",
    playlistTitle: "Mecânica Geral",
    channelId: `UC${"a".repeat(22)}`,
    channelTitle: "USP",
    channelUrl: "https://www.youtube.com/@usp",
  };
}

function recordedFetch(secret: string): typeof fetch {
  return (resource) => {
    const url = new URL(typeof resource === "string" ? resource : resource instanceof URL ? resource.href : resource.url);
    if (url.searchParams.get("key") !== secret) return Promise.resolve(new Response("denied", { status: 403 }));
    if (url.pathname.endsWith("/playlistItems")) {
      return Promise.resolve(Response.json({
        items: [{ snippet: { title: "General Mechanics - Lecture 01", position: 0 }, contentDetails: { videoId: "abcdefghijk" } }],
      }));
    }
    if (url.pathname.endsWith("/videos")) {
      return Promise.resolve(Response.json({
        items: [{
          id: "abcdefghijk",
          snippet: { title: "Mecânica Geral - Aula 01", publishedAt: "2021-03-02T12:00:00Z", liveBroadcastContent: "none" },
          contentDetails: { duration: "PT52M" },
        }],
      }));
    }
    return Promise.resolve(new Response("missing", { status: 404 }));
  };
}
