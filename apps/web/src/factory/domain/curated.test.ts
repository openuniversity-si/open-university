import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { LIMITS } from "../../catalog/domain/schema/fields.ts";
import { CURATED_DOC_PATH, curatedDocProblem, renderCuratedDoc } from "./curated-doc.ts";
import { parseCurated, type CuratedV1 } from "./curated.ts";

const sha = (digit: string) => digit.repeat(64);
const lesson = { youtubeId: "abcdefghijk", originalTitle: "Mecânica Geral - Aula 01", durationSeconds: 3120, uploadDate: "2021-03-02", position: 1, part: "lectures" as const };
const course = {
  sourcePlaylistId: "PLmecanica01", decision: "include" as const, id: "usp-mecanica-geral", slug: "mecanica-geral",
  title: "Mecânica Geral", originalTitle: "Mecânica Geral - 2021", language: "Portuguese", areaId: "physics", subareaId: "mechanics",
  license: "youtube-standard", rights: "accepted-risk" as const, canonicalUrl: "https://www.youtube.com/playlist?list=PLmecanica01",
  year: 2021, cover: { poster: sha("a") },
  lecturer: { id: "ana-lima", slug: "ana-lima", name: "Ana Lima", monogram: "AL", kind: "person" as const },
  lessons: [lesson],
};

function document(patch: { readonly courses?: CuratedV1["courses"]; readonly titles?: "original" | "translated" } = {}): unknown {
  return {
    format: "curated/v1",
    run: { id: "brasil-2026-10-22", createdAt: "2026-10-22T10:00:00-03:00", adapter: "youtube-playlist@1" },
    institution: {
      id: "usp", slug: "usp", name: "USP", fullName: "Universidade de São Paulo", place: "São Paulo, Brazil",
      kind: "institution", monogram: "USP",
      cover: { poster: sha("b"), og: sha("c"), alt: "Universidade de São Paulo", credit: "Photo: USP", sourceUrl: "https://www.usp.br", license: "CC BY 4.0" },
      homeRow: { after: "iit-madras", visible: true },
    },
    sources: [{ id: "yt-usp", kind: "youtube-channel", title: "USP", url: "https://www.youtube.com/@usp", youtubeChannelId: `UC${"a".repeat(22)}` }],
    courses: patch.courses ?? [course],
    provenance: { titles: patch.titles ?? "original", fetchedAt: "2026-10-22T10:00:00-03:00", counts: { videos: 2, skippedScheduled: 1 } },
  };
}

function names(input: unknown): string[] {
  const parsed = parseCurated(input);
  if (parsed.ok) return [];
  return parsed.issues.map((issue) => issue.name);
}

describe("curated/v1", () => {
  it("accepts a Brazil-shaped run with original titles", () => {
    const parsed = parseCurated(document());
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.courses[0]?.originalTitle).toBe("Mecânica Geral - 2021");
    expect(parsed.value.provenance.counts.skippedScheduled).toBe(1);
  });

  it("fails a translated title by the field name", () => {
    const parsed = parseCurated(document({ titles: "translated" }));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(names(document({ titles: "translated" }))).toContain("provenance.titles");
    expect(parsed.issues.find((issue) => issue.name === "provenance.titles")?.message).toMatch(/provenance\.titles/);
    expect(parsed.issues.find((issue) => issue.name === "provenance.titles")?.message).toMatch(/[Tt]ranslated/);
  });

  it("fails a zero duration by the field name", () => {
    const parsed = parseCurated(document({ courses: [{ ...course, lessons: [{ ...lesson, durationSeconds: 0 }] }] }));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.issues.some((issue) => issue.name === "courses.0.lessons.0.durationSeconds")).toBe(true);
    expect(parsed.issues.find((issue) => issue.name.endsWith("durationSeconds"))?.message).toMatch(/durationSeconds/);
  });

  it("parses an included course that omits its lecturer; the converter holds that course", () => {
    const without = { ...course };
    Reflect.deleteProperty(without, "lecturer");
    expect(names(document({ courses: [without] }))).toEqual([]);
  });

  it("fails a person used as the institution by the field name", () => {
    const input = document() as { institution: { kind: string } };
    input.institution.kind = "person";
    expect(names(input)).toContain("institution.kind");
  });

  it("rejects a home-row position; placement is after", () => {
    const input = document() as { institution: { homeRow: { position?: number } } };
    input.institution.homeRow.position = 1;
    const parsed = parseCurated(input);
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.issues.map((issue) => issue.name)).toContain("institution.homeRow");
    expect(parsed.issues.map((issue) => issue.message).join("\n")).toMatch(/position/);
  });

  it("fails a playlist position of 0 by the field name", () => {
    expect(names(document({ courses: [{ ...course, positions: { from: 0, to: 2 } }] }))).toContain("courses.0.positions.from");
  });

  it("fails an inverted playlist position range by the field name", () => {
    const parsed = parseCurated(document({ courses: [{ ...course, positions: { from: 4, to: 2 } }] }));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.issues.map((issue) => issue.name)).toContain("courses.0.positions");
    expect(parsed.issues.map((issue) => issue.message).join("\n")).toMatch(/positions\.from/);
  });

  it("accepts a playlist position range and treats absence as the whole playlist", () => {
    const ranged = parseCurated(document({ courses: [{ ...course, positions: { from: 2, to: 5 } }] }));
    expect(ranged.ok).toBe(true);
    if (!ranged.ok) return;
    expect(ranged.value.courses[0]?.positions).toEqual({ from: 2, to: 5 });
    const whole = parseCurated(document());
    expect(whole.ok).toBe(true);
    if (!whole.ok) return;
    expect(whole.value.courses[0]?.positions).toBeUndefined();
  });

  it("fails an over-long id by the field name", () => {
    const id = "a".repeat(LIMITS.entityId + 1);
    expect(id).toHaveLength(65);
    const parsed = parseCurated(document({ courses: [{ ...course, id }] }));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    const issue = parsed.issues.find((entry) => entry.name === "courses.0.id");
    expect(issue?.name).toBe("courses.0.id");
    expect(issue?.message).toMatch(/courses\.0\.id/);
  });

  it("keeps the generated doc equal to the schema", () => {
    const generated = renderCuratedDoc();
    expect(curatedDocProblem(generated)).toBeNull();
    expect(curatedDocProblem(null)).toBe(`${CURATED_DOC_PATH} is missing.`);
    expect(generated).toContain(`at most ${String(LIMITS.entityId)} characters`);
    expect(readFileSync(new URL(`../../../${CURATED_DOC_PATH}`, import.meta.url), "utf8")).toBe(generated);
  });
});
