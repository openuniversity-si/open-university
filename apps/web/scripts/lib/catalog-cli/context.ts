import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { sha256Hex } from "../../../src/kernel/canonical.ts";
import type { OEmbed } from "../../../src/playback/server/oembed-resolver.ts";
import { flag, type OptionSpecs, type ParsedArgs } from "./args.ts";
import type { ApiClient } from "./client.ts";
import { UsageError } from "./errors.ts";
import type { Output } from "./io.ts";
import type { Target } from "./target.ts";

/** A child process (tower-media, git, gh): the secret is never in its argv, and the environment it gets is scrubbed. */
export type Runner = (command: string, args: readonly string[], options?: { readonly cwd?: string; readonly inherit?: boolean }) => Promise<{ readonly code: number; readonly stdout: string; readonly stderr: string }>;

export interface CommandDeps {
  readonly now: () => Date;
  readonly sleep: (ms: number) => Promise<void>;
  readonly oembed: OEmbed;
  readonly run: Runner;
  /** apps/web of this checkout (current API exports use an explicit external directory). */
  readonly appRoot: string;
  /** Home directory for `media install` (the wrapper's environment, not a secret). */
  readonly home?: string;
  /** Public image fetches for `media check`. The check GETs; it does not HEAD the public host. */
  readonly fetchPublic?: (url: string, init?: RequestInit) => Promise<Response>;
}

export interface Context {
  readonly command: string;
  readonly target: Target;
  readonly client: ApiClient;
  readonly out: Output;
  readonly args: ParsedArgs;
  readonly deps: CommandDeps;
  readonly dryRun: boolean;
  /**
   * Asks before a change: on prod always, elsewhere when `dangerous` (publish, unpublish, activate, approve, home set,
   * confirmed deletes). y/N in a terminal, `--yes` outside one (else exit 2 before anything is sent). Under --dry-run it
   * returns at once: the client prints the change instead of sending it. Only this unlocks the client's guard.
   */
  confirm(question: string, dangerous?: boolean): Promise<void>;
  /** Reads a file the command depends on; its sha256 joins the idempotency intent (a changed file = a new key). */
  readText(path: string): string;
  /**
   * Read-only clients of the environments sharing this one's R2 bucket (prod ↔ preview; staging checks both), for the
   * byte checks of `--delete-bytes`. Throws a UsageError when one has no URL or credentials.
   */
  peers(): { readonly target: Target; readonly client: ApiClient }[];
  /**
   * A full client of another target, with that target's URL and admin key (`ship --to both`). It shares this command's
   * confirmation: once `confirm` passed, it may mutate too. The command's own target returns `client`.
   */
  clientFor(target: Target): ApiClient;
}

export interface CommandSpec {
  /** `course create`, `publish`… */
  readonly name: string;
  /** Other names that resolve to this command (`lesson update`). */
  readonly aliases?: readonly string[];
  readonly usage: string;
  readonly summary: string;
  readonly options: OptionSpecs;
  readonly positionals: { readonly min: number; readonly max: number };
  /** Every admin route the command may call; tower-catalog.test.ts checks the union covers every route of the API. */
  readonly routes: readonly string[];
  /** The target when the command's own options imply it (`ship --to prod`); default: `--target`, required. */
  target?(args: ParsedArgs): Target;
  run(context: Context): Promise<void>;
}

export function createContext(input: {
  command: string; target: Target; client: ApiClient; out: Output; args: ParsedArgs; deps: CommandDeps;
  prompt: ((question: string) => Promise<string>) | null; files: Map<string, string>;
  peers?: () => { readonly target: Target; readonly client: ApiClient }[];
  clientFor?: (target: Target) => ApiClient;
}): Context {
  const { client, args, out, prompt, files, target } = input;
  const dryRun = flag(args, "dry-run");
  const others = new Map<Target, ApiClient>();
  return {
    command: input.command, target, client, out, args, deps: input.deps, dryRun,
    async confirm(question, dangerous = false) {
      // --yes counts under --dry-run too: ship stages cover bytes on prod before the server rolls the catalog back.
      if (flag(args, "yes")) { client.confirmed = true; for (const other of others.values()) other.confirmed = true; return; }
      if (dryRun || (!dangerous && target !== "prod")) return;
      if (prompt === null) throw new UsageError(`${question} on ${target}: pass --yes outside a terminal; nothing was sent.`);
      const answer = (await prompt(`${question} on ${target.toUpperCase()}? [y/N] `)).trim().toLowerCase();
      if (answer !== "y" && answer !== "yes") throw new UsageError("Aborted; nothing was sent.");
      client.confirmed = true;
      for (const other of others.values()) other.confirmed = true;
    },
    readText(path) {
      const full = resolve(path);
      let text: string;
      try { text = readFileSync(full, "utf8"); } catch { throw new UsageError(`Cannot read ${path}.`); }
      files.set(path, sha256Hex(text));
      return text;
    },
    peers() {
      if (!input.peers) throw new UsageError("No other environment is configured.");
      return input.peers();
    },
    clientFor(other) {
      if (other === target) return client;
      const known = others.get(other);
      if (known) return known;
      if (!input.clientFor) throw new UsageError(`No client for --target ${other} is configured.`);
      const created = input.clientFor(other);
      created.confirmed = client.confirmed;
      others.set(other, created);
      return created;
    },
  };
}

/** JSON from a file the user gave, with the file named in the error (never its content). */
export function parseJsonFile(context: Context, path: string): unknown {
  const text = context.readText(path);
  try { return JSON.parse(text) as unknown; } catch { throw new UsageError(`${path} is not valid JSON.`); }
}
