import { z } from "zod";
import { invalid } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { validateFlagGeometry, type FlagGeometry } from "./flag-geometry.ts";
import type { LegalPageContent } from "./legal.ts";
import { EXTENT } from "../../kernel/extent.ts";

export interface CountrySpec {
  readonly id: string;
  readonly name: string;
  readonly rank: number;
  readonly placeEndings: readonly string[];
}
export interface SiteDataV2 {
  readonly schemaVersion: 2;
  readonly metadata: { readonly siteName: string; readonly defaultTitle: string; readonly titleTemplate: string; readonly defaultDescription: string; readonly ogImageAlt: string };
  readonly legal: { readonly updated: string; readonly publicContactEmails: readonly [string, ...string[]] };
  readonly homeIntro: { readonly text: string; readonly link: string; readonly href: string };
  readonly pages: {
    readonly about: LegalPageContent & { readonly metaTitle: string; readonly cta: { readonly label: string; readonly href: string } };
    readonly privacy: LegalPageContent;
    readonly terms: LegalPageContent;
    readonly contact: LegalPageContent & { readonly cardLabel: string; readonly cta: string };
    readonly credits: LegalPageContent;
  };
  readonly footer: { readonly links: readonly { readonly label: string; readonly href: string }[] };
  readonly topNav: { readonly back: { readonly home: string; readonly course: string } };
  readonly countries: readonly CountrySpec[];
  readonly flags: Readonly<Record<string, FlagGeometry>>;
}

const page = z.object({
  slug: z.string().min(EXTENT.one), kicker: z.string().min(EXTENT.one), title: z.string().min(EXTENT.one), description: z.string().min(EXTENT.one).max(LIMITS.pageDescription), lead: z.string(),
  body: z.array(z.string()).optional(), wink: z.string().optional(), closing: z.string().optional(),
  sections: z.array(z.object({ h: z.string().min(EXTENT.one), p: z.array(z.string()).optional(), ul: z.array(z.string()).optional(), after: z.array(z.string()).optional() })).optional(),
}).strict();
const shape = z.object({
  kind: z.enum(["rect", "path", "circle"]), fill: z.string().optional(), stroke: z.string().optional(), strokeWidth: z.number().optional(),
  x: z.number().optional(), y: z.number().optional(), width: z.number().optional(), height: z.number().optional(),
  d: z.string().optional(), cx: z.number().optional(), cy: z.number().optional(), r: z.number().optional(),
}).strict();
const flag = z.object({ width: z.number(), height: z.number(), shapes: z.array(shape) }).strict();
const country = z.object({ id: z.string().regex(/^[a-z]{2}$/), name: z.string().min(EXTENT.one), rank: z.number().int(), placeEndings: z.array(z.string().min(EXTENT.one)).min(EXTENT.one) }).strict();
const siteSchema = z.object({
  schemaVersion: z.literal(2),
  metadata: z.object({ siteName: z.string().min(EXTENT.one), defaultTitle: z.string().min(EXTENT.one), titleTemplate: z.string().min(EXTENT.one), defaultDescription: z.string().min(EXTENT.one).max(LIMITS.pageDescription), ogImageAlt: z.string().min(EXTENT.one) }).strict(),
  legal: z.object({ updated: z.string().regex(/^\d{1,2} [A-Z][a-z]+ \d{4}$/), publicContactEmails: z.tuple([z.email()], z.email()) }).strict(),
  homeIntro: z.object({ text: z.string().min(EXTENT.one), link: z.string().min(EXTENT.one), href: z.string().startsWith("/") }).strict(),
  pages: z.object({
    about: page.extend({ metaTitle: z.string().min(EXTENT.one), cta: z.object({ label: z.string().min(EXTENT.one), href: z.string().startsWith("/") }).strict() }).strict(),
    privacy: page, terms: page,
    contact: page.extend({ cardLabel: z.string().min(EXTENT.one), cta: z.string().min(EXTENT.one) }).strict(),
    credits: page,
  }).strict(),
  footer: z.object({ links: z.array(z.object({ label: z.string().min(EXTENT.one), href: z.string().startsWith("/") }).strict()).min(EXTENT.one) }).strict(),
  topNav: z.object({ back: z.object({ home: z.string().min(EXTENT.one), course: z.string().min(EXTENT.one) }).strict() }).strict(),
  countries: z.array(country).min(EXTENT.one),
  flags: z.record(z.string(), flag),
}).strict();

