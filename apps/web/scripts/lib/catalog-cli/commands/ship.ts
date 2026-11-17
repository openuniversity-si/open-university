import { statSync } from "node:fs";
import type { AdminEnvironment } from "../../../../src/admin/ports/jobs.ts";
import { stringOption, type ParsedArgs } from "../args.ts";
import type { CommandSpec } from "../context.ts";
import { UsageError } from "../errors.ts";
import { parseTarget, type Target } from "../target.ts";
import { isCatalogBatchFile, shipBatchFile, shipBundleDirectory } from "./ship-apply.ts";

/**
 * Routes this command used to call, still declared so every admin route keeps a command. The run below sends only
 * `media:POST /check`, `media:POST /objects` and `POST /batches/apply`.
 */
const SHIP_ROUTES = [
  "POST /jobs/claim", "POST /jobs/:id/renew", "POST /jobs/:id/advance", "POST /jobs/:id/complete",
  "POST /bundles/apply", "POST /bundles/ship", "POST /batches/apply", "POST /preview-token",
  "GET /courses/:id", "POST /courses/:id/status", "POST /courses/:id/publish", "POST /courses/publish-batch",
  "GET /releases", "GET /releases/:n",
  "media:POST /check", "media:POST /objects", "media:POST /attach",
] as const;

const REMOVED = "Removed: --batch, --bulk and --concurrency. Use tower-catalog ship <dir|batch>, which sends POST /batches/apply.";

function environmentsOf(value: string): readonly AdminEnvironment[] {
  if (value === "both") return ["preview", "prod"];
  if (value === "preview" || value === "prod") return [value];
  throw new UsageError("--to must be preview, prod or both.");
}

/**
 * `--to` implies the target: preview → preview, prod and both → prod. An explicit `--target` must agree with it: its
 * environment (staging shares preview's) must be one `--to` ships to.
 */
export function shipTarget(args: ParsedArgs): Target {
  const to = stringOption(args, "to");
  if (!to) throw new UsageError("--to is required.");
  const environments = environmentsOf(to);
  const explicit = stringOption(args, "target");
  if (explicit === undefined) return to === "preview" ? "preview" : "prod";
  const target = parseTarget(explicit);
  if (!environments.includes(target === "prod" ? "prod" : "preview")) throw new UsageError(`--target ${target} conflicts with --to ${to}; drop --target (--to implies it).`);
  return target;
}

export const shipCommands: CommandSpec[] = [
  {
    name: "ship",
    usage: "ship <dir|batch> --to preview|prod|both [--draft] [--note <text>]",
    summary: "upload missing cover bytes and apply one CatalogBatchV2; --dry-run posts that transaction and prints the server report",
    options: {
      to: { type: "string", required: true, help: "preview, prod or both; implies --target (both: prod)", value: "<env>" },
      draft: { type: "boolean", help: "apply the batch without publishing" },
      note: { type: "string", help: "release note", value: "<text>" },
      batch: { type: "boolean", help: "removed: a directory is already one apply" },
      bulk: { type: "boolean", help: "removed: a directory is already one apply" },
      concurrency: { type: "string", help: "removed with --bulk", value: "<n>" },
    },
    positionals: { min: 1, max: 1 },
    routes: SHIP_ROUTES,
    target: shipTarget,
    async run(context) {
      if (context.args.options.batch === true || context.args.options.bulk === true || context.args.options.concurrency !== undefined) throw new UsageError(REMOVED);
      const inputPath = context.args.positionals[0] ?? "";
      let info;
      try { info = statSync(inputPath); }
      catch { throw new UsageError(`Cannot read ${inputPath}.`); }
      if (info.isDirectory()) {
        await shipBundleDirectory(context, inputPath);
        return;
      }
      if (isCatalogBatchFile(context, inputPath)) {
        await shipBatchFile(context, inputPath);
        return;
      }
      throw new UsageError("ship takes a directory of CourseBundleV1 files or a CatalogBatchV2 file.");
    },
  },
];
