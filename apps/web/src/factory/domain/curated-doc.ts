import { z } from "zod";
import { metaDot } from "../../site/domain/reader-copy.ts";
import { LIMITS } from "../../catalog/domain/schema/fields.ts";
import { curatedDocSchema } from "./curated.ts";

// docs/factory/curated-v1.md is rendered from the zod schema. The unit test fails when the file is stale.

export const CURATED_DOC_PATH = "docs/factory/curated-v1.md";

interface JsonNode {
  readonly type?: string | readonly string[];
  readonly const?: unknown;
  readonly enum?: readonly unknown[];
  readonly properties?: Readonly<Record<string, JsonNode>>;
  readonly required?: readonly string[];
  readonly items?: JsonNode;
  readonly anyOf?: readonly JsonNode[];
}

const nonNull = (node: JsonNode): JsonNode => node.anyOf?.find((option) => option.type !== "null") ?? node;

function typeOf(node: JsonNode): string {
  const inner = nonNull(node);
  if (inner.const !== undefined) return `\`${JSON.stringify(inner.const)}\``;
  if (inner.enum) return inner.enum.map((value) => `\`${JSON.stringify(value)}\``).join(metaDot);
  if (inner.type === "array") return "list";
  if (inner.properties) return "object";
  const type = inner.type;
  if (type === undefined) return "any";
  if (typeof type === "string") return type;
  return type.join(metaDot);
}

function fields(node: JsonNode): string[] {
  const object = nonNull(node).type === "array" ? nonNull(nonNull(node).items ?? {}) : nonNull(node);
  const required = new Set(object.required ?? []);
  return Object.entries(object.properties ?? {}).map(([name, child]) => `| \`${name}\` | ${typeOf(child)} | ${required.has(name) ? "yes" : "no"} |`);
}

/** The whole generated file. Deterministic: same schema, same bytes. */
export function renderCuratedDoc(): string {
  const root = z.toJSONSchema(curatedDocSchema, { io: "input", unrepresentable: "any" }) as JsonNode;
  const sections = Object.entries(root.properties ?? {}).flatMap(([name, node]) => {
    const inner = nonNull(node);
    const object = inner.type === "array" ? nonNull(inner.items ?? {}) : inner;
    if (!object.properties) return [];
    return [`### \`${inner.type === "array" ? `${name}[]` : name}\``, "", "| Field | Type | Required |", "|---|---|---|", ...fields(node), ""];
  });
  return [
    "# curated/v1",
    "",
    "<!-- Generated from apps/web/src/factory/domain/curated.ts. Do not edit; the unit test fails when it is stale. -->",
    "",
    "One JSON file per institution run. It is the only input of `curatedToBatch`. Limits are the catalog schema",
    `(INV-R1): an id is at most ${String(LIMITS.entityId)} characters, a course title at most ${String(LIMITS.courseTitle)},`,
    `a lesson title at most ${String(LIMITS.lessonTitle)}.`,
    "",
    "Rules checked by the schema:",
    "",
    "- `provenance.titles` of `translated` is a schema error. `originalTitle` stays in the source language.",
    "- `durationSeconds` is an integer greater than 0. A scheduled video is not a lesson.",
    "- An over-long field fails by its path (`courses.0.id`, `courses.0.title`).",
    "- `decision: hold` keeps the course in the file and out of the batch, and names `holdReason`.",
    "- `decision: include` may omit a field. The converter holds that course. A missing year, coverFrom or required cover is a hold, never a guessed value.",
    "- The institution is kind `institution`. Its cover names alt, credit, sourceUrl and license for the University row.",
    "- Home-row placement is `after` (the previous row) or omitted. The batch has no position field.",
    "- `positions`, when present, is an inclusive playlist range `{ from, to }` of positive integers with `from` <= `to`. Absent means the whole playlist.",
    "",
    ...sections,
  ].join("\n");
}

/** Null when `current` is the rendered document, else what is wrong. */
export function curatedDocProblem(current: string | null): string | null {
  if (current === renderCuratedDoc()) return null;
  return `${CURATED_DOC_PATH} is ${current === null ? "missing" : "stale"}.`;
}
