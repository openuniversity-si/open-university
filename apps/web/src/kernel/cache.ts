/**
 * Cache durations, budgets, and the two no-store policies (D-050).
 * A page `revalidate`, a Data Cache TTL, a Cache-Control max-age, and a session lifetime read these keys.
 * The same number with a different job is a different key.
 * Immediate expiry (`expire: 0`) is not a cache TTL.
 */
export const CACHE = {
  /** Visitor Home regenerates on this interval. A media or catalog tag refreshes it sooner. */
  homeSeconds: 300,
  /** Sitemap regenerates hourly. A release activation also expires it by tag. */
  sitemapSeconds: 3_600,
  /** Credits, authors, and university pages regenerate daily. A release activation purges them sooner. */
  directorySeconds: 86_400,
  /** Public media reads and lesson-media reads. A tag expires them sooner. */
  mediaReadSeconds: 86_400,
  /** Browser cache of unversioned files in public/. The name is stable, so this is not immutable. */
  publicAssetSeconds: 86_400,
  /** Background revalidation window for those unversioned public files. */
  publicAssetStaleSeconds: 604_800,
  /** Content-addressed media objects, and the image optimizer floor. The bytes do not change. */
  immutableObjectSeconds: 31_536_000,
  /** How long a browser keeps the site HTTPS-only after one visit (HSTS, SSDF PW.9). */
  strictTransportSeconds: 31_536_000,
  /** Course pages, lesson pages, and catalog Data Cache entries. No clock; a tag expires them. */
  untilTagged: false,
  /** Next.js Data Cache refuses an entry above this. */
  platformEntryBytes: 2 * 1024 * 1024,
  /** Public catalog reads stay under this, leaving room under the platform ceiling. */
  entryBudgetBytes: Math.floor(1.5 * 1024 * 1024),
  /** First slice a chunked catalog read tries. A slice that does not fit is halved. */
  chunkItems: 32,
  /** How long a signed-in session stays valid. */
  sessionLifetimeSeconds: 30 * 24 * 60 * 60,
  /** How often the session expiry is refreshed. */
  sessionUpdateSeconds: 24 * 60 * 60,
  /** Compact cookie cache of the session. */
  sessionCacheSeconds: 5 * 60,
  /** oEmbed metadata is fresh only inside this window. */
  oembedFreshMs: 24 * 60 * 60 * 1000,
  /** One day in milliseconds. A video check counts days with this. */
  dayMs: 86_400_000,
  /** Cache-Control for a response a browser or a shared cache must not store. */
  responseNoStore: "no-store",
  /** fetch() cache mode that bypasses the HTTP cache. Not the response header. */
  fetchNoStore: "no-store",
  /** Next.js tag option that purges a tag now. Not a cache TTL. */
  immediateExpiry: 0,
} as const;

/** Cache-Control for a content-addressed media object. */
export const MEDIA_CACHE_CONTROL = `public, max-age=${String(CACHE.immutableObjectSeconds)}, immutable`;

/** Cache-Control for unversioned files under public/. */
export const PUBLIC_ASSET_CACHE_CONTROL = `public, max-age=${String(CACHE.publicAssetSeconds)}, stale-while-revalidate=${String(CACHE.publicAssetStaleSeconds)}`;
