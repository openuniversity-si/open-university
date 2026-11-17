import type { AreaCreate, AreaMove, AreaPatch, LicenseCreate, SourceCreate, SourcePatch, SubareaCreate } from "../domain/contracts.ts";
import { lockReleases, lockRow, type Outcome, type Tx } from "./mutation.ts";
import { EXTENT } from "../../kernel/extent.ts";
import { AppError, notFound, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { activeSubareaCovers } from "./media-gateway.ts";
import { changed } from "./courses.ts";
import { publishRelease, scheduleActivation } from "./releases.ts";

// Reference data. There is no DELETE by design: courses and lessons point to these rows with ON DELETE RESTRICT, and a
// published release names them; retiring one means pointing its courses elsewhere first (ADR-18).

function licenseView(row: Record<string, unknown>) {
  return {
    code: String(row.code), name: String(row.name), url: (row.url ?? null) as string | null, requiresAttribution: row.requires_attribution === true,
    nonCommercial: row.non_commercial === true, shareAlike: row.share_alike === true, embedOnly: row.embed_only === true,
    attributionTemplate: (row.attribution_template ?? null) as string | null,
  };
}
function sourceView(row: Record<string, unknown>) {
  return {
    id: String(row.id), kind: String(row.kind), title: String(row.title), publisher: String(row.publisher), url: String(row.url),
    youtubeChannelId: (row.youtube_channel_id ?? null) as string | null, youtubePlaylistId: (row.youtube_playlist_id ?? null) as string | null, revision: Number(row.revision),
  };
}

export async function listLicenses(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const { rows } = await context.db.query(`SELECT l.*, (SELECT count(*)::int FROM courses c WHERE c.license_code = l.code) + (SELECT count(*)::int FROM lessons s WHERE s.license_code = l.code) AS uses
    FROM licenses l ORDER BY code`);
  return { data: { licenses: rows.map((row) => ({ ...licenseView(row), uses: Number(row.uses) })) } };
}

export async function createLicense(context: HandlerContext<unknown, unknown, LicenseCreate>): Promise<Outcome> {
  const body = context.body;
  return context.mutate(async (tx) => {
    if ((await tx.query("SELECT 1 FROM licenses WHERE code = $1", [body.code])).rows[EXTENT.first]) throw new AppError("slug_taken", `License ${body.code} already exists.`);
    const { rows } = await tx.query(`INSERT INTO licenses (code, name, url, requires_attribution, non_commercial, share_alike, embed_only, attribution_template)
      VALUES ($1, $2, $3, $4, coalesce($5, false), coalesce($6, false), coalesce($7, true), $8) RETURNING *`,
    [body.code, body.name, body.url ?? null, body.requiresAttribution, body.nonCommercial ?? null, body.shareAlike ?? null, body.embedOnly ?? null, body.attributionTemplate ?? null]);
    const license = licenseView(rows[EXTENT.first] ?? {});
    await tx.audit({ action: "license.create", entityKind: "license", entityId: license.code, after: license });
    return { status: 201, data: { license }, entity: `license:${license.code}` };
  });
}

export async function listSources(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const { rows } = await context.db.query("SELECT s.*, (SELECT count(*)::int FROM courses c WHERE c.source_id = s.id) AS uses FROM content_sources s ORDER BY id");
  return { data: { sources: rows.map((row) => ({ ...sourceView(row), uses: Number(row.uses) })) } };
}

export async function createSource(context: HandlerContext<unknown, unknown, SourceCreate>): Promise<Outcome> {
  const body = context.body;
  return context.mutate(async (tx) => {
    if ((await tx.query("SELECT 1 FROM content_sources WHERE id = $1", [body.id])).rows[EXTENT.first]) throw new AppError("slug_taken", `Source ${body.id} already exists.`);
    if (body.youtubePlaylistId && (await tx.query("SELECT id FROM content_sources WHERE youtube_playlist_id = $1", [body.youtubePlaylistId])).rows[EXTENT.first]) {
      throw new AppError("slug_taken", `Playlist ${body.youtubePlaylistId} already has a source.`);
    }
    const { rows } = await tx.query(`INSERT INTO content_sources (id, kind, title, publisher, url, youtube_channel_id, youtube_playlist_id) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *`,
      [body.id, body.kind, body.title, body.publisher, body.url, body.youtubeChannelId ?? null, body.youtubePlaylistId ?? null]);
    const source = sourceView(rows[EXTENT.first] ?? {});
    await tx.audit({ action: "source.create", entityKind: "source", entityId: source.id, after: source });
    return { status: 201, data: { source }, entity: `source:${source.id}` };
  });
}

export async function patchSource(context: HandlerContext<{ id: string }, unknown, SourcePatch>): Promise<Outcome> {
  const { id } = context.params;
  const body = context.body;
  const columns = { kind: "kind", title: "title", publisher: "publisher", url: "url", youtubeChannelId: "youtube_channel_id", youtubePlaylistId: "youtube_playlist_id" } as const;
  return context.mutate(async (tx) => {
    const locked = await lockRow(tx, "content_sources", id, `Source ${id}`, body.expectedRevision);
    const before = sourceView(locked);
    const next: Record<string, unknown> = {};
    for (const [field, column] of Object.entries(columns)) {
      const value = body[field as keyof typeof columns];
      if (value !== undefined && value !== (locked[column] ?? null)) next[column] = value;
    }
    if (Object.keys(next).length === EXTENT.empty) return { data: { source: before, noop: true }, noop: true, entity: `source:${id}` };
    if (typeof next.youtube_playlist_id === "string" && (await tx.query("SELECT id FROM content_sources WHERE youtube_playlist_id = $1 AND id <> $2", [next.youtube_playlist_id, id])).rows[EXTENT.first]) {
      throw new AppError("slug_taken", `Playlist ${next.youtube_playlist_id} already has a source.`);
    }
    const names = Object.keys(next);
    const { rows } = await tx.query(`UPDATE content_sources SET ${names.map((column, index) => `${column} = $${String(index + 2)}`).join(", ")}, revision = revision + 1, updated_at = now() WHERE id = $1 RETURNING *`,
      [id, ...names.map((column) => next[column])]);
    const after = sourceView(rows[EXTENT.first] ?? {});
    await tx.audit({ action: "source.update", entityKind: "source", entityId: id, ...changed(before, after) });
    return { data: { source: after }, entity: `source:${id}` };
  });
}

// Subject areas (ADR-25). Like licenses there is no DELETE: courses point to them with ON DELETE RESTRICT.
function areaView(row: Record<string, unknown>) {
  return { id: String(row.id), title: String(row.title), position: Number(row.position) };
}

export async function listAreas(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const { rows } = await context.db.query(`SELECT a.*, (SELECT count(*)::int FROM courses c WHERE c.area_id = a.id) AS uses,
    (SELECT count(*)::int FROM courses c WHERE c.area_id = a.id AND c.status = 'published') AS published FROM subject_areas a ORDER BY position`);
  return { data: { areas: rows.map((row) => ({ ...areaView(row), uses: Number(row.uses), published: Number(row.published) })) } };
}

export async function createArea(context: HandlerContext<unknown, unknown, AreaCreate>): Promise<Outcome> {
  const body = context.body;
  return context.mutate(async (tx) => {
    if ((await tx.query("SELECT 1 FROM subject_areas WHERE id = $1", [body.id])).rows[EXTENT.first]) throw new AppError("slug_taken", `Area ${body.id} already exists.`);
    if ((await tx.query("SELECT 1 FROM subject_areas WHERE lower(title) = lower($1)", [body.title])).rows[EXTENT.first]) throw new AppError("slug_taken", `Area title ${body.title} already exists.`);
    if (body.position !== undefined && (await tx.query("SELECT 1 FROM subject_areas WHERE position = $1", [body.position])).rows[EXTENT.first]) {
      throw new AppError("slug_taken", `Position ${String(body.position)} is taken; areas keep a fixed order (docs/catalog/areas.md).`);
    }
    const { rows } = await tx.query(`INSERT INTO subject_areas (id, title, position)
      VALUES ($1, $2, coalesce($3, (SELECT coalesce(max(position), 0) + 1 FROM subject_areas))) RETURNING *`, [body.id, body.title, body.position ?? null]);
    const area = areaView(rows[EXTENT.first] ?? {});
    await tx.audit({ action: "area.create", entityKind: "area", entityId: area.id, after: area });
    return { status: 201, data: { area }, entity: `area:${area.id}` };
  });
}

/** Every area in order, locked for the rest of the transaction (move and rename take the same lock, so they queue). */
async function lockAreas(tx: Tx): Promise<ReturnType<typeof areaView>[]> {
  await lockReleases(tx);
  return (await tx.query("SELECT * FROM subject_areas ORDER BY position FOR UPDATE")).rows.map(areaView);
}

/** Inside the mutation: cuts one release for an area change, audits it with that release, revalidates after the commit. */
async function publishAreaChange(tx: Tx, context: HandlerContext<{ id: string }, unknown, { note?: string | undefined }>, audit: { action: string; before: unknown; after: unknown }, note: string) {
  const id = context.params.id;
  const publication = await publishRelease(tx, { note: context.body.note ?? note, actor: context.actor, fresh: new Set(), now: context.deps.now() });
  await tx.audit({ ...audit, entityKind: "area", entityId: id, releaseNumber: publication.release.number });
  scheduleActivation(tx, context.deps, publication.release, publication.release.created);
  return publication;
}

/**
 * Puts one area at `position` (1..n); the others shift by one and every position is rewritten 1..n, so the order stays
 * contiguous. One transaction and one release: reordering the areas is a data change, never a code change (ADR-25).
 */
export async function moveArea(context: HandlerContext<{ id: string }, unknown, AreaMove>): Promise<Outcome> {
  const { id } = context.params;
  const { position } = context.body;
  return context.mutate(async (tx) => {
    const before = await lockAreas(tx);
    const area = before.find((entry) => entry.id === id);
    if (!area) throw notFound(`Area ${id}`);
    if (position > before.length) throw unprocessable(`Position ${String(position)} is out of range: there are ${String(before.length)} areas (1..${String(before.length)}).`);
    const order = before.filter((entry) => entry.id !== id);
    order.splice(position - 1, 0, area);
    if (order.every((entry, index) => entry.position === index + 1)) return { data: { area, areas: before, noop: true }, noop: true, entity: `area:${id}` };
    // subject_areas_position_unique is not deferrable: park every row above the current maximum, then write 1..n. Neither
    // statement can meet a position another row still holds.
    await tx.query("UPDATE subject_areas SET position = position + (SELECT max(position) FROM subject_areas)");
    await tx.query("UPDATE subject_areas a SET position = o.n::int FROM unnest($1::text[]) WITH ORDINALITY AS o(id, n) WHERE a.id = o.id", [order.map((entry) => entry.id)]);
    const after = (await tx.query("SELECT * FROM subject_areas ORDER BY position")).rows.map(areaView);
    const publication = await publishAreaChange(tx, context, {
      action: "area.move", before: { position: area.position, order: before.map((entry) => entry.id) }, after: { position, order: after.map((entry) => entry.id) },
    }, `Move area ${id} to ${String(position)}`);
    return { data: { area: { ...area, position }, areas: after, release: publication.release, diff: publication.diff }, entity: `area:${id}` };
  });
}

/** Renames one area; the id (the URL segment) stays. One transaction and one release. */
export async function patchArea(context: HandlerContext<{ id: string }, unknown, AreaPatch>): Promise<Outcome> {
  const { id } = context.params;
  const { title } = context.body;
  return context.mutate(async (tx) => {
    const before = (await lockAreas(tx)).find((entry) => entry.id === id);
    if (!before) throw notFound(`Area ${id}`);
    if (before.title === title) return { data: { area: before, noop: true }, noop: true, entity: `area:${id}` };
    if ((await tx.query("SELECT 1 FROM subject_areas WHERE lower(title) = lower($1) AND id <> $2", [title, id])).rows[EXTENT.first]) throw new AppError("slug_taken", `Area title ${title} already exists.`);
    const area = areaView((await tx.query("UPDATE subject_areas SET title = $2 WHERE id = $1 RETURNING *", [id, title])).rows[EXTENT.first] ?? {});
    const publication = await publishAreaChange(tx, context, { action: "area.update", before, after: area }, `Rename area ${id}`);
    return { data: { area, release: publication.release, diff: publication.diff }, entity: `area:${id}` };
  });
}

// Subareas (ADR-26). Append-only like areas: no DELETE, courses point to them with ON DELETE RESTRICT.
function subareaView(row: Record<string, unknown>) {
  return { id: String(row.id), areaId: String(row.area_id), title: String(row.title), position: Number(row.position) };
}

export async function listSubareas(context: HandlerContext<unknown, { covers?: "1" }, unknown>): Promise<Outcome> {
  const covers = context.query.covers === "1" ? await activeSubareaCovers(context.db) : null;
  const { rows } = await context.db.query(`SELECT s.*, (SELECT count(*)::int FROM courses c WHERE c.subarea_id = s.id) AS uses,
    (SELECT count(*)::int FROM courses c WHERE c.subarea_id = s.id AND c.status = 'published') AS published
    FROM subject_subareas s JOIN subject_areas a ON a.id = s.area_id ORDER BY a.position, s.position`);
  return {
    data: {
      subareas: rows.map((row) => ({
        ...subareaView(row), uses: Number(row.uses), published: Number(row.published),
        ...(covers ? { covers: covers.get(String(row.id)) ?? [] } : {}),
      })),
    },
  };
}

export async function createSubarea(context: HandlerContext<unknown, unknown, SubareaCreate>): Promise<Outcome> {
  const body = context.body;
  return context.mutate(async (tx) => {
    if (!(await tx.query("SELECT 1 FROM subject_areas WHERE id = $1", [body.areaId])).rows[EXTENT.first]) throw unprocessable(`Unknown area ${body.areaId}.`);
    // One namespace for rail anchors: a subarea id is never an area id nor another subarea's.
    if ((await tx.query("SELECT 1 FROM subject_subareas WHERE id = $1 UNION ALL SELECT 1 FROM subject_areas WHERE id = $1", [body.id])).rows[EXTENT.first]) throw new AppError("slug_taken", `Id ${body.id} is already an area or a subarea.`);
    if ((await tx.query("SELECT 1 FROM subject_subareas WHERE lower(title) = lower($1)", [body.title])).rows[EXTENT.first]) throw new AppError("slug_taken", `Subarea title ${body.title} already exists.`);
    if (body.position !== undefined && (await tx.query("SELECT 1 FROM subject_subareas WHERE area_id = $1 AND position = $2", [body.areaId, body.position])).rows[EXTENT.first]) {
      throw new AppError("slug_taken", `Position ${String(body.position)} of ${body.areaId} is taken; subareas keep a fixed order (docs/catalog/subareas.md).`);
    }
    const { rows } = await tx.query(`INSERT INTO subject_subareas (id, area_id, title, position)
      VALUES ($1, $2, $3, coalesce($4, (SELECT coalesce(max(position), 0) + 1 FROM subject_subareas WHERE area_id = $2))) RETURNING *`, [body.id, body.areaId, body.title, body.position ?? null]);
    const subarea = subareaView(rows[EXTENT.first] ?? {});
    await tx.audit({ action: "subarea.create", entityKind: "subarea", entityId: subarea.id, after: subarea });
    return { status: 201, data: { subarea }, entity: `subarea:${subarea.id}` };
  });
}
