import { coverKindsByOwner, coverOwners, type CoverOwner } from "../../kernel/cover-kinds.ts";

export type { CoverOwner };

/** The figure's choice. A kind this owner does not accept is refused here, before a write. */
export function coverKindAllowed(owner: string, kind: string): boolean {
  if (!(coverOwners as readonly string[]).includes(owner)) return false;
  return (coverKindsByOwner[owner as CoverOwner] as readonly string[]).includes(kind);
}
