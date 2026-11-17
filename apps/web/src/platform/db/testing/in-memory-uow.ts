import type { UnitOfWork } from "../uow.ts";

export interface MemoryParticipant<S> {
  snapshot(): S;
  /** Publishes a copy only after every participant has been validated. */
  restore(snapshot: S): void;
}

export interface InMemoryUnitOfWork {
  register<S>(participant: MemoryParticipant<S>): void;
  /** True only for the transaction this bench handed out, and only until it finishes. */
  owns(tx: UnitOfWork): boolean;
  /** One serialized transaction. `query` throws: this bench does not emulate PostgreSQL. */
  run<T>(work: (tx: UnitOfWork) => Promise<T>): Promise<T>;
}

export interface TestClock {
  now(): number;
  advance(milliseconds: number): void;
}

/** A clock the adapters read. Nothing in the bench calls `Date.now`. */
export function createTestClock(start = 0): TestClock {
  let current = start;
  return {
    now: () => current,
    advance(milliseconds) { current += milliseconds; },
  };
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** In-memory unit of work for the ports that exist through state 3.2. Callbacks run only after commit. */
export function createInMemoryUnitOfWork(): InMemoryUnitOfWork {
  const participants = new Set<MemoryParticipant<unknown>>();
  const live = new WeakSet<UnitOfWork>();
  let active: { readonly effects: (() => Promise<void> | void)[]; readonly locks: Set<string> } | null = null;

  return {
    register(participant) {
      participants.add(participant);
    },
    owns(tx) {
      return live.has(tx);
    },
    async run(work) {
      if (active) throw new Error("In-memory transactions do not nest.");
      const before = new Map<MemoryParticipant<unknown>, unknown>();
      for (const participant of participants) before.set(participant, clone(participant.snapshot()));
      const effects: (() => Promise<void> | void)[] = [];
      const locks = new Set<string>();
      const txState = { effects, locks };
      active = txState;
      const tx: UnitOfWork = {
        query() {
          return Promise.reject(new Error("In-memory unit of work does not execute SQL."));
        },
        acquireLock(lock) {
          if (active !== txState) return Promise.reject(new Error("Advisory locks exist only inside a transaction."));
          locks.add("key" in lock ? lock.key : lock.scope);
          return Promise.resolve();
        },
        onAfterCommit(effect) {
          if (active !== txState) throw new Error("afterCommit exists only inside a transaction.");
          effects.push(effect);
        },
      };
      live.add(tx);
      try {
        const result = await work(tx);
        active = null;
        const errors: unknown[] = [];
        for (const effect of effects) {
          try { await effect(); } catch (error) { errors.push(error); }
        }
        if (errors.length === 1) throw errors[0];
        if (errors.length > 1) throw new AggregateError(errors, "A committed effect failed.");
        return result;
      } catch (error) {
        if (active === txState) {
          for (const [participant, snapshot] of before) participant.restore(clone(snapshot));
          active = null;
        }
        throw error;
      } finally {
        live.delete(tx);
      }
    },
  };
}
