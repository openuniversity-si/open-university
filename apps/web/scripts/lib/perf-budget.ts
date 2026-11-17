/**
 * perf:budget (docs/project/CICLO-DIARIO.md): what the Home makes a browser download in its first two viewports,
 * read from the server HTML only (no browser): stylesheets, scripts, preloaded fonts and the images the markup
 * selects at a viewport width (a <picture> resolves to its matching <source>; image preloads count too).
 */
import { MEDIA_BYTE_BUDGETS } from "../../src/media/domain/budget.ts";
import { EAGER_CARDS_IN_HTML, EAGER_ROWS } from "../../src/ui/Rail/eager.ts";

export const PERF_BUDGET = {
  totalBytes: 1024 * 1024,
  imageBytes: 120 * 1024,
  fontBytes: 60 * 1024,
} as const;

export const PERF_VIEWPORTS = { mobile: 390, desktop: 1440 } as const;

export type ResourceType = "document" | "css" | "js" | "font" | "image";
export interface PlannedResource { readonly url: string; readonly type: ResourceType; readonly hero: boolean }

const attribute = (tag: string, name: string) => new RegExp(`\\s${name}="([^"]*)"`, "i").exec(tag)?.[1]?.replaceAll("&gt;", ">").replaceAll("&lt;", "<").replaceAll("&amp;", "&");
const tags = (html: string, name: string) => html.match(new RegExp(`<${name}\\b(?:[^>"]|"[^"]*")*>`, "gi")) ?? [];

/** Evaluates the media queries the site emits: `(width >= N)`, `(width < N)`, `(min-width: Npx)`, `(max-width: Npx)`, joined by `and`. */
export function mediaMatches(media: string | undefined, width: number): boolean {
  if (!media?.trim() || media.trim() === "all") return true;
  return media.split(/\s+and\s+/i).every((part) => {
    const range = /\(\s*width\s*(>=|>|<=|<)\s*(\d+)px\s*\)/i.exec(part);
    if (range) {
      const [, op, value] = range;
      const limit = Number(value);
      return op === ">=" ? width >= limit : op === ">" ? width > limit : op === "<=" ? width <= limit : width < limit;
    }
    const classic = /\(\s*(min|max)-width\s*:\s*(\d+)px\s*\)/i.exec(part);
    if (classic) return classic[1] === "min" ? width >= Number(classic[2]) : width <= Number(classic[2]);
    throw new Error(`Unsupported media query: ${part}`);
  });
}

