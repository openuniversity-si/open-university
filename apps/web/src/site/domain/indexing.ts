export interface IndexingFacts {
  readonly production: boolean;
  readonly siteIndexable?: string;
}

/**
 * The single indexing rule (ADR-12): a production deployment is indexable, as is an explicit
 * siteIndexable "true" opt-in for local verification builds. Previews, development, CI and
 * anything else stay noindex. The host adapter supplies `production`.
 */
export function isSiteIndexable(facts: IndexingFacts): boolean {
  return facts.production || facts.siteIndexable === "true";
}

export const NOINDEX_HEADER_VALUE = "noindex, nofollow";

/** Root layout `metadata.robots`, from the same rule. */
export function robotsMetadata(facts: IndexingFacts): { index: boolean; follow: boolean } {
  const indexable = isSiteIndexable(facts);
  return { index: indexable, follow: indexable };
}
