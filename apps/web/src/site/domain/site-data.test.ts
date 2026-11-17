import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { groupByCountry } from "../../catalog/domain/countries.ts";
import type { HomeCourse } from "../../catalog/domain/home.ts";
import type { University } from "../../catalog/domain/universities.ts";
import { validateFlagGeometry } from "./flag-geometry.ts";
import { parseSiteData, upcastSiteData, type SiteDataV2 } from "./site-data.ts";

const v2 = JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8")) as SiteDataV2;
const v1 = JSON.parse(readFileSync(new URL("./site-data.v1.json", import.meta.url), "utf8")) as unknown;

const university = (slug: string, place: string): University => {
  const course = { id: slug } as HomeCourse;
  return { slug, name: slug, fullName: slug, place, cover: null, og: null, courses: [course], areaCount: 0, areasNamed: false };
};

describe("site data", () => {
  it("upcasts the frozen v1 fixture onto the v2 manifesto without loss", () => {
    expect(upcastSiteData(v1)).toEqual(v2);
    expect(() => upcastSiteData(v1)).not.toThrow();
    expect(() => upcastSiteData(v2)).not.toThrow();
  });

  it("is idempotent on a v2 document", () => {
    expect(upcastSiteData(v2)).toBe(v2);
  });

  it("keeps a flag for every country and the typed About, Contact and Terms props", () => {
    const data = upcastSiteData(v1);
    for (const id of ["us", "fr", "it", "de", "es", "ch", "gb", "in", "br"]) {
      expect(data.flags[id]).toEqual(v2.flags[id]);
      expect(data.flags[id]?.shapes.length).toBeGreaterThan(0);
    }
    expect(data.flags.us?.shapes.filter((shape) => shape.kind === "path").length).toBeGreaterThan(0);
    expect(data.flags.in?.shapes.some((shape) => shape.kind === "circle" && shape.strokeWidth !== undefined)).toBe(true);
    expect(data.pages.about.metaTitle).toBe(v2.pages.about.metaTitle);
    expect(data.pages.about.cta).toEqual(v2.pages.about.cta);
    expect(data.pages.contact.cardLabel).toBe(v2.pages.contact.cardLabel);
    expect(data.pages.contact.cta).toBe(v2.pages.contact.cta);
    expect(data.pages.terms.sections?.[0]?.h).toBe(v2.pages.terms.sections?.[0]?.h);
    expect(data.legal.publicContactEmails[0]).toBe("contact@openuniversity.si");
  });

  it("groups a new country and accepts its flag from data alone", () => {
    const next = structuredClone(v2) as SiteDataV2 & { countries: SiteDataV2["countries"][number][]; flags: Record<string, SiteDataV2["flags"][string]> };
    next.countries.push({ id: "jp", name: "Japan", rank: 10, placeEndings: ["Japan"] });
    next.flags.jp = {
      width: 300, height: 200,
      shapes: [
        { kind: "rect", x: 0, y: 0, width: 300, height: 200, fill: "#fff" },
        { kind: "circle", cx: 150, cy: 100, r: 60, fill: "#bc002d" },
      ],
    };
    const parsed = parseSiteData(next);
    expect(validateFlagGeometry(parsed.flags.jp ?? next.flags.jp).shapes).toHaveLength(2);
    expect(groupByCountry([university("todai", "Tokyo, Japan")], parsed.countries).map((group) => group.country?.id)).toEqual(["jp"]);
  });

  it("rejects a manifesto string that names an email outside the public list or a forbidden affiliation", () => {
    const emails = (value: SiteDataV2) => JSON.stringify(value).match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) ?? [];
    const leaked = structuredClone(v2) as SiteDataV2 & { homeIntro: { text: string; link: string; href: string }; metadata: { ogImageAlt: string } };
    leaked.homeIntro = { ...v2.homeIntro, text: `${v2.homeIntro.text} secret@gmail.com` };
    expect(emails(leaked).some((email) => !v2.legal.publicContactEmails.includes(email))).toBe(true);
    const affiliated = structuredClone(v2) as SiteDataV2 & { metadata: { ogImageAlt: string } };
    affiliated.metadata = { ...v2.metadata, ogImageAlt: `${v2.metadata.ogImageAlt} We are a partner university.` };
    expect(JSON.stringify(affiliated)).toMatch(/partner/i);
    expect(JSON.stringify(v2)).not.toMatch(/partner/i);
  });
});
