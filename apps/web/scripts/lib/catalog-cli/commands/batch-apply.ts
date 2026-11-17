import { batchV2Hash, chunkBatchV2, type ApplyBatchData } from "../../../../src/catalog/domain/batch-v2.ts";
import { MAX_BODY_BYTES } from "../../../../src/catalog/domain/contracts.ts";
import { catalogBatchV2Schema } from "../../../../src/catalog/domain/schema/batch-v2.ts";
import { requireOption } from "../args.ts";
import { parseJsonFile, type CommandSpec } from "../context.ts";
import { UsageError } from "../errors.ts";

/** Room for the apply envelope (hash, chunk indexes, dryRun) around one part. */
const PART_BUDGET = MAX_BODY_BYTES - 1024;

export const batchApplyCommands: CommandSpec[] = [
  {
    name: "batch apply",
    usage: "batch apply --file <batch.json> [--draft] [--note <text>]",
    summary: "apply a CatalogBatchV2 through POST /batches/apply; --dry-run runs that transaction and rolls it back",
    options: {
      file: { type: "string", required: true, help: "CatalogBatchV2 JSON", value: "<path>" },
      draft: { type: "boolean", help: "write the batch without publishing" },
      note: { type: "string", help: "release note", value: "<text>" },
    },
    positionals: { min: 0, max: 0 },
    routes: ["POST /batches/apply"],
    async run(context) {
      const parsed = catalogBatchV2Schema.safeParse(parseJsonFile(context, requireOption(context.args, "file")));
      if (!parsed.success) throw new UsageError(parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "));
      const batch = parsed.data;
      const hash = batchV2Hash(batch);
      const parts = chunkBatchV2(batch, PART_BUDGET);
      const draft = context.args.options.draft === true;
      const note = typeof context.args.options.note === "string" ? context.args.options.note : undefined;
      await context.confirm(`Apply batch ${hash.slice(0, 12)} (${String(batch.courses.length)} course(s))${context.dryRun ? " as a dry run" : ""}.`);
      let data: ApplyBatchData | undefined;
      for (const [index, part] of parts.entries()) {
        const result = await context.client.call("POST /batches/apply", {
          body: { batchHash: hash, chunk: index, chunks: parts.length, dryRun: context.dryRun, draft, ...(note ? { note } : {}), part },
        });
        data = result.data as ApplyBatchData;
        if (data.status === "partial") continue;
        context.out.line(`batch ${hash.slice(0, 12)} ${data.status} courses=${String(data.courses.length)} release=${data.release ? String(data.release.number) : "none"}`);
        context.out.result(result.envelope);
        return;
      }
      throw new UsageError(`Batch ${hash.slice(0, 12)} stayed partial after ${String(parts.length)} chunk(s).`);
    },
  },
];
