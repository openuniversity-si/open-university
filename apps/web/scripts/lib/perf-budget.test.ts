import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { budgetFailures, linkHeaderTags, mediaMatches, plannedResources } from "./perf-budget.ts";

const base = "https://tower.test/";
const html = `
  <link rel="stylesheet" href="/_next/a.css"/><script src="/_next/a.js" async=""></script>
  <section data-testid="tower-billboard"><div><picture>
    <source media="(width &gt;= 1024px)" srcSet="https://media.test/covers/course-1/hero_desktop_16x9/d.webp" width="1920" height="810"/>
    <img src="https://media.test/covers/course-1/hero_mobile_9x16/m.webp" width="780" height="1240" alt=""/>
  </picture></div></section>
  <img loading="lazy" src="https://media.test/covers/course-1/poster_9x16/p.webp" alt=""/>`;

describe("perf:budget planning", () => {
  it("evaluates the site's media query forms", () => {
    expect(mediaMatches("(width >= 1024px)", 1440)).toBe(true);
    expect(mediaMatches("(width >= 1024px)", 390)).toBe(false);
    expect(mediaMatches("(min-width: 768px) and (max-width: 1023px)", 800)).toBe(true);
    expect(mediaMatches(undefined, 390)).toBe(true);
  });

  it("downloads only the hero <source> that matches the viewport", () => {
    const mobile = plannedResources(html, base, 390);
    const desktop = plannedResources(html, base, 1440);
    expect(mobile.filter((resource) => resource.hero).map((resource) => resource.url)).toEqual(["https://media.test/covers/course-1/hero_mobile_9x16/m.webp"]);
    expect(desktop.filter((resource) => resource.hero).map((resource) => resource.url)).toEqual(["https://media.test/covers/course-1/hero_desktop_16x9/d.webp"]);
    expect(mobile.map((resource) => resource.type).sort()).toEqual(["css", "image", "image", "js"]);
  });

  it("ignores <noscript> fallback images: a scripting browser never fetches them", () => {
    const lazy = `<section data-testid="rail-a"><img data-poster-src="https://media.test/covers/course-2/poster_9x16/p.webp" alt=""/>
      <noscript><img src="https://media.test/covers/course-2/poster_9x16/p.webp" alt=""/></noscript>
      <NOSCRIPT><picture><img srcset="https://media.test/covers/course-3/poster_9x16/q.webp 540w" alt=""/></picture></NOSCRIPT></section>
      <img src="https://media.test/covers/course-4/poster_9x16/r.webp" alt=""/>`;
    const urls = plannedResources(lazy, base, 390).map((resource) => resource.url);
    expect(urls).toEqual(["https://media.test/covers/course-4/poster_9x16/r.webp"]);
  });

  it("counts Link-header font preloads and flags a preloaded hidden hero", () => {
    const tags = linkHeaderTags('</_next/static/media/Inter.p.woff2>; rel=preload; as="font"; crossorigin=""; type="font/woff2"');
    expect(plannedResources(tags, base, 390)).toEqual([{ url: "https://tower.test/_next/static/media/Inter.p.woff2", type: "font", hero: false }]);
    const preloaded = `<link rel="preload" as="image" href="https://media.test/covers/course-1/hero_desktop_16x9/d.webp"/>${html}`;
    const heroes = plannedResources(preloaded, base, 390).map((resource) => ({ ...resource, bytes: 10 }));
    expect(budgetFailures(heroes)).toEqual([expect.stringMatching(/^2 hero downloads/)]);
  });

  it("fails over the total, image and font budgets", () => {
    const failures = budgetFailures([
      { url: "a", type: "image", hero: false, bytes: 600 * 1024 },
      { url: "b", type: "font", hero: false, bytes: 61 * 1024 },
      { url: "c", type: "js", hero: false, bytes: 400 * 1024 },
    ]);
    expect(failures.map((failure) => failure.split(" ")[0])).toEqual(["total", "image", "font"]);
  });
});

describe("perf guards", () => {
  it("documents every unoptimized next/image as pre-optimized at the origin", () => {
    const src = fileURLToPath(new URL("../../src", import.meta.url));
    const files = readdirSync(src, { recursive: true, withFileTypes: true }).filter((entry) => entry.isFile() && entry.name.endsWith(".tsx") && !entry.name.includes(".test."));
    const undocumented = files.flatMap((entry) => {
      const file = path.join(entry.parentPath, entry.name);
      const lines = readFileSync(file, "utf8").split("\n");
      return lines.flatMap((line, index) => /\bunoptimized\b/.test(line) && !`${lines[index - 1] ?? ""}${line}`.includes("// perf: pre-optimized at the origin") ? [`${path.relative(src, file)}:${String(index + 1)}`] : []);
    });
    expect(undocumented).toEqual([]);
  });
});
