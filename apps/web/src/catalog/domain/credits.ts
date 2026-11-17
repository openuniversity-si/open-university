import { rowTab } from "./home.ts";
import type { PublicCatalog } from "./release.ts";

/**
 * /credits (Daniel, 14/10/2026; Figma 629:4627 / 629:4681): every credited image of the active release on one legal-style
 * page, never inline on catalog pages. Data-driven from the cover credit fields (home_rows.cover, authors.cover).
 */
export type ImageCreditKind = "university" | "author";

export interface ImageCredit {
  readonly subject: string;
  readonly kind: ImageCreditKind;
  /** "Photo: R Boed" (the license suffix of the stored credit is shown in its own column). */
  readonly credit: string;
  readonly sourceUrl: string;
  readonly license: string;
  readonly licenseUrl: string | null;
  readonly coverUrl: string;
}

/** The deed of a Creative Commons license or CC0 named in the cover's `license`; null for anything else. */
export function licenseUrl(license: string): string | null {
  if (/^CC0\b/i.test(license)) return "https://creativecommons.org/publicdomain/zero/1.0/";
  const match = /^CC (BY(?:-(?:NC|SA|ND))*) (\d\.\d)\b/i.exec(license);
  return match ? `https://creativecommons.org/licenses/${(match[1] ?? "").toLowerCase()}/${match[2] ?? ""}/` : null;
}

function strip(credit: string, license: string): string {
  const short = /^(CC0|CC [A-Z-]+ \d\.\d|Public domain)/i.exec(license)?.[1];
  return short ? credit.replace(new RegExp(`,\\s*${short.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i"), "") : credit;
}

export function imageCredits(catalog: PublicCatalog): ImageCredit[] {
  const universities = catalog.home.rows.filter((row) => rowTab(row) === "universities").flatMap((row) => (row.cover
    ? [{ subject: row.title, kind: "university" as const, cover: row.cover }] : []));
  const authors = catalog.authors.flatMap((author) => (author.cover ? [{ subject: author.name, kind: "author" as const, cover: author.cover }] : []));
  return [...universities, ...authors].map(({ subject, kind, cover }) => ({
    subject, kind, credit: strip(cover.credit, cover.license), sourceUrl: cover.sourceUrl, license: cover.license, licenseUrl: licenseUrl(cover.license), coverUrl: cover.url,
  }));
}
