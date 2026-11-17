import { AppError } from "../../src/kernel/errors.ts";
import { convertCurated, type FactoryText } from "../../src/factory/domain/convert.ts";
import { parseCurated, type CuratedIssue } from "../../src/factory/domain/curated.ts";
import { parseFactoryTexts, reviewTexts, textsFromCurated } from "../../src/factory/domain/texts.ts";
import type { AdapterInput, KeyValueCache } from "../../src/factory/ports/source-adapter.ts";
import { createYouTubePlaylistAdapter } from "../../src/factory/server/youtube-adapter.ts";

// tower-factory (docs/architecture/FACTORY.md). Reads a curated/v1 file and prints a batch. It does not open the database.
// ingest reads YOUTUBE_API_KEY from the runtime the operator passed in. It never prints that key.

export interface FactoryIo {
  stdout(text: string): void;
  stderr(text: string): void;
  readFile(path: string): Promise<string>;
}

/** Operator environment and the HTTP client. Tests pass both. Absent key means ingest makes no request. */
export interface FactoryRuntime {
  readonly env?: Readonly<Record<string, string | undefined>>;
  readonly fetch?: typeof fetch;
  readonly now?: () => Date;
}

const HELP = [
  "tower-factory: check a curated/v1 file and convert it into a CatalogBatchV2.",
  "usage: tower-factory validate <file> [--json]",
  "       tower-factory convert <file> [--texts <file>] [--json]",
  "       tower-factory ingest <spec.json> [--json]",
  "       tower-factory texts <file> --language <language> --noun <noun> [--json]",
  "       tower-factory review <texts.json> [--json]",
  "       tower-factory --help",
].join("\n");

interface ParsedArgs {
  readonly command: string;
  readonly file: string | null;
  readonly texts: string | null;
  readonly language: string | null;
  readonly noun: string | null;
  readonly json: boolean;
  readonly help: boolean;
}

function parseArgs(argv: readonly string[]): ParsedArgs | string {
  let command = "";
  let file: string | null = null;
  let texts: string | null = null;
  let language: string | null = null;
  let noun: string | null = null;
  let json = false;
  let help = false;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index] ?? "";
    if (arg === "--json") json = true;
    else if (arg === "--help" || arg === "-h") help = true;
    else if (arg === "--texts" || arg === "--language" || arg === "--noun") {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("--")) return `${arg} needs a value`;
      if (arg === "--texts") texts = value;
      else if (arg === "--language") language = value;
      else noun = value;
      index += 1;
    } else if (arg.startsWith("--")) return `unknown option ${arg}`;
    else if (command === "") command = arg;
    else if (file === null) file = arg;
    else return `unexpected argument ${arg}`;
  }
  return { command, file, texts, language, noun, json, help };
}

function envelope(ok: true, data: unknown): string;
function envelope(ok: false, error: { readonly code: string; readonly message: string; readonly issues?: readonly CuratedIssue[] }): string;
function envelope(ok: boolean, payload: unknown): string {
  const body = ok ? { ok: true, data: payload } : { ok: false, error: payload };
  return `${JSON.stringify(body, null, 2)}\n`;
}

async function readJson(io: FactoryIo, path: string): Promise<{ readonly ok: true; readonly value: unknown } | { readonly ok: false; readonly message: string }> {
  let text: string;
  try { text = await io.readFile(path); } catch { return { ok: false, message: `cannot read ${path}` }; }
  try { return { ok: true, value: JSON.parse(text) as unknown }; } catch { return { ok: false, message: `${path}: not JSON` }; }
}

function fail(io: FactoryIo, json: boolean, issues: readonly CuratedIssue[], code = "unprocessable"): number {
  const message = issues.map((issue) => issue.message).join("\n");
  if (json) io.stdout(envelope(false, { code, message, issues }));
  else io.stderr(`${message}\n`);
  return 1;
}

