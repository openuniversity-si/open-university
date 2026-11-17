import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { REQUIRED_COVERS } from "../cover-source.ts";
import { figurePresenceAnswer, lessonVideoCheckAnswer, showcaseRowAnswer, sitePageTextAnswer } from "./publish-answers.ts";

describe("answers publish receives", () => {
  it("names the lesson on a video check that no longer serves", () => {
    expect(lessonVideoCheckAnswer([{ lessonId: "lesson-1", status: "embed-disabled" }])).toEqual([
      { rule: "videos.fresh", entity: "lesson:lesson-1", message: "The fresh oEmbed check says embed-disabled.", owner: "lesson" },
    ]);
    expect(lessonVideoCheckAnswer([])).toEqual([]);
  });

  it("names the figure when a required picture is missing", () => {
    const present = new Set<string>(REQUIRED_COVERS.slice(1));
    expect(figurePresenceAnswer("course-9", present)).toEqual([
      { rule: "covers.active", entity: "course:course-9", message: `No active ${REQUIRED_COVERS[0]} cover.`, owner: "figure" },
    ]);
    expect(figurePresenceAnswer("course-9", new Set(REQUIRED_COVERS))).toEqual([]);
  });

  it("names the showcase, and an orphan marked on purpose is an acceptance", () => {
    expect(showcaseRowAnswer("course-9", false, false)).toEqual([
      { rule: "home.row", entity: "course:course-9", message: "The course is in no visible Home row (pass allowOrphan to publish it anyway).", owner: "showcase" },
    ]);
    expect(showcaseRowAnswer("course-9", true, false)).toEqual([]);
    expect(showcaseRowAnswer("course-9", false, true)).toEqual([]);
  });

  it("names the site when the page cannot draw a character, and ignores slot length", () => {
    expect(sitePageTextAnswer([{ kind: "course", id: "course-9", field: "level", text: "Intro 🙂" }])).toEqual([
      { rule: "texts.charset", entity: "course:course-9", message: "course.level uses characters outside the Inter subset: U+1F642.", owner: "site" },
    ]);
    expect(sitePageTextAnswer([{ kind: "course", id: "course-9", field: "level", text: "x".repeat(40) }])).toEqual([]);
    const answer = readFileSync(new URL("./publish-answers.ts", import.meta.url), "utf8");
    const page = readFileSync(new URL("../../../site/domain/page-characters.ts", import.meta.url), "utf8");
    const offer = readFileSync(new URL("../fields.ts", import.meta.url), "utf8");
    expect(answer).toContain("undrawablePageText");
    expect(answer).not.toContain("textIssues");
    expect(page).not.toContain("maxChars");
    expect(offer).toContain("maxChars");
  });
});