/** `Link` response header preloads (Next sends font preloads there) as equivalent <link> tags. */
export function linkHeaderTags(header: string | undefined): string {
  return (header ?? "").split(/,\s*(?=<)/).map((entry) => {
    const url = /^<([^>]+)>/.exec(entry.trim())?.[1];
    if (!url) return "";
    const params = [...entry.matchAll(/;\s*([a-z-]+)(?:="?([^";]*)"?)?/gi)].map(([, key = "", value = ""]) => ` ${key.toLowerCase()}="${value}"`).join("");
    return `<link href="${url}"${params}>`;
  }).join("");
}

/** First URL of a srcset (the site emits single-candidate srcsets). */
/** The markup a scripting browser acts on: every `<noscript>` block removed. */
export const withoutNoscript = (html: string) => html.replace(/<noscript\b[\s\S]*?<\/noscript>/gi, "");
const firstCandidate = (srcset: string | undefined) => srcset?.split(",")[0]?.trim().split(/\s+/)[0];

/**
 * Resources the HTML makes a browser fetch at `width`, resolved against `base`. Hero resources are the images
 * inside the Billboard section and image preloads of the same URLs.
 */
export function plannedResources(markup: string, base: string, width: number): PlannedResource[] {
  // A browser with scripting never fetches what sits inside <noscript> (the lazy posters' fallback <img>), so it is not a planned download.
  const html = withoutNoscript(markup);
  const resolve = (url: string) => new URL(url, base).href;
  const resources = new Map<string, PlannedResource>();
  const add = (url: string | undefined, type: ResourceType, hero = false) => {
    if (!url || url.startsWith("data:")) return;
    const href = resolve(url);
    const known = resources.get(href);
    resources.set(href, { url: href, type, hero: hero || (known?.hero ?? false) });
  };
  for (const tag of tags(html, "link")) {
    const rel = attribute(tag, "rel")?.toLowerCase() ?? "";
    const as = attribute(tag, "as");
    if (rel === "stylesheet") add(attribute(tag, "href"), "css");
    else if (rel === "preload" && as === "font") add(attribute(tag, "href"), "font");
    else if (rel === "preload" && as === "script") add(attribute(tag, "href"), "js");
    else if (rel === "preload" && as === "style") add(attribute(tag, "href"), "css");
    else if (rel === "preload" && as === "image" && mediaMatches(attribute(tag, "media"), width)) add(firstCandidate(attribute(tag, "imagesrcset")) ?? attribute(tag, "href"), "image");
  }
  for (const tag of tags(html, "script")) add(attribute(tag, "src"), "js");
  const billboard = /<section\b[^>]*data-testid="tower-billboard"[^>]*>[\s\S]*?<\/section>/i.exec(html)?.[0] ?? "";
  const heroUrls = new Set<string>();
  const images = (fragment: string) => {
    const selected: string[] = [];
    const pictures = fragment.match(/<picture\b[\s\S]*?<\/picture>/gi) ?? [];
    for (const picture of pictures) {
      const source = tags(picture, "source").find((tag) => mediaMatches(attribute(tag, "media"), width));
      const image = tags(picture, "img")[0] ?? "";
      const url = source ? firstCandidate(attribute(source, "srcset")) : firstCandidate(attribute(image, "srcset")) ?? attribute(image, "src");
      if (url) selected.push(url);
    }
    for (const image of tags(pictures.reduce((rest, picture) => rest.replace(picture, ""), fragment), "img")) {
      const url = firstCandidate(attribute(image, "srcset")) ?? attribute(image, "src");
      if (url) selected.push(url);
    }
    return selected;
  };
  for (const url of images(billboard)) heroUrls.add(resolve(url));
  for (const url of images(html)) add(url, "image", heroUrls.has(resolve(url)));
  // An image preload of a Billboard URL is a hero download even when the viewport shows the other one.
  for (const tag of tags(html, "link")) {
    if (attribute(tag, "rel")?.toLowerCase() !== "preload" || attribute(tag, "as") !== "image") continue;
    const url = firstCandidate(attribute(tag, "imagesrcset")) ?? attribute(tag, "href");
    if (url && billboard.includes(url)) add(url, "image", true);
  }
  return [...resources.values()];
}

export interface MeasuredResource extends PlannedResource { readonly bytes: number }

/** Budget failures for one viewport (empty = pass). */
export function budgetFailures(resources: readonly MeasuredResource[]): string[] {
  const failures: string[] = [];
  const total = resources.reduce((sum, resource) => sum + resource.bytes, 0);
  const kib = (bytes: number) => `${(bytes / 1024).toFixed(1)} KiB`;
  if (total >= PERF_BUDGET.totalBytes) failures.push(`total ${kib(total)} ≥ ${kib(PERF_BUDGET.totalBytes)}`);
  for (const resource of resources) {
    if (resource.type === "image" && resource.bytes >= PERF_BUDGET.imageBytes) failures.push(`image ${kib(resource.bytes)} ≥ ${kib(PERF_BUDGET.imageBytes)}: ${resource.url}`);
    if (resource.type === "font" && resource.bytes >= PERF_BUDGET.fontBytes) failures.push(`font ${kib(resource.bytes)} ≥ ${kib(PERF_BUDGET.fontBytes)}: ${resource.url}`);
  }
  const heroes = resources.filter((resource) => resource.hero);
  if (heroes.length > 1) failures.push(`${String(heroes.length)} hero downloads (the hidden one too): ${heroes.map((hero) => hero.url).join(", ")}`);
  return failures;
}

/**
 * P8: what the Home's HTML asks for before any scrolling, independent of the catalog size. Posters of the first
 * EAGER_ROWS rails carry a `src` (at most EAGER_CARDS_IN_HTML each); every other poster waits for its IntersectionObserver
 * (no `src`, only `data-poster-src`). `<noscript>` fallbacks are ignored: browsers with scripting never fetch them.
 */
export interface HomeImageAudit {
  /** Posters with a `src` in the live markup, per rail in DOM order. */
  readonly eagerPerRow: readonly number[];
  readonly heroPictures: number;
  /** `<link rel=preload as=image>` that is not a hero URL. */
  readonly posterPreloads: number;
}

export function auditHomeImages(html: string): HomeImageAudit {
  const live = withoutNoscript(html);
  const billboard = /<section\b[^>]*data-testid="tower-billboard"[^>]*>[\s\S]*?<\/section>/i.exec(live)?.[0] ?? "";
  const rails = live.split(/(?=<section\b[^>]*data-testid="rail-)/i).slice(1);
  const eagerPerRow = rails.map((rail) => tags(rail.replace(/<\/section>[\s\S]*$/i, ""), "img").filter((image) => (attribute(image, "src") ?? attribute(image, "srcset")) !== undefined).length);
  const posterPreloads = tags(live, "link").filter((tag) => {
    if (attribute(tag, "rel")?.toLowerCase() !== "preload" || attribute(tag, "as") !== "image") return false;
    const url = firstCandidate(attribute(tag, "imagesrcset")) ?? attribute(tag, "href");
    return !url || !billboard.includes(url);
  }).length;
  return { eagerPerRow, heroPictures: (billboard.match(/<picture\b/gi) ?? []).length, posterPreloads };
}

/** Budget failures of the Home's initial HTML (empty = pass): eager posters only where P8 allows them, image estimate < 1 MiB. */
export function homeImageFailures(audit: HomeImageAudit): string[] {
  const failures: string[] = [];
  audit.eagerPerRow.forEach((eager, row) => {
    const allowed = row < EAGER_ROWS ? EAGER_CARDS_IN_HTML : 0;
    if (eager > allowed) failures.push(`rail ${String(row + 1)} has ${String(eager)} posters with a src (allowed ${String(allowed)}; rails from ${String(EAGER_ROWS + 1)} on wait for the viewport)`);
  });
  if (audit.heroPictures > 1) failures.push(`${String(audit.heroPictures)} hero pictures (one expected)`);
  if (audit.posterPreloads > 0) failures.push(`${String(audit.posterPreloads)} poster image preloads (eager posters go in a <picture>, never preloaded)`);
  const estimate = estimatedFirstViewportsImageBytes(audit);
  if (estimate >= PERF_BUDGET.totalBytes) failures.push(`first two viewports estimate ${(estimate / 1024).toFixed(0)} KiB of images ≥ ${String(PERF_BUDGET.totalBytes / 1024)} KiB`);
  return failures;
}

/**
 * Upper bound of the image bytes in the first two viewports, from the media catalog's budgets (src/media/domain/budget.ts):
 * one hero (the larger of its kinds) plus every eager poster at the poster budget. It depends only on EAGER_*, never on
 * how many courses the Home lists. JS, CSS and fonts are measured on the wire by `pnpm perf:budget <url>`.
 */
export function estimatedFirstViewportsImageBytes(audit: HomeImageAudit): number {
  const hero = audit.heroPictures > 0 ? Math.max(MEDIA_BYTE_BUDGETS.hero_mobile_9x16, MEDIA_BYTE_BUDGETS.hero_desktop_16x9) : 0;
  const posters = audit.eagerPerRow.reduce((sum, eager) => sum + eager, 0) + audit.posterPreloads;
  return hero + posters * MEDIA_BYTE_BUDGETS.poster_9x16;
}
