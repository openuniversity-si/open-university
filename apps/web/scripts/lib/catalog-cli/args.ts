import type { z } from "zod";
import { UsageError } from "./errors.ts";

export interface OptionSpec {
  readonly type: "string" | "boolean";
  readonly help: string;
  readonly required?: boolean;
  /** May repeat; the value is then a list. */
  readonly repeat?: boolean;
  /** Help placeholder (`<id>`). */
  readonly value?: string;
}
export type OptionSpecs = Readonly<Record<string, OptionSpec>>;
export type OptionValue = string | boolean | readonly string[] | undefined;

export interface ParsedArgs {
  readonly positionals: readonly string[];
  readonly options: Readonly<Record<string, OptionValue>>;
}

/** Options every command takes (docs/catalog/cli.md). */
export const GLOBAL_OPTIONS = {
  target: { type: "string", help: "preview | staging | prod (required; no default)", value: "<t>" },
  json: { type: "boolean", help: "print the API envelope (ok/data/requestId) instead of tables" },
  "dry-run": { type: "boolean", help: "show method, route and body of each change without sending it (reads still run)" },
  yes: { type: "boolean", help: "answer y to the confirmation (required outside a terminal)" },
  "idempotency-key": { type: "string", help: "fix the Idempotency-Key of the first keyed request", value: "<k>" },
  "idem-nonce": { type: "string", help: "a new intent window for the deterministic Idempotency-Key (default: the UTC day)", value: "<n>" },
  help: { type: "boolean", help: "show this command's usage" },
} as const satisfies OptionSpecs;
/** Global flags that change how a command prints or asks, not what it asks the API: left out of the idempotency intent. */
export const NON_INTENT_OPTIONS = new Set(["json", "dry-run", "yes", "idempotency-key", "help", "target"]);

/** `--name value`, `--name=value`, `--flag`, `--` ends options. Unknown options and missing values are usage errors. */
export function parseArgv(argv: readonly string[], specs: OptionSpecs, positionals: { readonly min: number; readonly max: number }, usage: string): ParsedArgs {
  const options: Record<string, OptionValue> = {};
  const rest: string[] = [];
  let onlyPositionals = false;
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index] ?? "";
    if (onlyPositionals || !token.startsWith("--")) { rest.push(token); continue; }
    if (token === "--") { onlyPositionals = true; continue; }
    const equals = token.indexOf("=");
    const name = token.slice(2, equals === -1 ? undefined : equals);
    const spec = specs[name];
    if (!spec) throw new UsageError(`Unknown option --${name}. ${usage}`);
    let value: string | boolean;
    if (spec.type === "boolean") {
      if (equals !== -1) throw new UsageError(`--${name} takes no value.`);
      value = true;
    } else {
      const next = equals === -1 ? argv[index + 1] : token.slice(equals + 1);
      if (next === undefined || (equals === -1 && next.startsWith("--"))) throw new UsageError(`--${name} needs a value.`);
      if (equals === -1) index += 1;
      value = next;
    }
    const previous = options[name];
    if (previous !== undefined && !spec.repeat) throw new UsageError(`--${name} given twice.`);
    options[name] = spec.repeat ? [...(Array.isArray(previous) ? previous as string[] : []), String(value)] : value;
  }
  for (const [name, spec] of Object.entries(specs)) if (spec.required && options[name] === undefined) throw new UsageError(`--${name} is required. ${usage}`);
  if (rest.length < positionals.min || rest.length > positionals.max) throw new UsageError(`Expected ${positionals.min === positionals.max ? String(positionals.min) : `${String(positionals.min)}–${String(positionals.max)}`} argument(s), got ${String(rest.length)}. ${usage}`);
  return { positionals: rest, options };
}

export function stringOption(args: ParsedArgs, name: string): string | undefined {
  const value = args.options[name];
  return typeof value === "string" ? value : undefined;
}
export function requireOption(args: ParsedArgs, name: string): string {
  const value = stringOption(args, name);
  if (value === undefined || value.trim() === "") throw new UsageError(`--${name} is required.`);
  return value;
}
export function flag(args: ParsedArgs, name: string): boolean { return args.options[name] === true; }
export function listOption(args: ParsedArgs, name: string): string[] | undefined {
  const value = stringOption(args, name);
  if (value === undefined) return undefined;
  const items = value.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
  if (items.length === 0) throw new UsageError(`--${name} needs a comma-separated list.`);
  return items;
}
export function intOption(args: ParsedArgs, name: string, min = 1): number | undefined {
  const value = stringOption(args, name);
  if (value === undefined) return undefined;
  if (!/^\d{1,9}$/.test(value) || Number(value) < min) throw new UsageError(`--${name} must be an integer ≥ ${String(min)}.`);
  return Number(value);
}
export function positional(args: ParsedArgs, index: number, name: string): string {
  const value = args.positionals[index];
  if (value === undefined) throw new UsageError(`Missing <${name}>.`);
  return value;
}

