import { describe, expect, it } from "vitest";
import { releaseTextEntries, TEXT_ENTITY_KINDS, TEXT_FIELDS, textField, textFieldNames, textIssues } from "./fields.ts";

describe("catalog text fields", () => {
  it("lists the fields the 0005 CHECK allows, with the plan's review set (10 course fields + lesson displayTitle)", () => {
    expect(TEXT_ENTITY_KINDS).toEqual(["course", "lesson", "author"]);
    expect(textFieldNames("course").filter((name) => TEXT_FIELDS.course[name as keyof typeof TEXT_FIELDS.course].review)).toHaveLength(10);
    expect(textFieldNames("lesson").filter((name) => TEXT_FIELDS.lesson[name as keyof typeof TEXT_FIELDS.lesson].review)).toEqual(["displayTitle"]);
    expect(textField("course", "displayTitle")?.maxChars).toBe(40);
    expect(textField("course", "nope")).toBeUndefined();
    expect(textField("nope", "displayTitle")).toBeUndefined();
  });

  it("reports every issue of a text at once, by rule, without echoing the text", () => {
    expect(textIssues("course", "level", "Introductory")).toEqual([]);
    const issues = textIssues("course", "level", `${"x".repeat(20)} 🙂`);
    expect(issues.map((issue) => issue.rule)).toEqual(["texts.limit", "texts.charset"]);
    expect(issues.every((issue) => !issue.message.includes("xxxx"))).toBe(true);
    expect(textIssues("course", "level", "   ").map((issue) => issue.rule)).toEqual(["texts.empty"]);
    expect(textIssues("course", "bogus", "x")).toEqual([{ rule: "texts.field", message: "course has no text field bogus." }]);
  });

  it("pins release presence without adding a text field", () => {
    expect(Object.keys(TEXT_FIELDS.lesson)).toEqual(["displayTitle", "about"]);
    expect(Object.keys(TEXT_FIELDS.course)).toEqual([
      "displayTitle", "shelfTitle", "subtitle", "billboardDescription", "billboardDescriptionMobile",
      "description", "descriptionMobile", "about", "level", "format",
    ]);
    expect(TEXT_FIELDS.lesson.displayTitle.release).toBe("required");
    expect(TEXT_FIELDS.lesson.about.release).toBe("nullable");
    expect(TEXT_FIELDS.course.about.release).toBe("nullable");
    expect(TEXT_FIELDS.author.bio.release).toBe("off");
    for (const name of Object.keys(TEXT_FIELDS.course)) {
      if (name === "about") continue;
      expect(TEXT_FIELDS.course[name as keyof typeof TEXT_FIELDS.course].release).toBe("required");
    }
    expect(releaseTextEntries(
      { displayTitle: { release: "required" }, about: { release: "nullable" }, summary: { release: "optional" } },
      (name) => (name === "displayTitle" ? "Title" : null),
    )).toEqual({ displayTitle: "Title", about: null });
  });

  it("counts characters, not UTF-16 units", () => {
    expect(textIssues("course", "level", "é".repeat(16))).toEqual([]);
  });
});
