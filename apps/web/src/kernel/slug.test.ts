import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseSiteData } from "../site/domain/site-data.ts";
import { slugify } from "./slug.ts";
const pages = parseSiteData(JSON.parse(readFileSync(new URL("../../content/site/site-data.v2.json", import.meta.url), "utf8"))).pages;
const PRIVACY_PAGE = pages.privacy, TERMS_PAGE = pages.terms, CONTACT_PAGE = pages.contact;

describe("kernel slugify", () => {
  it("preserves all current legal anchors", () => {
    const headings = [PRIVACY_PAGE, TERMS_PAGE, CONTACT_PAGE].flatMap((page) => (page.sections ?? []).map((section) => section.h));
    expect(headings).toHaveLength(21);
    const old = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    for (const heading of headings) expect(slugify(heading, { fallback: "" })).toBe(old(heading));
  });
  it("preserves import suggestions and their length/fallback policy", () => {
    const options = { max: 160, fallback: "lesson" };
    expect(slugify("Ça va, Éden & Égypte!", options)).toBe("ca-va-eden-egypte");
    expect(slugify("word ".repeat(60), { max: 20, fallback: "lesson" })).toBe("word-word-word-word");
    expect(slugify("!!!", options)).toBe("lesson");
    expect(slugify("a".repeat(200), options)).toHaveLength(160);
    expect(slugify("a long title", { max: 2, fallback: "lesson" })).toBe("a");
    expect(slugify("!!!", { fallback: "" })).toBe("");
    expect(slugify("a".repeat(200))).toHaveLength(200);
  });
});
