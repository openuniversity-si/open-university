import type { ConfigDocument, ConfigKind } from "../domain/documents.ts";

/** One stored revision. Revision 0 is the code and is never a row. */
export interface ConfigRevision {
  readonly kind: ConfigKind;
  readonly revision: number;
  readonly body: ConfigDocument;
  readonly actor: string;
  readonly note: string | null;
  readonly at: string;
}

/** Versioned configuration reads and appends. History is append-only. */
export interface ConfigDocuments {
  read(kind: ConfigKind): Promise<ConfigRevision | null>;
  history(kind: ConfigKind): Promise<readonly ConfigRevision[]>;
  commit(input: {
    readonly kind: ConfigKind;
    readonly expectedRevision: number;
    readonly body: ConfigDocument;
    readonly actor: string;
    readonly note: string | null;
  }): Promise<ConfigRevision>;
}
