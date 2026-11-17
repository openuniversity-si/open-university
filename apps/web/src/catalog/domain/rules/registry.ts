import type { PreconditionFailure } from "../../../kernel/errors.ts";

/**
 * The rule registry (CONTRACT.md INV-R2). Every catalog rule id is declared here once, by `declareRule` in a module of
 * `src/catalog/domain/rules/`; routes, the ship applier and the CLI report failures only through the declared rule.
 * A second declaration of an id throws at load, and the gate's `L6.single-rule` rejects it before that.
 */

/** A lifecycle blocker: a rule that stops a delete, without an entity (the report names the entity). */
export interface RuleBlocker { readonly rule: string; readonly message: string }

export interface DeclaredRule<Id extends string = string> {
  readonly id: Id;
  readonly summary: string;
  fail(entity: string, message: string): PreconditionFailure;
  block(message: string): RuleBlocker;
}

const registry = new Map<string, DeclaredRule>();

export function declareRule<const Id extends string>(id: Id, summary: string): DeclaredRule<Id> {
  if (registry.has(id)) throw new Error(`Rule ${id} is declared twice.`);
  const rule: DeclaredRule<Id> = {
    id, summary,
    fail: (entity, message) => ({ rule: id, entity, message }),
    block: (message) => ({ rule: id, message }),
  };
  registry.set(id, rule);
  return rule;
}

/** Every declared rule, in declaration order. */
export function declaredRules(): readonly DeclaredRule[] {
  return [...registry.values()];
}
