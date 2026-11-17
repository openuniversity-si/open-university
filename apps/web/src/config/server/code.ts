import "server-only";
import { codeDocument, type ConfigKind } from "../domain/documents.ts";

/** The code revision. A stored revision replaces it only after the reader lands. */
export function codeConfiguration(kind: ConfigKind) {
  return codeDocument(kind);
}
