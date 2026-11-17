import { DEFAULT_ACTOR, type PreconditionFailure } from "../../../src/catalog/domain/contracts.ts";
import { GLOBAL_OPTIONS, NON_INTENT_OPTIONS, parseArgv, stringOption, type OptionSpecs } from "./args.ts";
import { ApiClient, validateFixedKey, type Transport } from "./client.ts";
import { createContext, type CommandDeps, type CommandSpec } from "./context.ts";
import { ApiError, CliError, DryRunHalt, EXIT } from "./errors.ts";
import { Output, type Io } from "./io.ts";
import { redact } from "./redact.ts";
import { installTowerMedia } from "./commands/media.ts";
import { COMMANDS, resolveCommand } from "./registry.ts";
import { preconditionLines } from "./render.ts";
import { parseTarget, peerTargets, targetOrigin, type Target } from "./target.ts";

export interface MainDeps extends CommandDeps {
  readonly io: Io;
  readonly env: Readonly<Record<string, string | undefined>>;
  readonly hostname: string;
  readonly uuid: () => string;
  /** The authenticated transport for a target (throws a UsageError naming what is missing). */
  transport(target: Target): Transport;
  /** Secret values to scrub from every line printed (known once transport() ran). */
  secrets(): readonly string[];
}

/** `cli:tower-catalog@<hostname>`, within X-Tower-Actor's `^[a-z0-9:@._ -]{1,64}$`. */
export function actorFor(hostname: string): string {
  const host = hostname.toLowerCase().replace(/[^a-z0-9.-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
  return `${DEFAULT_ACTOR}@${host}`.slice(0, 64);
}

function optionHelp(options: OptionSpecs): string[] {
  return Object.entries(options).map(([name, spec]) => `  --${name}${spec.type === "string" ? ` ${spec.value ?? "<value>"}` : ""}${spec.required ? " (required)" : ""}${spec.repeat ? " (repeatable)" : ""}  ${spec.help}`);
}

export function helpText(command?: CommandSpec): string {
  if (command) return [`usage: tower-catalog ${command.usage}${command.target ? " [--target preview|staging|prod]" : " --target preview|staging|prod"}`, command.summary, "", "options:", ...optionHelp(command.options), ...optionHelp(GLOBAL_OPTIONS)].join("\n");
  const width = Math.max(...COMMANDS.map((entry) => entry.name.length));
  return [
    "tower-catalog: operate The Tower's dynamic catalog through the admin API (docs/catalog/cli.md).",
    "usage: tower-catalog <command> … --target preview|staging|prod [--json] [--dry-run] [--yes]", "",
    ...COMMANDS.map((entry) => `  ${entry.name.padEnd(width)}  ${entry.summary}`),
    `  ${"install".padEnd(width)}  copy the wrapper to ~/.local/bin/tower-catalog`, "",
    "Exit codes: 0 ok · 1 API error · 2 usage · 3 conflict (409) · 4 preconditions (412) · 5 unprocessable (422) · 6 401/429/503 · 7 network/timeout.",
    "tower-catalog <command> --help shows a command's options.",
  ].join("\n");
}

/** Canonical arguments for the idempotency intent: positionals and options that change the request, sorted. */
function intentArgs(positionals: readonly string[], options: Readonly<Record<string, unknown>>): unknown {
  return { positionals, options: Object.fromEntries(Object.entries(options).filter(([name, value]) => !NON_INTENT_OPTIONS.has(name) && value !== undefined).sort(([a], [b]) => a.localeCompare(b))) };
}

/** The `error.code` of a failure without an API envelope: its exit class (`usage`, `network`, `conflict`…). */
function exitName(code: number): string {
  return Object.entries(EXIT).find(([, value]) => value === code)?.[0] ?? "api";
}

function report(error: unknown, out: Output): number {
  if (error instanceof DryRunHalt) { out.finish(true); return EXIT.ok; }
  if (error instanceof ApiError) {
    out.note(`tower-catalog: ${error.message}`);
    const details = error.details as { failed?: PreconditionFailure[]; currentRevision?: number } | undefined;
    if (error.code === "preconditions_failed" && Array.isArray(details?.failed)) out.note([`Unmet preconditions (${String(details.failed.length)}):`, ...preconditionLines(details.failed)].join("\n"));
    else if (error.code === "revision_conflict" && typeof details?.currentRevision === "number") out.note(`Current revision: ${String(details.currentRevision)}. Read it again (review, course get) and re-run; changes are not retried blindly.`);
    else if (details !== undefined) out.note(`details: ${JSON.stringify(redact(details), null, 2)}`);
    if (error.envelope !== null) out.result(error.envelope);
    else out.fail(error.code, error.message);
    return error.exitCode;
  }
  if (error instanceof CliError) {
    out.note(`tower-catalog: ${error.message}`);
    out.fail(exitName(error.exitCode), error.message);
    return error.exitCode;
  }
  const message = `unexpected ${error instanceof Error ? `${error.name}: ${error.message}` : "failure"}`;
  out.note(`tower-catalog: ${message}`);
  out.fail("unexpected", message);
  return EXIT.api;
}

/** Runs one command line; never throws. The exit code follows errors.ts EXIT. */
export async function main(argv: readonly string[], deps: MainDeps): Promise<number> {
  // --json answers one envelope even for a usage error found before the command parses its options.
  const earlyOut = new Output(deps.io, argv.includes("--json"), []);
  const [first] = argv;
  if (first === undefined || first === "help" || first === "--help" || first === "-h") {
    const named = first === "help" ? resolveCommand(argv.slice(1))?.command : undefined;
    deps.io.stdout(`${helpText(named)}\n`);
    return first === undefined ? EXIT.usage : EXIT.ok;
  }
  const resolved = resolveCommand(argv);
  if (!resolved) {
    const message = `unknown command "${argv.slice(0, 2).join(" ")}". Run tower-catalog --help.`;
    earlyOut.note(`tower-catalog: ${message}`);
    earlyOut.fail("usage", message);
    return EXIT.usage;
  }
  const { command, rest } = resolved;
  let out = earlyOut;
  try {
    if (rest.includes("--help")) { deps.io.stdout(`${helpText(command)}\n`); return EXIT.ok; }
    if (command.name === "media" && rest[0] === "install") { await installTowerMedia(deps.appRoot, deps.env.HOME); deps.io.stdout("installed ~/.local/bin/tower-media\n"); return EXIT.ok; }
    const args = parseArgv(rest, { ...GLOBAL_OPTIONS, ...command.options }, command.positionals, `Usage: tower-catalog ${command.usage}`);
    const target = command.target ? command.target(args) : parseTarget(stringOption(args, "target"));
    const origin = targetOrigin(target, deps.env);
    const transport = deps.transport(target);
    out = new Output(deps.io, args.options.json === true, deps.secrets());
    const files = new Map<string, string>();
    const window = stringOption(args, "idem-nonce") ?? deps.now().toISOString().slice(0, 10);
    const client = new ApiClient({
      origin, target, transport, actor: actorFor(deps.hostname), uuid: deps.uuid, sleep: deps.sleep, dryRun: args.options["dry-run"] === true, out,
      fixedKey: validateFixedKey(stringOption(args, "idempotency-key")),
      intent: () => ({ command: command.name, args: intentArgs(args.positionals, args.options), files: Object.fromEntries([...files].sort(([a], [b]) => a.localeCompare(b))), window }),
    });
    // Peers only read (POST /media/references); they never mutate, so no confirmation or idempotency key is involved.
    const peers = () => peerTargets(target).map((peer) => ({ target: peer, client: new ApiClient({
      origin: targetOrigin(peer, deps.env), target: peer, transport: deps.transport(peer), actor: actorFor(deps.hostname), uuid: deps.uuid, sleep: deps.sleep, dryRun: false, out,
      fixedKey: undefined, intent: () => ({ command: command.name, args: [], files: {}, window }),
    }) }));
    // Another target's full client (ship --to both): its own URL and admin key, the same intent and dry-run.
    const clientFor = (other: Target) => new ApiClient({
      origin: targetOrigin(other, deps.env), target: other, transport: deps.transport(other), actor: actorFor(deps.hostname), uuid: deps.uuid, sleep: deps.sleep, dryRun: args.options["dry-run"] === true, out,
      fixedKey: validateFixedKey(stringOption(args, "idempotency-key")),
      intent: () => ({ command: command.name, args: intentArgs(args.positionals, args.options), files: Object.fromEntries([...files].sort(([a], [b]) => a.localeCompare(b))), window }),
    });
    const context = createContext({ command: command.name, target, client, out, args, deps, prompt: deps.io.prompt, files, peers, clientFor });
    await command.run(context);
    out.finish(false);
    return EXIT.ok;
  } catch (error) {
    return report(error, out);
  }
}
