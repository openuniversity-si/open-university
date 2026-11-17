import { preconditionsFailed, stateConflict } from "../../kernel/errors.ts";
import type { CatalogStatePort, StatusChange } from "../ports/commands.ts";
import { canTransition, evaluateRules, STATUS_TRANSITIONS, type RuleOptions } from "./rules/status.ts";
import { factsOf } from "./rules-helpers.ts";

export interface TransitionEffects {
  readonly state: CatalogStatePort;
  audit(entry: { readonly action: string; readonly entityKind: string; readonly entityId: string; readonly before?: unknown; readonly after?: unknown }): Promise<void>;
}

/** The status change shared by the database adapter and the in-memory catalog. Publish stays on the release pipeline. */
export async function createTransition(change: StatusChange, options: RuleOptions | undefined, deps: TransitionEffects, transitions: Readonly<Record<string, readonly string[]>> = STATUS_TRANSITIONS) {
  const snapshot = await deps.state.read(change);
  const course = snapshot.tables.courses.find((row) => row.id === change.courseId);
  if (!course) throw stateConflict(`Course ${change.courseId} is missing after its lock.`);
  const from = course.status;
  if (from === "published") throw stateConflict("A published course leaves through POST /unpublish (or DELETE ?mode=archive).", { from, to: change.target });
  if (!canTransition(from, change.target, transitions)) throw stateConflict(`A course cannot go from ${from} to ${change.target}.`, { from, to: change.target, allowed: transitions[from] ?? [] });
  if (change.target === "review") {
    const facts = factsOf(snapshot, change.courseId);
    const failed = facts ? evaluateRules("review", facts, options) : [];
    if (failed.length > 0) throw preconditionsFailed(failed);
  }
  const result = await deps.state.changeStatus(change);
  await deps.audit({ action: "course.status", entityKind: "course", entityId: change.courseId, before: { status: from }, after: { status: change.target } });
  return result;
}
