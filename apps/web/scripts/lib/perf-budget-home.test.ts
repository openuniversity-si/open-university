import { createElement } from "react";
import { prerenderToNodeStream } from "react-dom/static";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/identity/client/AuthProvider";
import { snapshotCatalog } from "@/catalog/testing/fake";
import { signedOutHome, type HomeCourse, type HomeRail } from "@/catalog/domain/home";
import { BillboardSelection } from "@/ui/Billboard/BillboardSelection";
import { EAGER_CARDS_IN_HTML, EAGER_ROWS } from "@/ui/Rail/eager";
import { auditHomeImages, estimatedFirstViewportsImageBytes, homeImageFailures, PERF_BUDGET } from "./perf-budget.ts";

const media = "https://media.test/covers";
const image = (id: string, kind: string, width: number, height: number) => ({ url: `${media}/${id}/${kind}/${kind}.0123456789abcdef.webp`, width, height, transform: null });

/**
 * The snapshot's Home (fake.ts) grown to `total` courses, no network: a curated rail with every course first (the widest
 * horizontal case), then rails of three, the shape of the author rows. Every course has a poster and both heroes.
 */
function homeAt(total: number): { featured: HomeCourse; rails: HomeRail[] } {
  const home = signedOutHome(snapshotCatalog);
  const seeds = home.rails.flatMap((rail) => rail.courses);
  const fallback = home.featured;
  if (!fallback || seeds.length === 0) throw new Error("The snapshot needs a featured course and rails.");
  const courses = Array.from({ length: total }, (_, index): HomeCourse => {
    const seed = seeds[index % seeds.length] ?? fallback;
    const id = `course-${String(index + 1)}`;
    return { ...seed, id, slug: `${seed.slug}-${String(index + 1)}`, assets: { poster: image(id, "poster_9x16", 540, 960), heroMobile: image(id, "hero_mobile_9x16", 780, 1240), heroDesktop: image(id, "hero_desktop_16x9", 1920, 810) } };
  });
  const [featured = fallback] = courses;
  const rows = Array.from({ length: Math.ceil(total / 3) }, (_, row) => ({ id: `row-${String(row + 1)}`, title: `Row ${String(row + 1)}`, courses: courses.slice(row * 3, row * 3 + 3) }));
  return { featured, rails: [{ id: "curated", title: "All courses", courses }, ...rows] };
}

async function render(props: { featured: HomeCourse; rails: HomeRail[] }) {
  const slots = { busyOverlay: () => null, signInFeedback: () => null };
  const intro = { text: "Great lectures, in order. Universal, Free & Luxurious.", link: "About Open University", href: "/about" };
  const shelves = props.rails.map((rail) => ({ id: rail.id, title: rail.title, courses: rail.courses, resume: false as const }));
  // eslint-disable-next-line react/no-children-prop -- AuthProvider props require children; the rest-argument overload does not accept AuthProviderSlots.
  const { prelude } = await prerenderToNodeStream(createElement(AuthProvider, { slots, children: createElement(BillboardSelection, { featured: props.featured, shelves, intro }) }));
  let html = "";
  for await (const chunk of prelude) html += String(chunk);
  return html;
}

// Verifies: REQ-web-home-perf-budget
describe("perf:budget on the rendered Home (P8)", () => {
  it.each([24, 50])("keeps %i courses within EAGER_* and under 1 MiB of images in the first two viewports", async (total) => {
    const audit = auditHomeImages(await render(homeAt(total)));
    expect(audit.eagerPerRow).toHaveLength(1 + Math.ceil(total / 3));
    expect(audit.eagerPerRow.slice(0, EAGER_ROWS)).toEqual(Array.from({ length: EAGER_ROWS }, () => EAGER_CARDS_IN_HTML));
    expect(audit.eagerPerRow.slice(EAGER_ROWS).every((eager) => eager === 0)).toBe(true);
    expect(audit.heroPictures).toBe(1);
    expect(homeImageFailures(audit)).toEqual([]);
    expect(estimatedFirstViewportsImageBytes(audit)).toBeLessThan(PERF_BUDGET.totalBytes);
  });

  it("preconnects to the media host of the hero, the LCP element", async () => {
    expect(await render(homeAt(24))).toMatch(/<link rel="preconnect" href="https:\/\/media\.test"\/>/);
  });

  it("does not grow with the catalog", async () => {
    const [small, large] = await Promise.all([24, 50].map(async (total) => estimatedFirstViewportsImageBytes(auditHomeImages(await render(homeAt(total))))));
    expect(large).toBe(small);
  });

  it("fails a poster with a src below the first rail, an extra eager card, a poster preload and a 1 MiB estimate", () => {
    const poster = (src: boolean) => `<picture><img ${src ? 'src="https://media.test/p.webp"' : 'data-poster-src="https://media.test/p.webp"'} alt=""/></picture>`;
    const rail = (id: string, posters: string) => `<section data-testid="rail-${id}"><div>${posters}</div></section>`;
    const html = `<link rel="preload" as="image" href="https://media.test/p.webp"/><section data-testid="tower-billboard"><picture><img src="https://media.test/h.webp" alt=""/></picture></section>`
      + rail("a", poster(true).repeat(EAGER_CARDS_IN_HTML + 1)) + rail("b", poster(true)) + rail("c", `${poster(false)}${poster(true)}<noscript>${poster(true)}</noscript>`);
    const audit = auditHomeImages(html);
    expect(audit).toEqual({ eagerPerRow: [EAGER_CARDS_IN_HTML + 1, 1, 1], heroPictures: 1, posterPreloads: 1 });
    expect(homeImageFailures(audit).map((failure) => failure.split(" ").slice(0, 2).join(" "))).toEqual(["rail 1", "rail 2", "rail 3", "1 poster", "first two"]);
    expect(homeImageFailures({ eagerPerRow: [EAGER_CARDS_IN_HTML, EAGER_CARDS_IN_HTML, 0], heroPictures: 1, posterPreloads: 2 }).at(-1)).toMatch(/^first two viewports estimate/);
  });
});
