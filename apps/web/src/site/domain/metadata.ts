import { resolveCover } from "../../catalog/domain/cover-resolve.ts";
import { authorsDescription, authorsTitle, courseByAuthorTemplate, fill, metaDot, universitiesDescription, universitiesTitle } from "./reader-copy.ts";
import { PRODUCTION_ORIGIN } from "./origin.ts";
import { installedSiteData } from "./site-data.ts";
import type { PublicStaticRoute } from "./route-registry.ts";

/** Single source of the site metadata (ADR-13): root defaults, static pages, courses and lessons. */
const meta = () => installedSiteData().metadata;
const pages = () => installedSiteData().pages;
export const MAX_TITLE_LENGTH = 70;
export const MAX_DESCRIPTION_LENGTH = 160;
/** Brand card (`public/brand/og.jpg`): the share image of every page without art of its own. */
export function ogImage() {
  return { url: "/brand/og.jpg", width: 1200, height: 630, alt: meta().ogImageAlt } as const;
}

export interface ShareImage { readonly url: string; readonly width: number; readonly height: number; readonly alt: string }

/** Root defaults. The route maps this onto Next; the domain does not import that type. */
export interface SiteDefaults {
  readonly metadataBase: URL;
  readonly title: { readonly default: string; readonly template: string };
  readonly description: string;
  readonly applicationName: string;
  readonly icons: {
    readonly icon: { readonly url: string; readonly type?: string; readonly sizes: string }[];
    readonly apple: { readonly url: string; readonly sizes: string }[];
  };
}

/** One public page: title, description, canonical and the share image. */
export interface PageMeta {
  readonly title?: PageTitle;
  readonly description?: string;
  readonly alternates?: { readonly canonical: string };
  readonly openGraph?: {
    readonly type: "website";
    readonly siteName: string;
    readonly locale: "en_US";
    readonly url: string;
    readonly title: string;
    readonly description: string;
    readonly images: ShareImage[];
  };
  readonly twitter?: {
    readonly card: "summary_large_image";
    readonly title: string;
    readonly description: string;
    readonly images: ShareImage[];
  };
}
interface ArtLike { readonly kind?: string; readonly variant?: string; readonly url: string; readonly width: number; readonly height: number }

/** The course's own share image, or the brand card. */
export function courseShareImage(assets: readonly ArtLike[] | undefined, alt: string): ShareImage {
  const asset = resolveCover({ course: assets?.map((entry) => ({ ...entry, kind: entry.kind ?? "" })), coverFrom: "own", courseId: "course" }, { target: "course", presentation: "share" });
  return asset ? { url: asset.url, width: asset.width, height: asset.height, alt } : ogImage();
}

type Art = Omit<ArtLike, "kind" | "variant">;
/** A university's share image: its 1200×630 preview, else its cover, else the brand card. */
export function coverShareImage(cover: (Art & { readonly og?: Art | undefined }) | null | undefined, alt: string): ShareImage {
  const institution = cover ? [{ ...cover, kind: "poster_9x16" }, ...(cover.og ? [{ ...cover.og, kind: "og" }] : [])] : [];
  const art = resolveCover({ institution }, { target: "institution", presentation: "share" });
  return art ? { url: art.url, width: art.width, height: art.height, alt } : ogImage();
}