function firstIssue(error: z.ZodError): string {
  const issue = error.issues[0];
  return issue ? issue.path.join(".") || "(root)" : "(root)";
}

/** v1 is the literal export bag frozen from the previous constants. */
export interface SiteDataV1 {
  readonly schemaVersion?: 1;
  readonly PRIVACY_PAGE: unknown; readonly TERMS_PAGE: unknown; readonly CONTACT_PAGE: unknown; readonly CREDITS_PAGE: unknown; readonly ABOUT_PAGE: unknown;
  readonly HOME_INTRO: unknown; readonly LEGAL_UPDATED: unknown; readonly PUBLIC_CONTACT_EMAILS: unknown; readonly FOOTER_LINKS: unknown;
  readonly COUNTRIES: unknown; readonly flags: unknown;
  readonly SITE_NAME: unknown; readonly DEFAULT_TITLE: unknown; readonly TITLE_TEMPLATE: unknown; readonly DEFAULT_DESCRIPTION: unknown; readonly OG_IMAGE_ALT: unknown;
  readonly TOP_NAV_BACK_HOME: unknown; readonly TOP_NAV_BACK_COURSE: unknown;
}

function fromV1(raw: SiteDataV1): unknown {
  return {
    schemaVersion: 2,
    metadata: { siteName: raw.SITE_NAME, defaultTitle: raw.DEFAULT_TITLE, titleTemplate: raw.TITLE_TEMPLATE, defaultDescription: raw.DEFAULT_DESCRIPTION, ogImageAlt: raw.OG_IMAGE_ALT },
    legal: { updated: raw.LEGAL_UPDATED, publicContactEmails: raw.PUBLIC_CONTACT_EMAILS },
    homeIntro: raw.HOME_INTRO,
    pages: { about: raw.ABOUT_PAGE, privacy: raw.PRIVACY_PAGE, terms: raw.TERMS_PAGE, contact: raw.CONTACT_PAGE, credits: raw.CREDITS_PAGE },
    footer: { links: raw.FOOTER_LINKS },
    topNav: { back: { home: raw.TOP_NAV_BACK_HOME, course: raw.TOP_NAV_BACK_COURSE } },
    countries: raw.COUNTRIES,
    flags: raw.flags,
  };
}

export function parseSiteData(raw: unknown): SiteDataV2 {
  const parsed = siteSchema.safeParse(raw);
  if (!parsed.success) throw invalid(`Invalid site data at ${firstIssue(parsed.error)}.`);
  const data = parsed.data as SiteDataV2;
  const ranks = [...data.countries.map((country) => country.rank)].sort((a, b) => a - b);
  if (ranks.some((rank, index) => rank !== index + 1)) throw invalid("Country ranks must be 1..n without ties.");
  if (new Set(data.countries.map((country) => country.id)).size !== data.countries.length) throw invalid("Country ids must be unique.");
  for (const country of data.countries) {
    const flag = data.flags[country.id];
    if (!flag) throw invalid(`Country ${country.id} has no flag.`);
    validateFlagGeometry(flag, `flags.${country.id}`);
  }
  return data;
}

/** Accepts the frozen v1 bag or a v2 document. Valid input never throws; the first bad field is an AppError. */
export function upcastSiteData(raw: unknown): SiteDataV2 {
  if (raw !== null && typeof raw === "object" && (raw as { schemaVersion?: unknown }).schemaVersion === 2) {
    parseSiteData(raw);
    return raw as SiteDataV2;
  }
  return parseSiteData(fromV1(raw as SiteDataV1));
}

let installed: SiteDataV2 | undefined;
export function installSiteData(data: SiteDataV2): void { installed = data; }
export function installedSiteData(): SiteDataV2 {
  if (!installed) throw invalid("Site data is not installed.");
  return installed;
}
