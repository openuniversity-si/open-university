import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { releaseFixture } from "../../../test/fixtures/release.ts";
import { CreditsList } from "../../ui/CreditsList/CreditsList.tsx";
import { parseSiteData } from "../../site/domain/site-data.ts";
const FOOTER_LINKS = parseSiteData(JSON.parse(readFileSync(new URL("../../../content/site/site-data.v2.json", import.meta.url), "utf8"))).footer.links;
import { imageCredits, licenseUrl } from "./credits.ts";

// Daniel, 14/10/2026: cover credits live on /credits only, never inline on a catalog page.
const cover = (id: string, license: string) => ({ url: `https://media.openuniversity.si/covers/${id}.webp`, width: 1080, height: 1920, sha256: "b".repeat(64), alt: id, credit: `Photo: ${id}, ${license}`, sourceUrl: `https://commons.wikimedia.org/${id}`, license, note: "Cropped" });

function credited() {
  const release = releaseFixture();
  release.home.rows.push({ id: "mit", kind: "curated", title: "MIT", courseIds: ["course-2"], cover: cover("mit", "CC BY 2.0") });
  release.home.rows.push({ id: "cmu", kind: "curated", title: "Carnegie Mellon", courseIds: ["course-2"], cover: cover("cmu", "CC0") });
  release.authors = release.authors.map((author) => ({ ...author, cover: cover(author.id, "CC BY-SA 3.0") }));
  return release;
}

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => { const path = join(dir, name); return statSync(path).isDirectory() ? files(path) : [path]; });
}

describe("image credits", () => {
  it("lists every credited cover of the release, with source and license links", () => {
    const release = credited();
    const credits = imageCredits(release);
    const covers = [...release.home.rows.flatMap((row) => (row.cover ? [row.cover.url] : [])), ...release.authors.flatMap((author) => (author.cover ? [author.cover.url] : []))];
    expect(credits.map((entry) => entry.coverUrl).sort()).toEqual(covers.sort());
    expect(credits[0]).toMatchObject({ subject: "MIT", kind: "university", credit: "Photo: mit", licenseUrl: "https://creativecommons.org/licenses/by/2.0/" });
    const html = renderToStaticMarkup(CreditsList({ credits }));
    expect(html).toContain("University cover");
    expect(html).toContain("Author cover");
    for (const url of covers) expect(html).toContain(`data-cover="${url}"`);
    expect(html).toContain('href="https://creativecommons.org/publicdomain/zero/1.0/"');
    expect(licenseUrl("Not stated by the source")).toBeNull();
    expect(FOOTER_LINKS.map((link) => link.label)).toEqual(["Privacy", "Terms", "Contact", "Credits"]);
  });

  it("never renders credits inline on a catalog page", () => {
    const app = join(import.meta.dirname, "../..", "app");
    const pages = files(app).filter((path) => /page\.tsx$/.test(path) && !path.includes(join("app", "credits")));
    expect(pages.length).toBeGreaterThan(5);
    for (const path of pages) {
      const source = readFileSync(path, "utf8");
      expect(source, path).not.toMatch(/CreditsList|imageCredits|AuthorCredits|\.credit\b|cover-credits/);
    }
  });
});
