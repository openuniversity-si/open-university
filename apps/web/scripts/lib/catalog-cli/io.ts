import { redact, redactText, scrub } from "./redact.ts";

/** Where tower-catalog writes and how it asks; tests pass buffers and a scripted prompt. */
export interface Io {
  stdout(text: string): void;
  stderr(text: string): void;
  /** Asks one question on the terminal; null when stdin or stderr is not a TTY (then changes need --yes). */
  readonly prompt: ((question: string) => Promise<string>) | null;
}

/** `{ok, data}` or `{ok:false, error}`, with or without the API's requestId. */
function isEnvelope(value: unknown): boolean {
  if (typeof value !== "object" || value === null || !("ok" in value)) return false;
  return (value.ok === true && "data" in value) || (value.ok === false && "error" in value);
}

/**
 * Every byte tower-catalog prints goes through here: known secret values are replaced, `token=`/Bearer values and
 * sensitive keys are redacted, and `--json` keeps stdout to exactly one envelope, `{ok, data}` or `{ok:false, error}`.
 * Only `secretOutput` (preview-url) prints a preview token, and only to stdout.
 */
export class Output {
  private readonly io: Io;
  private readonly secrets: readonly string[];
  readonly json: boolean;
  private printed = false;
  /** Under --json, the human lines of a command that has no result of its own: `finish` sends them as `data.lines`. */
  private readonly captured: string[] = [];

  constructor(io: Io, json: boolean, secrets: readonly string[]) {
    this.io = io;
    this.json = json;
    this.secrets = secrets;
  }

  /** Human output (stdout); silent under --json. */
  line(text = ""): void {
    if (this.json) this.captured.push(this.clean(text));
    else this.io.stdout(`${this.clean(text)}\n`);
  }

  lines(texts: readonly string[]): void {
    for (const text of texts) this.line(text);
  }

  /** Progress, warnings, dry-run plans and errors (stderr), in both modes. */
  note(text: string): void {
    this.io.stderr(`${this.clean(text)}\n`);
  }

  /** The `--json` answer: the API envelope as it came (redacted), or the command's own report as `{ok: true, data}`. */
  result(value: unknown): void {
    if (!this.json || this.printed) return;
    this.printed = true;
    this.io.stdout(`${scrub(JSON.stringify(redact(isEnvelope(value) ? value : { ok: true, data: value }), null, 2), this.secrets)}\n`);
  }

  /** A command that ended without a result still answers one envelope: its lines, and whether it was a dry run. */
  finish(dryRun: boolean): void {
    this.result({ ok: true, data: { lines: this.captured, ...(dryRun ? { dryRun } : {}) } });
  }

  /** A failure with no API envelope (usage, network, a local check): `{ok:false, error:{code, message}}`. */
  fail(code: string, message: string): void {
    this.result({ ok: false, error: { code, message } });
  }

  /** A value that is itself a short-lived secret the user asked for (a preview URL): stdout only, never redacted. */
  secretOutput(text: string, envelope: unknown): void {
    this.printed = true;
    this.io.stdout(`${scrub(this.json ? JSON.stringify(envelope, null, 2) : text, this.secrets)}\n`);
  }


  private clean(text: string): string {
    return redactText(scrub(text, this.secrets));
  }
}