/** Root layout defaults; every page adds its own canonical, Open Graph and Twitter card through `pageMetadata`. */
export function siteMetadata(): SiteDefaults {
  return {
  metadataBase: new URL(PRODUCTION_ORIGIN),
  title: { default: meta().defaultTitle, template: meta().titleTemplate },
  description: meta().defaultDescription,
  applicationName: meta().siteName,
  icons: {
    icon: [{ url: "/icons/icon-192.png", type: "image/png", sizes: "192x192" }, { url: "/favicon.ico", sizes: "16x16 32x32 48x48" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
  };
}

export type PageTitle = string | { readonly absolute: string };

/** The `<title>` a page ends up with once the root template applies. */
export function resolvedTitle(title: PageTitle | undefined): string {
  if (title === undefined) return meta().defaultTitle;
  return typeof title === "string" ? meta().titleTemplate.replace("%s", title) : title.absolute;
}

/** First candidate that fits 70 characters, with the template or else without it; the last one is used as is. */
function fittedTitle(candidates: readonly string[]): PageTitle {
  for (const candidate of candidates) {
    if (resolvedTitle(candidate).length <= MAX_TITLE_LENGTH) return candidate;
    if (candidate.length <= MAX_TITLE_LENGTH) return { absolute: candidate };
  }
  return { absolute: candidates.at(-1) ?? meta().defaultTitle };
}

/** Whole sentences up to 160 characters; when they say too little, whole words and an ellipsis. */
export function clippedDescription(text: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= MAX_DESCRIPTION_LENGTH) return clean;
  let sentences = "";
  for (const sentence of clean.match(/[^.!?]+[.!?]+(?=\s|$)/g) ?? []) {
    const next = `${sentences} ${sentence.trim()}`.trim();
    if (next.length > MAX_DESCRIPTION_LENGTH) break;
    sentences = next;
  }
  if (sentences.length >= 100) return sentences;
  const words = clean.slice(0, MAX_DESCRIPTION_LENGTH).replace(/\s+\S*$/, "");
  return `${words.replace(/[\s,;:.—–-]+$/, "")}…`;
}

/** Description, canonical, Open Graph and Twitter card for one public path (relative to `metadataBase`). */
export function pageMetadata(path: string, description: string, title?: PageTitle, image: ShareImage = ogImage()): PageMeta {
  const fullTitle = resolvedTitle(title);
  return {
    ...(title === undefined ? {} : { title }),
    description,
    alternates: { canonical: path },
    openGraph: { type: "website", siteName: meta().siteName, locale: "en_US", url: path, title: fullTitle, description, images: [image] },
    twitter: { card: "summary_large_image", title: fullTitle, description, images: [image] },
  };
}

/** Title (before the template) and description of every static page; a route missing here fails typecheck. */
function staticPages(): Readonly<Record<PublicStaticRoute, { readonly title?: string; readonly description: string }>> {
  const copy = pages();
  return {
    "/": { description: meta().defaultDescription },
    "/universities": { title: universitiesTitle, description: universitiesDescription },
    "/authors": { title: authorsTitle, description: authorsDescription },
    "/privacy": copy.privacy,
    "/terms": copy.terms,
    "/credits": copy.credits,
    "/contact": copy.contact,
    "/about": { title: copy.about.metaTitle, description: copy.about.description },
  };
}

export function staticPageMetadata(route: PublicStaticRoute): PageMeta {
  const page = staticPages()[route];
  return pageMetadata(route, page.description, page.title);
}

export interface CourseMetadataInput {
  readonly slug: string;
  readonly displayTitle: string;
  readonly description: string;
  readonly authorName: string;
  readonly art: readonly { readonly kind: string; readonly variant: string; readonly url: string; readonly width: number; readonly height: number }[];
}

export interface LessonMetadataInput {
  readonly course: CourseMetadataInput;
  readonly slug: string;
  readonly displayTitle: string;
  readonly about: string | null;
}

/** `/c/<course>`: "<course> by <author>". A null input (unknown slug, missing author) gets no page metadata. */
export function courseMetadata(input: CourseMetadataInput | null): PageMeta {
  if (!input) return {};
  return pageMetadata(`/c/${input.slug}`, clippedDescription(input.description), fittedTitle([fill(courseByAuthorTemplate, { title: input.displayTitle, author: input.authorName }), input.displayTitle]),
    courseShareImage(input.art, input.displayTitle));
}

/** `/c/<course>/<lesson>`: "<lesson> · <course>"; the lesson About, or the course description when it has none. */
export function lessonMetadata(input: LessonMetadataInput | null): PageMeta {
  if (!input) return {};
  return pageMetadata(`/c/${input.course.slug}/${input.slug}`, clippedDescription(input.about ?? input.course.description),
    fittedTitle([`${input.displayTitle}${metaDot}${input.course.displayTitle}`, input.displayTitle]), courseShareImage(input.course.art, input.course.displayTitle));
}