export async function runFactory(argv: readonly string[], io: FactoryIo, runtime: FactoryRuntime = {}): Promise<number> {
  const parsed = parseArgs(argv);
  if (typeof parsed === "string") {
    io.stderr(`tower-factory: ${parsed}\n${HELP}\n`);
    return 2;
  }
  if (parsed.help || parsed.command === "" || parsed.command === "help") {
    io.stdout(`${HELP}\n`);
    return 0;
  }
  if (!["validate", "convert", "ingest", "texts", "review"].includes(parsed.command)) {
    io.stderr(`tower-factory: unknown command ${parsed.command}\n${HELP}\n`);
    return 2;
  }
  if (parsed.file === null) {
    io.stderr(`tower-factory: ${parsed.command} needs a file\n`);
    return 2;
  }
  if (parsed.command === "ingest") return ingestSpec(parsed.file, parsed.json, io, runtime);
  if (parsed.command === "texts") {
    if (parsed.language === null || parsed.language.trim() === "" || parsed.noun === null || parsed.noun.trim() === "") {
      io.stderr("tower-factory: texts needs --language and --noun\n");
      return 2;
    }
    return writeTexts(parsed.file, parsed.language, parsed.noun, parsed.json, io);
  }
  if (parsed.command === "review") return reviewFile(parsed.file, parsed.json, io, runtime);
  const loaded = await readJson(io, parsed.file);
  if (!loaded.ok) return fail(io, parsed.json, [{ name: "curated", message: loaded.message }]);
  const curated = parseCurated(loaded.value);
  if (!curated.ok) return fail(io, parsed.json, curated.issues);
  if (parsed.command === "validate") {
    const held = curated.value.courses.filter((course) => course.decision === "hold").length;
    const data = { run: curated.value.run.id, courses: curated.value.courses.length, held };
    if (parsed.json) io.stdout(envelope(true, data));
    else io.stdout(`${data.run}: ${String(data.courses)} courses, ${String(held)} held\n`);
    return 0;
  }
  let texts: FactoryText[] = [];
  if (parsed.texts !== null) {
    const file = await readJson(io, parsed.texts);
    if (!file.ok) return fail(io, parsed.json, [{ name: "texts", message: file.message }]);
    if (!Array.isArray(file.value)) return fail(io, parsed.json, [{ name: "texts", message: `${parsed.texts}: texts are a JSON array` }]);
    texts = file.value as FactoryText[];
  }
  try {
    const conversion = convertCurated(curated.value, texts);
    const data = { batch: conversion.batch, held: conversion.held, excluded: conversion.excluded };
    if (parsed.json) io.stdout(envelope(true, data));
    else {
      io.stdout(`${JSON.stringify(conversion.batch, null, 2)}\n`);
      io.stderr(`held ${String(conversion.held.length)}, excluded ${String(conversion.excluded)}\n`);
    }
    return 0;
  } catch (error) {
    const issues = error instanceof AppError && Array.isArray((error.details as { issues?: unknown } | undefined)?.issues)
      ? (error.details as { issues: CuratedIssue[] }).issues
      : [{ name: "batch", message: error instanceof Error ? error.message : "convert failed" }];
    return fail(io, parsed.json, issues);
  }
}

const SPEC_FIELDS = ["runId", "playlistId", "playlistTitle", "channelId", "channelTitle", "channelUrl"] as const;

function readSpec(value: unknown): { readonly ok: true; readonly value: Omit<AdapterInput, "apiKey"> } | { readonly ok: false; readonly issues: readonly CuratedIssue[] } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return { ok: false, issues: [{ name: "spec", message: "spec: expected an object" }] };
  const spec = value as Record<string, unknown>;
  const issues: CuratedIssue[] = [];
  for (const field of SPEC_FIELDS) {
    if (typeof spec[field] !== "string" || spec[field].trim() === "") issues.push({ name: field, message: `${field}: required` });
  }
  if (typeof spec.institution !== "object" || spec.institution === null || Array.isArray(spec.institution)) {
    issues.push({ name: "institution", message: "institution: required" });
  }
  if (issues.length > 0) return { ok: false, issues };
  return { ok: true, value: spec as Omit<AdapterInput, "apiKey"> };
}

