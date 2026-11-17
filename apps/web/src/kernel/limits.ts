/**
 * Catalog limits (D-050). One object: character caps, counts, byte ceilings, and timeouts.
 * The database CHECKs and the request schemas read these keys. `fields.ts` re-exports them.
 * A non-empty floor of 1 is not a key here.
 */
export const LIMITS = {
  entityId: 64,
  authorSlug: 120,
  courseSlug: 120,
  lessonSlug: 160,
  editionSlug: 40,
  homeRowId: 80,
  courseTitle: 200,
  lessonTitle: 1000,
  authorName: 120,
  authorRole: 60,
  monogram: 3,
  languageLabel: 40,
  editionLabel: 40,
  /** Short label of an edition variant (D-034). The 0030 CHECK holds the same number. */
  editionVariantLabel: 40,
  areaTitle: 80,
  attributionText: 500,
  note: 500,
  licenseCode: 64,
  url: 2048,
  lessonSeconds: 86_400,
  text: 10_000,
  /** Public catalog path (`/c/…`), including a redirect. */
  catalogPath: 300,
  /** Id of one import record. */
  importId: 128,
  /** Rights notes stored on a course. */
  rightsNotes: 2000,
  /** Who approved a text or checked rights. Not a catalog slug. */
  actorId: 64,
  /** One object key. */
  objectKey: 512,
  /** How many object keys one check or delete may name. */
  objectKeyBatch: 5000,
  /** Resolution label stored on an edition (`1080p`). */
  resolutionLabel: 20,
  /** How many source playlists one edition may name. */
  sourcePlaylistCount: 20,
  /** How many editions one reorder may name. */
  editionReorderCount: 100,
  /** How many lessons one reorder or slug write may name. */
  lessonWriteCount: 2000,
  /** A `kind:id` reference on a text query. */
  entityRef: 80,
  /** Where a catalog text says it came from. */
  textSourceRef: 200,
  /** How many texts one put, approve, or revoke may name. */
  textBatchCount: 1000,
  /** Title of a row on `PUT /home`. A batch row title uses `courseTitle`. */
  homeRowTitle: 80,
  /** Place line under a university card. */
  placeName: 80,
  /** How many rows one Home document may hold. */
  homeRowCount: 50,
  /** Position of an area or subarea. */
  areaPosition: 1000,
  /** License name a reader sees. Not the license code. */
  licenseName: 120,
  /** Attribution template stored on a license. Not the sentence on a course. */
  attributionTemplate: 500,
  /** Title of a content source. */
  sourceTitle: 200,
  /** Publisher of a content source. A batch publisher uses `authorName`. */
  sourcePublisher: 200,
  /** Title of an imported video or playlist, as the source spelled it. */
  externalTitle: 300,
  /** A short availability, live status, or license token on an import item. */
  importToken: 40,
  /** Channel id carried as text on an import. */
  youtubeChannelId: 64,
  /** Channel name on an import. */
  channelName: 200,
  /** How many videos one import may contain. */
  importItemCount: 500,
  /** How many video ids one import include or exclude list may name. */
  importSelectionCount: 500,
  /** How long a preview token may last, in minutes. */
  previewTtlMinutes: 60,
  /** How many audit rows one query returns. */
  auditPageSize: 200,
  /** Alt text of a cover credit. Stored media alt uses `mediaAlt`. */
  coverAlt: 200,
  /** Credit line of a cover. */
  coverCredit: 200,
  /** Note on a cover credit. Not a catalog note. */
  coverNote: 300,
  /** Reason code on a curated hold or exclusion. */
  curationReason: 80,
  /** Id of one curated run. */
  curationRunId: 80,
  /** How many other courses one course may share a video with. */
  sharedWithCount: 40,
  /** An instant stored as text (ISO-8601). */
  isoTimestamp: 40,
  /** Media owner id. A lesson slug is the longest owner id. */
  mediaOwnerId: 160,
  /** Variant name of a media asset. */
  mediaVariant: 80,
  /** Alt text stored on a media asset. */
  mediaAlt: 500,
  /** How many chunks one ship may be split into. The ship CHECK holds the same number. */
  shipChunkCount: 100,
  /** How many bundles one ship chunk may carry. */
  shipBundleCount: 2000,
  /** How many content hashes one media check may name. */
  mediaCheckBatch: 100,
  /** Error or reason text on a catalog job. */
  jobMessage: 300,
  /** Continuation cursor of a storage list. */
  storageCursor: 64,
  /** Name of the tool that produced an import. */
  importTool: 80,
  /** Entity id on a factory text. A lesson slug is the longest. */
  factoryEntityId: 160,
  /** Description of a site page. Not a lesson slug. */
  pageDescription: 160,
  /** A media upload is refused above this many bytes. */
  mediaBodyBytes: 4 * 1024 * 1024,
  /** Multipart framing allowed above `mediaBodyBytes`. The stored file may not use it. */
  mediaMultipartOverhead: 64 * 1024,
  /** A CSP report longer than this is dropped. Not the multipart framing allowance. */
  cspReportBytes: 64 * 1024,
  /** An ordinary catalog or media admin route gives up after 30 seconds. */
  adminRouteMs: 30_000,
  /** A publish, unpublish, delete, home write, release, bundle apply, or lifecycle route gives up after two minutes. */
  adminLongMs: 120_000,
  /** A publish batch, a ship, or a batch apply gives up after five minutes. */
  adminBatchMs: 300_000,
  /** A media upload, delete, or prune gives up after 60 seconds. */
  mediaTransferMs: 60_000,
  /** A fetch of one public media object gives up after 30 seconds. */
  publicMediaFetchMs: 30_000,
  /** A YouTube oEmbed request gives up after 10 seconds. */
  oembedTimeoutMs: 10_000,
  /** A pooled connection that sits idle is closed after 20 seconds. */
  dbIdleMs: 20_000,
  /** Opening a database connection gives up after 10 seconds. */
  dbConnectMs: 10_000,
  /** One SQL statement gives up after 10 seconds. */
  dbStatementMs: 10_000,
  /** How many physical object requests this process runs at once. */
  r2Concurrency: 4,
  /** How many times one object request is tried. */
  r2Attempts: 5,
  /** One object attempt gives up after 15 seconds. */
  r2AttemptMs: 15_000,
  /** The whole object operation gives up after 60 seconds. */
  r2TotalMs: 60_000,
  /** Most physical object requests this process may run at once. */
  r2ConcurrencyCap: 16,
  /** Most times one object request may be tried. */
  r2AttemptsCap: 8,
  /** One object attempt may not be asked to wait longer than 60 seconds. */
  r2AttemptCapMs: 60_000,
  /** The whole object operation may not be asked to run longer than five minutes. */
  r2TotalCapMs: 300_000,
} as const;

/** Inclusive range of a known edition year (CHECK course_editions_year). */
export const EDITION_YEARS = { min: 1990, max: 2100 } as const;
