import { editionVariantSchema, type EditionVariant } from "./schema/fields.ts";

// D-034: an offering is (courseId, year, variant). The variant is optional and, when present, a kind plus a short
// label. Two editions of one year with no distinct variant are the same offering. The season column is not a variant.

/** The variant stored in `variant_kind` and `variant_label`, or null when both are absent. */
export function columnsToVariant(kind: string | null | undefined, label: string | null | undefined): EditionVariant | null {
  if (kind == null && label == null) return null;
  const parsed = editionVariantSchema.safeParse({ kind, label });
  return parsed.success ? parsed.data : null;
}

/** Identity of one offering's year and variant. A missing variant is its own value, so two of them collide. */
export function offeringKey(year: number, variant: { readonly kind: string; readonly label: string } | null | undefined): string {
  return `${String(year)}\n${variant?.kind ?? ""}\n${variant?.label ?? ""}`;
}

export interface EditionOffering {
  readonly id: string;
  readonly year: number | null;
  readonly variant?: { readonly kind: string; readonly label: string } | null;
}

/** Groups of more than one edition that share a year and do not differ by variant. A null year is not an offering yet. */
export function indistinctEditions(editions: readonly EditionOffering[]): { readonly year: number; readonly ids: readonly string[] }[] {
  const groups = new Map<string, { year: number; ids: string[] }>();
  for (const edition of editions) {
    if (edition.year === null) continue;
    const key = offeringKey(edition.year, edition.variant);
    const group = groups.get(key);
    if (group) group.ids.push(edition.id);
    else groups.set(key, { year: edition.year, ids: [edition.id] });
  }
  return [...groups.values()].filter((group) => group.ids.length > 1);
}

/** The sentence the bundle, the ship and publish print. No second wording. */
export function indistinctEditionMessage(year: number, ids: readonly string[]): string {
  return `Editions ${ids.join(", ")} share the year ${String(year)} without a distinct variant.`;
}

/** The edition a course opens on: the lowest position. */
export function defaultEdition<T extends { readonly position: number }>(editions: readonly T[]): T | undefined {
  let chosen: T | undefined;
  for (const edition of editions) {
    if (chosen === undefined || edition.position < chosen.position) chosen = edition;
  }
  return chosen;
}

export interface EditionLanguage {
  readonly id: string;
  readonly position: number;
  readonly language?: string | null;
  readonly variant?: { readonly kind: string; readonly label: string } | null;
}

/**
 * D-035. One language field. A variant of kind `language` is that field, not a second string.
 * The course language, when the course states one, is the default edition's language.
 */
export function languageVariantProblem(edition: {
  readonly id: string;
  readonly language?: string | null;
  readonly variant?: { readonly kind: string; readonly label: string } | null;
}): string | null {
  if (edition.variant?.kind !== "language") return null;
  if (!edition.language) return `Edition ${edition.id} names a language variant without edition.language.`;
  if (edition.variant.label !== edition.language) return `Edition ${edition.id} language variant is ${edition.variant.label}; edition.language is ${edition.language}.`;
  return null;
}

export function editionLanguageProblems(courseLanguage: string | undefined, editions: readonly EditionLanguage[]): string[] {
  const problems: string[] = [];
  for (const edition of editions) {
    const variant = languageVariantProblem(edition);
    if (variant) problems.push(variant);
  }
  const chosen = defaultEdition(editions);
  if (courseLanguage !== undefined && chosen) {
    if (!chosen.language) problems.push(`The course language is ${courseLanguage}; its default edition has none.`);
    else if (chosen.language !== courseLanguage) problems.push(`The course language is ${courseLanguage}; its default edition is ${chosen.language}.`);
  }
  return problems;
}
