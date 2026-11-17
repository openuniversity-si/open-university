import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { universityCoverSchema, universityOgSchema, type UniversityCover } from "../../../../src/catalog/domain/university-cover.ts";
import { objectKey } from "../../../../src/media/server/objects.ts";
import { uploadCatalogObject } from "../media-object.ts";
import { stringOption } from "../args.ts";
import type { CommandSpec } from "../context.ts";
import type { HomeRow } from "../responses.ts";
import { UsageError } from "../errors.ts";
import { listReleases, verifyActivation } from "./shared.ts";

/** `home og` publishes link previews. A row cover itself ships inside the batch; `home cover` is a refusal. */
export const universityCoverCommands: CommandSpec[] = [];

/** PUT /home rows: every row as it is (an absent cover stays), with the new covers of `covers` (row id → cover). */
export function homeRowsWithCovers(rows: readonly HomeRow[], covers: ReadonlyMap<string, UniversityCover>) {
  return rows.map((entry) => {
    const cover = covers.get(entry.id);
    return {
      id: entry.id, kind: entry.kind, ...(entry.title === null ? {} : { title: entry.title }),
      ...(entry.authorId === null ? {} : { authorId: entry.authorId }), visible: entry.visible, courseIds: entry.courseIds,
      ...(cover ? { cover } : {}),
    };
  });
}

universityCoverCommands.push({
  name: "home og", usage: "home og [<row>...] [--dir <folder>]",
  summary: "render the 1200×630 JPEG link preview of university covers (letterboxed on a dark fill) and publish them in one release",
  options: { dir: { type: "string", help: "local covers as <row>.{webp,jpg,png}; default: fetch each cover from the media host", value: "<folder>" } },
  positionals: { min: 0, max: 100 }, routes: ["GET /home", "GET /releases", "PUT /home"],
  async run(context) {
    const home = (await context.client.call("GET /home")).data;
    const wanted = new Set(context.args.positionals);
    const rows = home.rows.filter((row) => row.kind === "curated" && row.cover && (wanted.size === 0 || wanted.has(row.id)));
    for (const id of wanted) if (!rows.some((row) => row.id === id)) throw new UsageError(`Row ${id} is not a curated row with a cover.`);
    if (rows.length === 0) { context.out.line("No university covers: nothing to do."); return; }
    if (context.target === "staging") throw new UsageError("The media bucket has no staging target; make previews on preview or prod.");
    const { renderOgImage } = await import("../../../../src/media/server/og.ts");
    const { prepareMedia } = await import("../../media-storage.ts");
    const dir = stringOption(context.args, "dir");
    await context.confirm(`Set the link previews of ${String(rows.length)} universities (one release)`, true);
    const covers = new Map<string, UniversityCover>();
    // One at a time (memory): read the cover, render, upload the content-addressed JPEG.
    for (const row of rows) {
      const cover = universityCoverSchema.parse(row.cover);
      let source: Buffer;
      const local = dir ? ["webp", "jpg", "png"].map((ext) => join(dir, `${row.id}.${ext}`)).find((path) => existsSync(path)) : undefined;
      if (dir && !local) throw new UsageError(`No ${row.id}.{webp,jpg,png} in ${dir}.`);
      if (local) source = readFileSync(local);
      else {
        const response = await fetch(cover.url);
        if (!response.ok) throw new UsageError(`Cover of ${row.id}: HTTP ${String(response.status)}.`);
        source = Buffer.from(await response.arrayBuffer());
      }
      const prepared = await prepareMedia(await renderOgImage(source, "letterbox"));
      const pathname = objectKey(prepared.sha256, prepared.extension);
      const object = await uploadCatalogObject(context, prepared.bytes);
      const url = object.url;
      const og = universityOgSchema.parse({ url, width: prepared.width, height: prepared.height, sha256: prepared.sha256, mediaSha256: prepared.sha256 });
      context.out.line(`${row.id}: ${pathname} (${String(Math.ceil(prepared.bytes.length / 1024))} KiB, ${String(og.width)}×${String(og.height)})`);
      covers.set(row.id, universityCoverSchema.parse({ ...cover, og }));
    }
    if (context.dryRun) { context.out.note("DRY-RUN: nothing uploaded or published."); return; }
    await context.confirm(`Set the link preview of ${String(covers.size)} universit${covers.size === 1 ? "y" : "ies"} (one release)`, true);
    const previous = (await listReleases(context)).find((release) => release.isActive)?.number ?? null;
    const result = await context.client.call("PUT /home", { body: { featuredCourseId: home.featuredCourseId, rows: homeRowsWithCovers(home.rows, covers), expectedRevision: home.revision, note: `University link previews: ${[...covers.keys()].join(", ")}` } });
    context.out.lines([`Link previews of ${String(covers.size)} universities; release #${String(result.data.release.number)}${result.data.release.created ? " created" : " unchanged"}`]);
    context.out.result(result.envelope);
    if (result.data.release.created) await verifyActivation(context, result.data.release.number, previous);
  },
});
