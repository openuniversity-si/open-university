import { textBatchIssues } from "../domain/rules/lifecycle.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import { TEXT_FIELDS, textField, textIssues, type TextEntityKind, type TextField } from "../domain/fields.ts";
import type { TextsApprove, TextsPut, TextsRevoke } from "../domain/contracts.ts";
import type { Outcome } from "./mutation.ts";
import { AppError, notFound, stateConflict, unprocessable } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { iso } from "./common.ts";
import { approveCatalogText, lockCatalogText, revokeCatalogText, selectCatalogTexts, selectTextEntityIds, updateCatalogTextProvenance, upsertCatalogTextDraft } from "./table-io.ts";

const ref = (kind: string, id: string) => `${kind}:${id}`;
type Key = { entityKind: TextEntityKind; entityId: string; field: string };

/** Which of these entities exist, by `kind:id`. */
async function existing(db: Queryable, keys: readonly Key[]): Promise<Set<string>> {
  const found = new Set<string>();
  for (const kind of ["course", "lesson", "author"] as const) {
    const ids = [...new Set(keys.filter((key) => key.entityKind === kind).map((key) => key.entityId))];
    if (ids.length === 0) continue;
    for (const row of await selectTextEntityIds(db, kind, ids)) found.add(ref(kind, String(row.id)));
  }
  return found;
}

async function lockTexts(db: Queryable, keys: readonly Key[]) {
  const rows = new Map<string, Record<string, unknown>>();
  for (const key of keys) {
    const found = await lockCatalogText(db, key.entityKind, key.entityId, key.field);
    if (found) rows.set(`${ref(key.entityKind, key.entityId)}.${key.field}`, found);
  }
  return rows;
}

function textView(row: Record<string, unknown>) {
  return {
    text: String(row.text), sha256: String(row.text_sha256), status: String(row.status), approvedSha256: (row.approved_sha256 ?? null) as string | null,
    approvedBy: (row.approved_by ?? null) as string | null, approvedAt: iso(row.approved_at), source: String(row.source), sourceRef: String(row.source_ref),
    confidence: String(row.confidence), updatedAt: iso(row.updated_at),
  };
}

export async function getTexts(context: HandlerContext<unknown, { entity: string }, unknown>): Promise<Outcome> {
  const [kind, id] = context.query.entity.split(":") as [TextEntityKind, string];
  if (!(await existing(context.db, [{ entityKind: kind, entityId: id, field: "" }])).has(ref(kind, id))) throw notFound(`${kind} ${id}`);
  const rows = await selectCatalogTexts(context.db, kind, id);
  const byField = new Map(rows.map((row) => [String(row.field), row]));
  const specs: Readonly<Record<string, TextField>> = TEXT_FIELDS[kind];
  return {
    data: {
      entity: ref(kind, id),
      fields: Object.entries(specs).map(([field, spec]) => {
        const row = byField.get(field);
        return { field, maxChars: spec.maxChars, requiredForReview: spec.review, requiredForPublish: spec.publish, ...(row ? { ...textView(row), issues: textIssues(kind, field, String(row.text)) } : { text: null, status: null, issues: [] }) };
      }),
    },
  };
}

/** PUT /texts: one atomic batch, always written as draft; any invalid item refuses the whole batch (422 with every item). */
export async function putTexts(context: HandlerContext<unknown, unknown, TextsPut>): Promise<Outcome> {
  const items = context.body;
  const errors: { index: number; entity: string; field: string; issues: { rule: string; message: string }[] }[] = [];
  const found = await existing(context.db, items);
  const batchIssues = textBatchIssues(items, found);
  items.forEach((item, index) => {
    const issues: { rule: string; message: string }[] = [...textIssues(item.entityKind, item.field, item.text), ...(batchIssues[index] ?? [])];
    if (issues.length > 0) errors.push({ index, entity: ref(item.entityKind, item.entityId), field: item.field, issues });
  });
  if (errors.length > 0) throw unprocessable(`${String(errors.length)} item(s) cannot be stored; nothing was written.`, { items: errors });
  return context.mutate(async (tx) => {
    const current = await lockTexts(tx, items);
    if ((await existing(tx, items)).size !== found.size) throw unprocessable("An entity of the batch was deleted meanwhile; nothing was written.");
    const results = [];
    for (const item of items) {
      const key = `${ref(item.entityKind, item.entityId)}.${item.field}`;
      const before = current.get(key);
      const same = before !== undefined && before.text === item.text;
      if (same && before.source === item.source && before.source_ref === item.sourceRef && before.confidence === item.confidence) {
        results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, sha256: String(before.text_sha256), status: String(before.status), changed: false });
        continue;
      }
      // Same text, new provenance: the approval (of that exact text) stands. A new text always goes back to draft.
      const row = same
        ? await updateCatalogTextProvenance(tx, item.entityKind, item.entityId, item.field, item.source, item.sourceRef, item.confidence)
        : await upsertCatalogTextDraft(tx, item.entityKind, item.entityId, item.field, item.source, item.sourceRef, item.confidence, item.text);
      const after = { sha256: String(row?.text_sha256), status: String(row?.status) };
      await tx.audit({
        action: "text.put", entityKind: item.entityKind, entityId: item.entityId,
        before: before ? { field: item.field, sha256: before.text_sha256, status: before.status, source: before.source } : { field: item.field },
        after: { field: item.field, ...after, source: item.source },
      });
      results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, ...after, changed: true });
    }
    const noop = results.every((result) => !result.changed);
    return { data: { items: results, ...(noop ? { noop: true } : {}) }, noop };
  });
}

