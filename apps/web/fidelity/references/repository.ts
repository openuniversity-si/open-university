/** Plain-Postgres access to tower_tooling; any driver with a parameterized query() fits. */
export interface SqlClient {
  query(text: string, values?: readonly unknown[]): Promise<{ readonly rows: readonly Record<string, unknown>[] }>;
}

export interface ReferenceSet {
  readonly id: string;
  readonly figmaFileKey: string;
  readonly figmaVersionId: string;
  readonly createdAt: string;
  readonly isActive: boolean;
  readonly note: string | null;
}

export interface ReferenceImage {
  readonly nodeId: string;
  readonly screenKey: string;
  /** `<frame width>@<scale>x`, e.g. `390@2x`. */
  readonly viewport: string;
  readonly blobUrl: string;
  readonly sha256: string;
  readonly width: number;
  readonly height: number;
}

/** Bounding box of `nodeId` relative to the exported root `rootNodeId`, in CSS pixels. */
export interface ReferenceNode {
  readonly rootNodeId: string;
  readonly nodeId: string;
  readonly name: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface ActiveReferenceSet {
  readonly set: ReferenceSet;
  readonly images: readonly ReferenceImage[];
  readonly nodes: readonly ReferenceNode[];
}

export class NoActiveReferenceSetError extends Error {
  constructor() {
    super("No active fidelity reference set in tower_tooling. Run `pnpm fidelity:sync` (see docs/fidelity/F03.md).");
  }
}

const text = (value: unknown): string => {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint") return String(value);
  if (value instanceof Date) return value.toISOString();
  throw new Error("Unexpected tower_tooling column value.");
};

const toSet = (row: Record<string, unknown>): ReferenceSet => ({
  id: text(row.id),
  figmaFileKey: text(row.figma_file_key),
  figmaVersionId: text(row.figma_version_id),
  createdAt: text(row.created_at),
  isActive: row.is_active === true,
  note: row.note === null ? null : text(row.note),
});

const SET_COLUMNS = "id::text AS id, figma_file_key, figma_version_id, created_at, is_active, note";

export async function findReferenceSet(db: SqlClient, figmaFileKey: string, figmaVersionId: string): Promise<ReferenceSet | null> {
  const { rows } = await db.query(`SELECT ${SET_COLUMNS} FROM fidelity_reference_set WHERE figma_file_key = $1 AND figma_version_id = $2`, [figmaFileKey, figmaVersionId]);
  return rows[0] ? toSet(rows[0]) : null;
}

export async function loadActiveReferenceSet(db: SqlClient): Promise<ActiveReferenceSet> {
  const { rows } = await db.query(`SELECT ${SET_COLUMNS} FROM fidelity_reference_set WHERE is_active`);
  if (!rows[0]) throw new NoActiveReferenceSetError();
  const set = toSet(rows[0]);
  const images = await db.query("SELECT node_id, screen_key, viewport, blob_url, sha256, width, height FROM fidelity_reference_image WHERE set_id = $1 ORDER BY screen_key", [set.id]);
  const nodes = await db.query("SELECT root_node_id, node_id, name, x, y, width, height FROM fidelity_reference_node WHERE set_id = $1 ORDER BY root_node_id, node_id", [set.id]);
  if (images.rows.length === 0) throw new Error(`Active fidelity reference set ${set.id} has no images.`);
  return {
    set,
    images: images.rows.map((row) => ({
      nodeId: text(row.node_id), screenKey: text(row.screen_key), viewport: text(row.viewport), blobUrl: text(row.blob_url),
      sha256: text(row.sha256), width: Number(row.width), height: Number(row.height),
    })),
    nodes: nodes.rows.map((row) => ({
      rootNodeId: text(row.root_node_id), nodeId: text(row.node_id), name: text(row.name),
      x: Number(row.x), y: Number(row.y), width: Number(row.width), height: Number(row.height),
    })),
  };
}

/** Blob URL already stored for identical bytes of this Figma file, so unchanged renders are not uploaded again. */
export async function knownBlobUrls(db: SqlClient, figmaFileKey: string): Promise<ReadonlyMap<string, string>> {
  const { rows } = await db.query(
    "SELECT DISTINCT ON (i.sha256) i.sha256, i.blob_url FROM fidelity_reference_image i JOIN fidelity_reference_set s ON s.id = i.set_id WHERE s.figma_file_key = $1 ORDER BY i.sha256, s.id DESC",
    [figmaFileKey],
  );
  return new Map(rows.map((row) => [text(row.sha256), text(row.blob_url)]));
}

async function inTransaction<T>(db: SqlClient, work: () => Promise<T>): Promise<T> {
  await db.query("BEGIN");
  try {
    const result = await work();
    await db.query("COMMIT");
    return result;
  } catch (error) {
    await db.query("ROLLBACK");
    throw error;
  }
}

async function activate(db: SqlClient, id: string): Promise<void> {
  // The partial unique index allows one active row; clear the old one first, inside the same transaction.
  await db.query("UPDATE fidelity_reference_set SET is_active = false WHERE is_active AND id <> $1", [id]);
  await db.query("UPDATE fidelity_reference_set SET is_active = true WHERE id = $1", [id]);
}

export async function activateReferenceSet(db: SqlClient, id: string): Promise<void> {
  await inTransaction(db, () => activate(db, id));
}

export interface NewReferenceSet {
  readonly figmaFileKey: string;
  readonly figmaVersionId: string;
  readonly note: string | null;
  readonly images: readonly ReferenceImage[];
  readonly nodes: readonly ReferenceNode[];
}

/** Insert the set, its images and geometry, and make it the only active set, atomically. */
export async function insertAndActivateReferenceSet(db: SqlClient, input: NewReferenceSet): Promise<string> {
  if (input.images.length === 0) throw new Error("A fidelity reference set needs at least one image.");
  return inTransaction(db, async () => {
    const { rows } = await db.query(
      "INSERT INTO fidelity_reference_set (figma_file_key, figma_version_id, note) VALUES ($1, $2, $3) RETURNING id::text AS id",
      [input.figmaFileKey, input.figmaVersionId, input.note],
    );
    const id = text(rows[0]?.id);
    const column = <T>(items: readonly T[], pick: (item: T) => string | number) => items.map(pick);
    await db.query(
      `INSERT INTO fidelity_reference_image (set_id, node_id, screen_key, viewport, blob_url, sha256, width, height)
       SELECT $1, * FROM unnest($2::text[], $3::text[], $4::text[], $5::text[], $6::text[], $7::int[], $8::int[])`,
      [id, ...(["nodeId", "screenKey", "viewport", "blobUrl", "sha256", "width", "height"] as const).map((key) => column(input.images, (image) => image[key]))],
    );
    if (input.nodes.length > 0) {
      await db.query(
        `INSERT INTO fidelity_reference_node (set_id, root_node_id, node_id, name, x, y, width, height)
         SELECT $1, * FROM unnest($2::text[], $3::text[], $4::text[], $5::float8[], $6::float8[], $7::float8[], $8::float8[])`,
        [id, ...(["rootNodeId", "nodeId", "name", "x", "y", "width", "height"] as const).map((key) => column(input.nodes, (node) => node[key]))],
      );
    }
    await activate(db, id);
    return id;
  });
}

/** Inactive sets beyond the newest `keepInactive`, and the blob URLs only they reference. */
export async function supersededReferenceSets(db: SqlClient, keepInactive: number): Promise<{ readonly setIds: readonly string[]; readonly blobUrls: readonly string[] }> {
  const victims = (await db.query("SELECT id::text AS id FROM fidelity_reference_set WHERE NOT is_active ORDER BY id DESC OFFSET $1", [keepInactive])).rows.map((row) => text(row.id));
  if (victims.length === 0) return { setIds: [], blobUrls: [] };
  const { rows } = await db.query(
    `SELECT DISTINCT blob_url FROM fidelity_reference_image WHERE set_id = ANY($1::bigint[])
     EXCEPT SELECT blob_url FROM fidelity_reference_image WHERE NOT (set_id = ANY($1::bigint[])) ORDER BY 1`,
    [victims],
  );
  return { setIds: victims, blobUrls: rows.map((row) => text(row.blob_url)) };
}

export async function deleteReferenceSets(db: SqlClient, setIds: readonly string[]): Promise<void> {
  await db.query("DELETE FROM fidelity_reference_set WHERE id = ANY($1::bigint[]) AND NOT is_active", [setIds]);
}