function cache(): KeyValueCache {
  const values = new Map<string, string>();
  return {
    get: (key) => Promise.resolve(values.get(key) ?? null),
    set: (key, value) => { values.set(key, value); return Promise.resolve(); },
  };
}

function scrub(message: string, secret: string): string {
  return secret === "" ? message : message.split(secret).join("[redacted]");
}

async function ingestSpec(file: string, json: boolean, io: FactoryIo, runtime: FactoryRuntime): Promise<number> {
  const loaded = await readJson(io, file);
  if (!loaded.ok) return fail(io, json, [{ name: "spec", message: loaded.message }]);
  const spec = readSpec(loaded.value);
  if (!spec.ok) return fail(io, json, spec.issues);
  const apiKey = runtime.env?.YOUTUBE_API_KEY?.trim() ?? "";
  if (apiKey === "") {
    io.stderr("tower-factory: YouTube Data API key is missing. Set YOUTUBE_API_KEY in the operator secret store. ingest does not call YouTube without it.\n");
    return 2;
  }
  if (runtime.fetch === undefined) {
    io.stderr("tower-factory: ingest has no HTTP client.\n");
    return 2;
  }
  try {
    const curated = await createYouTubePlaylistAdapter().ingest(
      { ...spec.value, apiKey },
      { fetch: runtime.fetch, cache: cache(), now: runtime.now ?? (() => new Date()), concurrency: 1 },
    );
    if (json) io.stdout(envelope(true, curated));
    else io.stdout(`${JSON.stringify(curated, null, 2)}\n`);
    return 0;
  } catch (error) {
    const code = error instanceof AppError ? error.code : "upstream_failed";
    const raw = error instanceof AppError && Array.isArray((error.details as { issues?: unknown } | undefined)?.issues)
      ? (error.details as { issues: CuratedIssue[] }).issues
      : [{ name: "ingest", message: error instanceof Error ? error.message : "ingest failed" }];
    const issues = raw.map((issue) => ({ name: issue.name, message: scrub(issue.message, apiKey) }));
    if (code === "unconfigured") {
      io.stderr(`tower-factory: ${issues.map((issue) => issue.message).join("\n")}\n`);
      return 2;
    }
    return fail(io, json, issues, code);
  }
}

async function writeTexts(file: string, language: string, noun: string, json: boolean, io: FactoryIo): Promise<number> {
  const loaded = await readJson(io, file);
  if (!loaded.ok) return fail(io, json, [{ name: "curated", message: loaded.message }]);
  const curated = parseCurated(loaded.value);
  if (!curated.ok) return fail(io, json, curated.issues);
  const generated = textsFromCurated(curated.value, { language, noun });
  const checked = parseFactoryTexts([...generated.texts]);
  if (!checked.ok) return fail(io, json, checked.issues);
  const data = { texts: checked.texts, skipped: generated.skipped };
  if (json) io.stdout(envelope(true, data));
  else {
    io.stdout(`${JSON.stringify(checked.texts, null, 2)}\n`);
    io.stderr(`skipped ${String(generated.skipped.length)}\n`);
  }
  return 0;
}

async function reviewFile(file: string, json: boolean, io: FactoryIo, runtime: FactoryRuntime): Promise<number> {
  const loaded = await readJson(io, file);
  if (!loaded.ok) return fail(io, json, [{ name: "texts", message: loaded.message }]);
  const parsed = parseFactoryTexts(loaded.value);
  if (!parsed.ok) return fail(io, json, parsed.issues);
  const reviewed = reviewTexts(parsed.texts, (runtime.now ?? (() => new Date()))().toISOString());
  const checked = parseFactoryTexts(reviewed);
  if (!checked.ok) return fail(io, json, checked.issues);
  if (json) io.stdout(envelope(true, checked.texts));
  else io.stdout(`${JSON.stringify(checked.texts, null, 2)}\n`);
  return 0;
}
