import { bundleCommands } from "./commands/bundle.ts";
import { batchApplyCommands } from "./commands/batch-apply.ts";
import { shipCommands } from "./commands/ship.ts";
import { lifecycleCommands } from "./commands/lifecycle.ts";
import { courseCommands } from "./commands/courses.ts";
import { coverCommands } from "./commands/covers.ts";
import { mediaCommands } from "./commands/media.ts";
import { editionCommands } from "./commands/editions.ts";
import { importCommands } from "./commands/imports.ts";
import { authorCommands, lessonCommands } from "./commands/lessons.ts";
import { authorCoverCommands } from "./commands/author-cover.ts";
import { universityCoverCommands } from "./commands/university-cover.ts";
import { opsCommands } from "./commands/ops.ts";
import { referenceCommands } from "./commands/reference.ts";
import { homeCommands, releaseCommands } from "./commands/releases.ts";
import { textCommands } from "./commands/texts.ts";
import type { CommandSpec } from "./context.ts";
import { UsageError } from "./errors.ts";

/** Commands that exist to say why they cannot (no API route by design); the route-coverage guardian allows only these. */
export const REFUSALS: CommandSpec[] = [
  {
    name: "license set", usage: "license set <code> …", summary: "not available: licenses have no PATCH route by design", options: {}, positionals: { min: 0, max: 20 }, routes: [],
    run() {
      return Promise.reject(new UsageError("Licenses have no PATCH route by design (docs/catalog/admin-api.md): published releases name them. Create a new one with license create and repoint courses with course set --license-code."));
    },
  },
  {
    name: "home cover",
    usage: "home cover <row> …",
    summary: "removed: a university cover ships inside the batch",
    options: {
      file: { type: "string", help: "removed", value: "<img>" },
      alt: { type: "string", help: "removed", value: "<text>" },
      credit: { type: "string", help: "removed", value: "<text>" },
      "source-url": { type: "string", help: "removed", value: "<url>" },
      license: { type: "string", help: "removed", value: "<text>" },
      note: { type: "string", help: "removed", value: "<text>" },
      clear: { type: "boolean", help: "removed" },
    },
    positionals: { min: 0, max: 20 },
    routes: [],
    run() {
      return Promise.reject(new UsageError("Removed: a university cover ships inside the batch. Use tower-catalog ship <dir|batch>."));
    },
  },
];

/** Every tower-catalog command, in help order (plan §3.3 plus audit, license, source, redirect). */
export const COMMANDS: readonly CommandSpec[] = [
  ...importCommands, ...textCommands.filter((command) => command.name === "draft-copy"), ...textCommands.filter((command) => command.name.startsWith("texts ")),
  ...courseCommands.filter((command) => command.name === "review"), ...textCommands.filter((command) => command.name === "approve"), ...coverCommands, ...mediaCommands,
  ...courseCommands.filter((command) => ["preview-url", "status", "publish", "unpublish"].includes(command.name)),
  ...courseCommands.filter((command) => command.name.startsWith("course ")), ...editionCommands, ...lessonCommands, ...authorCommands, ...authorCoverCommands,
  ...homeCommands, ...universityCoverCommands, ...releaseCommands, ...bundleCommands, ...batchApplyCommands, ...shipCommands, ...lifecycleCommands, ...opsCommands, ...referenceCommands, ...REFUSALS,
];

/** The command named by the first one or two words of argv, and the rest. */
export function resolveCommand(argv: readonly string[]): { command: CommandSpec; rest: string[] } | null {
  for (const words of [2, 1]) {
    const name = argv.slice(0, words).join(" ");
    const command = COMMANDS.find((entry) => entry.name === name || entry.aliases?.includes(name));
    if (command) return { command, rest: argv.slice(words) };
  }
  return null;
}
