import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { prerenderToNodeStream } from "react-dom/static";
import { describe, expect, it } from "vitest";
import { CourseCard } from "./CourseCard.tsx";

const course = { id: "course-1", slug: "genesis", title: "Genesis", assets: { poster: null } } as unknown as Parameters<typeof CourseCard>[0]["course"];

describe("CourseCard CoverPlayButton (504:53064)", () => {
  it("shows a decorative play only when selected", () => {
    const selected = renderToStaticMarkup(createElement(CourseCard, { course, selected: true }));
    expect(selected).toMatch(/<span[^>]*aria-hidden="true"[^>]*data-testid="tower-cover-play"/);
    expect(renderToStaticMarkup(createElement(CourseCard, { course }))).not.toContain("tower-cover-play");
  });
});

describe("CourseCard posters (P8)", () => {
  const withPoster = { ...course, assets: { poster: { url: "https://media.example/covers/course-1/poster.webp", width: 540, height: 960 } } } as typeof course;
  async function html(eager: boolean) {
    const { prelude } = await prerenderToNodeStream(createElement(CourseCard, { course: withPoster, eager }));
    let out = "";
    for await (const chunk of prelude) out += String(chunk);
    return out;
  }
  it("loads an eager poster at once, never preloaded", async () => {
    const out = await html(true);
    expect(out).toMatch(/<picture><img[^>]* src="https:\/\/media\.example\/covers\/course-1\/poster\.webp"[^>]*loading="eager"[^>]*fetchPriority="low"/);
    expect(out).not.toContain("preload");
  });
  it("leaves an on-demand poster without src, with a noscript fallback and the same box", async () => {
    const out = await html(false);
    const [live] = out.split("<noscript>");
    expect(live).toMatch(/<picture><img[^>]* width="540" height="960" loading="lazy" decoding="async" fetchPriority="low" alt="" data-poster-src=/);
    expect(live).not.toMatch(/ src=/);
    expect(out).toMatch(/<noscript><picture><img[^>]* loading="lazy"[^>]* src="https:\/\/media\.example\/covers\/course-1\/poster\.webp"/);
    expect(out).not.toContain("preload");
  });
});
