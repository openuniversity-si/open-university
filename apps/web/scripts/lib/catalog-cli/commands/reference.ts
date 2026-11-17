import type { z } from "zod";
import { areaCreate, subareaCreate, licenseCreate, sourceCreate, sourcePatch } from "../../../../src/catalog/domain/contracts.ts";
import { fieldOptions, fieldValues, flag, intOption, positional, requireOption, stringOption } from "../args.ts";
import type { CommandSpec, Context } from "../context.ts";
import { UsageError } from "../errors.ts";
import { diffLines, orDash, table } from "../render.ts";
import { listAllRedirects, patchFields, patchWithRetry } from "./shared.ts";
import type { SourceRow } from "../responses.ts";


async function sourceOf(context: Context, id: string): Promise<SourceRow> {
  const source = (await context.client.call("GET /sources")).data.sources.find((entry) => entry.id === id);
  if (!source) throw new UsageError(`No source ${id}.`);
  return source;
}

export const referenceCommands: CommandSpec[] = [
  {
    name: "area list", usage: "area list", summary: "subject areas in their fixed order and how many courses use each (docs/catalog/areas.md)", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /areas"],
    async run(context) {
      const result = await context.client.call("GET /areas");
      context.out.lines(table(["pos", "id", "title", "uses", "published"], result.data.areas.map((area) => [String(area.position), area.id, area.title, String(area.uses ?? 0), String(area.published ?? 0)])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "area create", usage: "area create --id <slug> --title <t> [--position <n>]",
    summary: "add a subject area (last unless --position names a free slot); assign with course set --area-id", options: fieldOptions(areaCreate), positionals: { min: 0, max: 0 }, routes: ["POST /areas"],
    async run(context) {
      const body = fieldValues(areaCreate, context.args) as z.input<typeof areaCreate>;
      await context.confirm(`Create area ${body.id}`);
      const result = await context.client.call("POST /areas", { body });
      context.out.line(`Created area ${result.data.area.id} at position ${String(result.data.area.position)}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "area move", usage: "area move <id> --position <n> [--note <text>]",
    summary: "put an area at position n (1..count); the others shift, positions stay 1..n; one release", options: {
      position: { type: "string", required: true, help: "new position, 1..number of areas", value: "<n>" }, note: { type: "string", help: "release note (default: Move area <id> to <n>)", value: "<text>" },
    }, positionals: { min: 1, max: 1 }, routes: ["POST /areas/:id/move"],
    async run(context) {
      const id = positional(context.args, 0, "area");
      const position = intOption(context.args, "position");
      if (position === undefined) throw new UsageError("--position is required.");
      const note = stringOption(context.args, "note");
      await context.confirm(`Move area ${id} to position ${String(position)} and publish a release`);
      const result = await context.client.call("POST /areas/:id/move", { params: { id }, body: { position, ...(note === undefined ? {} : { note }) } });
      if (result.data.noop || !result.data.release) context.out.line(`Area ${id} is already at position ${String(position)}; nothing changed.`);
      else context.out.lines([`Moved area ${id} to position ${String(position)}; release #${String(result.data.release.number)}${result.data.release.created ? " created" : " unchanged"}.`, ...diffLines(result.data.diff ?? null)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "area update", usage: "area update <id> --title <t> [--note <text>]", summary: "rename an area (the id stays); one release",
    options: { title: { type: "string", required: true, help: "new title, unique", value: "<t>" }, note: { type: "string", help: "release note (default: Rename area <id>)", value: "<text>" } },
    positionals: { min: 1, max: 1 }, routes: ["PATCH /areas/:id"],
    async run(context) {
      const id = positional(context.args, 0, "area");
      const title = requireOption(context.args, "title");
      const note = stringOption(context.args, "note");
      await context.confirm(`Rename area ${id} to ${title} and publish a release`);
      const result = await context.client.call("PATCH /areas/:id", { params: { id }, body: { title, ...(note === undefined ? {} : { note }) } });
      if (result.data.noop || !result.data.release) context.out.line(`Area ${id} is already titled ${title}; nothing changed.`);
      else context.out.lines([`Renamed area ${id} to ${result.data.area.title}; release #${String(result.data.release.number)}${result.data.release.created ? " created" : " unchanged"}.`, ...diffLines(result.data.diff ?? null)]);
      context.out.result(result.envelope);
    },
  },
  {
    name: "subarea list", usage: "subarea list [--area <id>] [--covers]", summary: "subareas in display order (area, then position) and how many courses use each; --covers adds every subarea's active covers in that one call (docs/catalog/subareas.md)",
    options: { area: { type: "string", help: "only this area", value: "<id>" }, covers: { type: "boolean", help: "include active covers" } }, positionals: { min: 0, max: 0 }, routes: ["GET /subareas"],
    async run(context) {
      const covers = flag(context.args, "covers");
      const result = await context.client.call("GET /subareas", { query: covers ? { covers: "1" } : {} });
      const area = stringOption(context.args, "area");
      const rows = result.data.subareas.filter((subarea) => area === undefined || subarea.areaId === area);
      const headers = ["area", "pos", "id", "title", "uses", "published", ...(covers ? ["covers"] : [])];
      context.out.lines(table(headers, rows.map((subarea) => {
        const cells = [subarea.areaId, String(subarea.position), subarea.id, subarea.title, String(subarea.uses ?? 0), String(subarea.published ?? 0)];
        return covers ? [...cells, (subarea.covers ?? []).map((cover) => cover.kind).join(",") || "-"] : cells;
      })));
      context.out.result(result.envelope);
    },
  },
  {
    name: "subarea create", usage: "subarea create --id <slug> --area-id <area> --title <t> [--position <n>]",
    summary: "append a subarea to an area (last in it unless --position names a free slot); assign with course set --subarea-id or course classify", options: fieldOptions(subareaCreate), positionals: { min: 0, max: 0 }, routes: ["POST /subareas"],
    async run(context) {
      const body = fieldValues(subareaCreate, context.args) as z.input<typeof subareaCreate>;
      await context.confirm(`Create subarea ${body.id} in ${body.areaId}`);
      const result = await context.client.call("POST /subareas", { body });
      context.out.line(`Created subarea ${result.data.subarea.id} in ${result.data.subarea.areaId} at position ${String(result.data.subarea.position)}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "license list", usage: "license list", summary: "licenses and how many courses/lessons use each", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /licenses"],
    async run(context) {
      const result = await context.client.call("GET /licenses");
      context.out.lines(table(["code", "name", "attribution", "nc", "uses"], result.data.licenses.map((license) => [license.code, license.name, license.requiresAttribution ? "yes" : "no", license.nonCommercial ? "yes" : "no", String(license.uses)])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "license create", usage: "license create --code <c> --name <n> --requires-attribution true|false [--url …] [--non-commercial …] [--attribution-template …]",
    summary: "add a license", options: fieldOptions(licenseCreate), positionals: { min: 0, max: 0 }, routes: ["POST /licenses"],
    async run(context) {
      const body = fieldValues(licenseCreate, context.args) as z.input<typeof licenseCreate>;
      await context.confirm(`Create license ${body.code}`);
      const result = await context.client.call("POST /licenses", { body });
      context.out.line(`Created license ${result.data.license.code}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "source list", usage: "source list", summary: "content sources (playlists, channels, sites)", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /sources"],
    async run(context) {
      const result = await context.client.call("GET /sources");
      context.out.lines(table(["id", "kind", "publisher", "rev", "uses", "title"], result.data.sources.map((source) => [source.id, source.kind, source.publisher, String(source.revision), String(source.uses), source.title])));
      context.out.result(result.envelope);
    },
  },
  {
    name: "source create", usage: "source create --id <id> --kind <k> --title <t> --publisher <p> --url <https://…> [--youtube-playlist-id …]",
    summary: "add a content source", options: fieldOptions(sourceCreate), positionals: { min: 0, max: 0 }, routes: ["POST /sources"],
    async run(context) {
      const body = fieldValues(sourceCreate, context.args) as z.input<typeof sourceCreate>;
      await context.confirm(`Create source ${body.id}`);
      const result = await context.client.call("POST /sources", { body });
      context.out.line(`Created source ${result.data.source.id}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "source set", usage: "source set <source> [--title …] [--url …] [--unset <field>] [--file fields.json]", summary: "change a source (PATCH, expectedRevision read first)",
    options: { ...fieldOptions(sourcePatch, ["expectedRevision"]), file: { type: "string", help: "JSON object of fields", value: "<path>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /sources", "PATCH /sources/:id"],
    async run(context) {
      const id = positional(context.args, 0, "source");
      const fields = patchFields(context, sourcePatch, context.args);
      await context.confirm(`Change ${Object.keys(fields).join(", ")} of source ${id}`);
      const result = await patchWithRetry(context, fields, async () => {
        const source = await sourceOf(context, id);
        return { revision: source.revision, values: source as unknown as Record<string, unknown> };
      }, (revision) => context.client.call("PATCH /sources/:id", { params: { id }, body: { ...fields, expectedRevision: revision } }));
      context.out.line(`Updated source ${id} (revision ${String(result.data.source.revision)}).`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "redirect list", usage: "redirect list", summary: "slug redirects, one keyset page at a time (live = the target is in the next release and the source is not)", options: {}, positionals: { min: 0, max: 0 }, routes: ["GET /redirects"],
    async run(context) {
      const redirects = await listAllRedirects(context);
      context.out.lines(table(["from", "to", "live"], redirects.map((redirect) => [redirect.from, redirect.to, redirect.live === undefined ? "-" : redirect.live ? "yes" : "no"])));
      context.out.result({ redirects, nextCursor: null });
    },
  },
  {
    name: "redirect add", usage: "redirect add --from /c/old --to /c/new", summary: "add a redirect (reaches the site with the next release)",
    options: { from: { type: "string", required: true, help: "old path", value: "</c/…>" }, to: { type: "string", required: true, help: "course or lesson page", value: "</c/…>" } },
    positionals: { min: 0, max: 0 }, routes: ["POST /redirects"],
    async run(context) {
      const body = { from: requireOption(context.args, "from"), to: requireOption(context.args, "to") };
      await context.confirm(`Redirect ${body.from} → ${body.to}`);
      const result = await context.client.call("POST /redirects", { body });
      context.out.line(`Added ${result.data.redirect.from} → ${result.data.redirect.to}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "redirect rm", usage: "redirect rm --from /c/old [--confirm]", summary: "remove a redirect; a dry-run unless --confirm",
    options: { from: { type: "string", required: true, help: "old path", value: "</c/…>" }, confirm: { type: "boolean", help: "execute" } }, positionals: { min: 0, max: 0 }, routes: ["DELETE /redirects"],
    async run(context) {
      const from = requireOption(context.args, "from");
      const report = await context.client.call("DELETE /redirects", { query: { from } });
      context.out.line(`Would remove ${report.data.redirect.from} → ${report.data.redirect.to}.`);
      if (!flag(context.args, "confirm")) { context.out.line("Nothing changed. Re-run with --confirm to execute."); context.out.result(report.envelope); return; }
      await context.confirm(`Remove redirect ${from}`, true);
      const result = await context.client.call("DELETE /redirects", { query: { from, confirm: "true" } });
      context.out.line(`Removed ${from}.`);
      context.out.result(result.envelope);
    },
  },
  {
    name: "audit show", usage: "audit show <kind:id> [--limit n]", summary: "audit trail of one entity, newest first (course:course-6, release:3, home:home…)",
    options: { limit: { type: "string", help: "entries, ≤ 200 (default 50)", value: "<n>" } }, positionals: { min: 1, max: 1 }, routes: ["GET /audit"],
    async run(context) {
      const limit = intOption(context.args, "limit");
      const result = await context.client.call("GET /audit", {
        query: { entity: positional(context.args, 0, "entity"), ...(limit === undefined ? {} : { limit: String(limit) }) },
      });
      context.out.lines(table(["at", "action", "actor", "release", "requestId"], result.data.entries.map((entry) => [entry.at, entry.action, entry.actor, orDash(entry.releaseNumber), entry.requestId])));
      context.out.result(result.envelope);
    },
  },
];