// ---- Options derived from a contracts.ts object schema (create/set commands) ----

export const kebab = (name: string) => name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
interface FieldShape { readonly kind: "string" | "number" | "boolean" | "enum" | "other"; readonly nullable: boolean; readonly values: readonly string[] }

function fieldShape(schema: z.ZodType): FieldShape {
  let current = schema as unknown as { def: { type: string; innerType?: unknown; in?: unknown; entries?: Record<string, string> } };
  let nullable = false;
  for (;;) {
    const def = current.def;
    if (def.type === "optional" || def.type === "default") current = def.innerType as typeof current;
    else if (def.type === "nullable") { nullable = true; current = def.innerType as typeof current; }
    else if (def.type === "pipe") current = def.in as typeof current;
    else break;
  }
  const type = current.def.type;
  if (type === "string" || type === "number" || type === "boolean") return { kind: type, nullable, values: [] };
  if (type === "enum") return { kind: "enum", nullable, values: Object.values(current.def.entries ?? {}) };
  return { kind: "other", nullable, values: [] };
}

function shapeOf(schema: z.ZodType): Record<string, z.ZodType> {
  const shape = (schema as unknown as { shape?: Record<string, z.ZodType> }).shape;
  if (!shape) throw new Error("Field options need an object schema.");
  return shape;
}

/** One `--kebab-name <value>` per scalar field of `schema` (minus `exclude`), and `--unset <field>` when one is nullable. */
export function fieldOptions(schema: z.ZodType, exclude: readonly string[] = []): OptionSpecs {
  const specs: Record<string, OptionSpec> = {};
  let nullable = false;
  for (const [name, field] of Object.entries(shapeOf(schema))) {
    if (exclude.includes(name)) continue;
    const shape = fieldShape(field);
    if (shape.kind === "other") continue;
    nullable ||= shape.nullable;
    specs[kebab(name)] = { type: "string", help: shape.kind === "enum" ? shape.values.join(" | ") : shape.kind, value: shape.kind === "number" ? "<n>" : shape.kind === "boolean" ? "true|false" : "<value>" };
  }
  if (nullable) specs.unset = { type: "string", repeat: true, help: "clear a nullable field (repeatable)", value: "<field>" };
  return specs;
}

/** The body fields given as options, typed by the schema (numbers, booleans; `--unset x` = null). Zod validates the rest. */
export function fieldValues(schema: z.ZodType, args: ParsedArgs, exclude: readonly string[] = []): Record<string, unknown> {
  const shape = shapeOf(schema);
  const values: Record<string, unknown> = {};
  for (const [name, field] of Object.entries(shape)) {
    if (exclude.includes(name)) continue;
    const raw = stringOption(args, kebab(name));
    if (raw === undefined) continue;
    const kind = fieldShape(field).kind;
    if (kind === "number") {
      if (!/^-?\d+(?:\.\d+)?$/.test(raw)) throw new UsageError(`--${kebab(name)} must be a number.`);
      values[name] = Number(raw);
    } else if (kind === "boolean") {
      if (raw !== "true" && raw !== "false") throw new UsageError(`--${kebab(name)} must be true or false.`);
      values[name] = raw === "true";
    } else values[name] = raw;
  }
  const unset = args.options.unset;
  for (const option of Array.isArray(unset) ? unset as string[] : []) {
    const name = Object.keys(shape).find((key) => key === option || kebab(key) === option);
    if (name === undefined || exclude.includes(name) || !fieldShape(shape[name] as z.ZodType).nullable) throw new UsageError(`--unset ${option}: not a nullable field.`);
    if (name in values) throw new UsageError(`--${kebab(name)} and --unset ${option} conflict.`);
    values[name] = null;
  }
  return values;
}
