export interface SlugifyOptions {
  /** Truncate to this length and remove trailing hyphens. */
  readonly max?: number;
  /** Used when normalization produces an empty slug. */
  readonly fallback?: string;
}

/** Stable ASCII slug shared by import suggestions and legal section anchors. */
export function slugify(text: string, options: SlugifyOptions = {}): string {
  const slug = text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug.slice(0, options.max).replace(/-+$/g, "") || (options.fallback ?? "");
}