/** Approves the hash the reviewer saw: any text that changed since (or is missing, or invalid) refuses the whole batch. */
export async function approveTexts(context: HandlerContext<unknown, unknown, TextsApprove>): Promise<Outcome> {
  const { items, approvedBy } = context.body;
  return context.mutate(async (tx) => {
    const current = await lockTexts(tx, items);
    const missing = items.filter((item) => !current.has(`${ref(item.entityKind, item.entityId)}.${item.field}`)).map((item) => `${ref(item.entityKind, item.entityId)}.${item.field}`);
    if (missing.length > 0) throw new AppError("not_found", `${String(missing.length)} text(s) do not exist; nothing was approved.`, { missing });
    const mismatched = items.flatMap((item) => {
      const row = current.get(`${ref(item.entityKind, item.entityId)}.${item.field}`);
      return row && row.text_sha256 !== item.sha256 ? [{ entity: ref(item.entityKind, item.entityId), field: item.field, currentSha256: String(row.text_sha256) }] : [];
    });
    if (mismatched.length > 0) throw stateConflict(`${String(mismatched.length)} text(s) changed since review; nothing was approved.`, { mismatched });
    const invalid = items.flatMap((item) => {
      const row = current.get(`${ref(item.entityKind, item.entityId)}.${item.field}`);
      const issues = row && textField(item.entityKind, item.field) ? textIssues(item.entityKind, item.field, String(row.text)) : [];
      return issues.length > 0 ? [{ entity: ref(item.entityKind, item.entityId), field: item.field, issues }] : [];
    });
    if (invalid.length > 0) throw unprocessable(`${String(invalid.length)} text(s) do not fit their slot; nothing was approved.`, { items: invalid });
    const results = [];
    for (const item of items) {
      const row = current.get(`${ref(item.entityKind, item.entityId)}.${item.field}`) ?? {};
      if (row.status === "approved" && row.approved_sha256 === item.sha256) { results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, sha256: item.sha256, changed: false }); continue; }
      await approveCatalogText(tx, item.entityKind, item.entityId, item.field, approvedBy);
      await tx.audit({ action: "text.approve", entityKind: item.entityKind, entityId: item.entityId, before: { field: item.field, sha256: item.sha256, status: row.status }, after: { field: item.field, sha256: item.sha256, status: "approved", approvedBy } });
      results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, sha256: item.sha256, changed: true });
    }
    const noop = results.every((result) => !result.changed);
    return { data: { items: results, approvedBy, ...(noop ? { noop: true } : {}) }, noop };
  });
}

export async function revokeTexts(context: HandlerContext<unknown, unknown, TextsRevoke>): Promise<Outcome> {
  const { items } = context.body;
  return context.mutate(async (tx) => {
    const current = await lockTexts(tx, items);
    const missing = items.filter((item) => !current.has(`${ref(item.entityKind, item.entityId)}.${item.field}`)).map((item) => `${ref(item.entityKind, item.entityId)}.${item.field}`);
    if (missing.length > 0) throw new AppError("not_found", `${String(missing.length)} text(s) do not exist; nothing was revoked.`, { missing });
    const results = [];
    for (const item of items) {
      const row = current.get(`${ref(item.entityKind, item.entityId)}.${item.field}`) ?? {};
      if (row.status !== "approved") { results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, changed: false }); continue; }
      await revokeCatalogText(tx, item.entityKind, item.entityId, item.field);
      await tx.audit({ action: "text.revoke", entityKind: item.entityKind, entityId: item.entityId, before: { field: item.field, sha256: row.text_sha256, status: "approved", approvedBy: row.approved_by }, after: { field: item.field, status: "draft" } });
      results.push({ entity: ref(item.entityKind, item.entityId), field: item.field, changed: true });
    }
    const noop = results.every((result) => !result.changed);
    return { data: { items: results, ...(noop ? { noop: true } : {}) }, noop };
  });
}
