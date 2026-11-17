import { TEXT_FIELDS, type ReleasePresence, type TextField } from "../../kernel/text-fields.ts";
import { undrawablePageText } from "../../site/domain/page-characters.ts";

export type { ReleasePresence, TextField };
export { TEXT_FIELDS };

/**
 * Text keys a release carries, in leaf order. A nullable key is always emitted, including null.
 * An optional key is omitted when it has no text, so a stored release without that key still parses.
 */
export function releaseTextEntries(
  specs: Readonly<Record<string, Pick<TextField, "release">>>,
  valueOf: (name: string, release: ReleasePresence) => string | null,
): Record<string, string | null> {
  const entries: [string, string | null][] = [];
  for (const [name, spec] of Object.entries(specs)) {
    if (spec.release === "off") continue;
    const value = valueOf(name, spec.release);
    if (spec.release === "optional" && value === null) continue;
    entries.push([name, value]);
  }
  return Object.fromEntries(entries);
}

/** Course fields the incremental compile stores, including About. Key order is the object above. */
export const COURSE_TEXT_FIELDS = Object.keys(TEXT_FIELDS.course) as (keyof typeof TEXT_FIELDS.course)[];

/** Course fields copied into a release. About is stored beside them and is not required to publish. */
export const COURSE_TEXTS = COURSE_TEXT_FIELDS.filter((name) => TEXT_FIELDS.course[name].publish);

export type TextEntityKind = keyof typeof TEXT_FIELDS;
export const TEXT_ENTITY_KINDS = Object.keys(TEXT_FIELDS) as TextEntityKind[];

export function textField(kind: string, name: string): TextField | undefined {
  const fields: Readonly<Record<string, TextField>> | undefined = (TEXT_FIELDS as Readonly<Record<string, Readonly<Record<string, TextField>>>>)[kind];
  return fields?.[name];
}

export function textFieldNames(kind: TextEntityKind): string[] {
  return Object.keys(TEXT_FIELDS[kind]);
}

export interface TextIssue {
  readonly rule: "texts.empty" | "texts.limit" | "texts.charset" | "texts.field";
  readonly message: string;
}

/** Why `text` cannot fill `kind.name`; empty when it can. Messages name lengths and code points, never the text. */
export function textIssues(kind: string, name: string, text: string): TextIssue[] {
  const spec = textField(kind, name);
  if (!spec) return [{ rule: "texts.field", message: `${kind} has no text field ${name}.` }];
  const issues: TextIssue[] = [];
  if (text.trim().length === 0) issues.push({ rule: "texts.empty", message: `${kind}.${name} is empty.` });
  const length = Array.from(text).length;
  if (length > spec.maxChars) issues.push({ rule: "texts.limit", message: `${kind}.${name} has ${String(length)} characters; the slot holds ${String(spec.maxChars)}.` });
  const undrawable = undrawablePageText(kind, name, text);
  if (undrawable !== null) issues.push({ rule: "texts.charset", message: undrawable });
  return issues;
}
