import "server-only";
import { invalid } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { withUnitOfWork, type DbPool } from "../../platform/db/uow.ts";
import { isConfigKind, nextStoredRevision, parseDocument, type ConfigDocument, type ConfigKind } from "../domain/documents.ts";
import type { ConfigDocuments, ConfigRevision } from "../ports/documents.ts";

interface StoredRow {
  kind: string;
  revision: number;
  body: unknown;
  actor: string;
  note: string | null;
  at: Date;
}

function requireKind(kind: string): ConfigKind {
  if (!isConfigKind(kind)) throw invalid("Unknown configuration kind.");
  return kind;
}

function requireActor(actor: string): string {
  if (actor.length === 0 || actor.length > LIMITS.text) throw invalid("Actor is outside the contract.");
  return actor;
}

function requireNote(note: string | null): string | null {
  if (note !== null && note.length > LIMITS.text) throw invalid("Note is outside the contract.");
  return note;
}

function storedRow(value: Record<string, unknown>): StoredRow {
  const note = value.note;
  if (typeof value.kind !== "string" || typeof value.revision !== "number" || typeof value.actor !== "string" || !(value.at instanceof Date) || (note !== null && typeof note !== "string")) {
    throw invalid("Stored revision is outside the contract.");
  }
  return { kind: value.kind, revision: value.revision, body: value.body, actor: value.actor, note, at: value.at };
}

function toRevision(kind: ConfigKind, row: StoredRow): ConfigRevision {
  if (row.kind !== kind) throw invalid("Stored revision is outside the contract.");
  return {
    kind,
    revision: row.revision,
    body: parseDocument(kind, row.body),
    actor: row.actor,
    note: row.note,
    at: row.at.toISOString(),
  };
}

function seenRevision(value: Record<string, unknown> | undefined): number {
  if (value === undefined) return 0;
  if (typeof value.revision !== "number") throw invalid("Stored revision is outside the contract.");
  return value.revision;
}

const READ_CURRENT = "SELECT kind, revision, body, actor, note, updated_at AS at FROM config_documents WHERE kind = $1";
const READ_HISTORY = "SELECT kind, revision, body, actor, note, created_at AS at FROM config_document_revisions WHERE kind = $1 ORDER BY revision";

/** Versioned configuration. The SQL for these tables stays in this file. */
export function configRepository(pool: DbPool): ConfigDocuments {
  return {
    async read(kind) {
      const checked = requireKind(kind);
      const result = await pool.query(READ_CURRENT, [checked]);
      const row = result.rows[0];
      return row === undefined ? null : toRevision(checked, storedRow(row));
    },
    async history(kind) {
      const checked = requireKind(kind);
      const result = await pool.query(READ_HISTORY, [checked]);
      return result.rows.map((row) => toRevision(checked, storedRow(row)));
    },
    async commit(input) {
      const kind = requireKind(input.kind);
      const actor = requireActor(input.actor);
      const note = requireNote(input.note);
      const body: ConfigDocument = parseDocument(kind, input.body);
      return withUnitOfWork(pool, async (uow) => {
        await uow.acquireLock({ scope: "xact", key: `config:${kind}` });
        const current = await uow.query("SELECT revision FROM config_documents WHERE kind = $1 FOR UPDATE", [kind]);
        const seen = seenRevision(current.rows[0]);
        const revision = nextStoredRevision(seen, input.expectedRevision);
        const payload = JSON.stringify(body);
        await uow.query(
          "INSERT INTO config_document_revisions (kind, revision, body, actor, note) VALUES ($1, $2, $3::jsonb, $4, $5)",
          [kind, revision, payload, actor, note],
        );
        if (seen === 0) {
          await uow.query(
            "INSERT INTO config_documents (kind, revision, body, actor, note) VALUES ($1, $2, $3::jsonb, $4, $5)",
            [kind, revision, payload, actor, note],
          );
        } else {
          await uow.query(
            "UPDATE config_documents SET revision = $2, body = $3::jsonb, actor = $4, note = $5, updated_at = now() WHERE kind = $1",
            [kind, revision, payload, actor, note],
          );
        }
        const stored = await uow.query(READ_CURRENT, [kind]);
        const row = stored.rows[0];
        if (row === undefined) throw invalid("Stored revision is missing.");
        return toRevision(kind, storedRow(row));
      });
    },
  };
}
