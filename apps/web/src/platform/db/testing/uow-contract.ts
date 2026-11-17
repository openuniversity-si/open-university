import { expect } from "vitest";
import type { UnitOfWork } from "../uow.ts";

export interface ContractHarness<P> {
  readonly port: P;
  reset(): Promise<void>;
  dispose(): Promise<void>;
}
export interface ContractCase<P> {
  readonly id: string;
  run(harness: P): Promise<void>;
}
export interface ContractSuite<P> {
  readonly portId: string;
  readonly cases: readonly ContractCase<P>[];
}

interface Participant<S> {
  snapshot(): S;
  restore(snapshot: S): void;
}

export interface UowBench extends ContractHarness<{ readonly kind: "infrastructure" }> {
  register<S>(participant: Participant<S>): void;
  run<T>(work: (tx: UnitOfWork) => Promise<T>): Promise<T>;
}

/** Shared unit-of-work cases. The bench throws on SQL; it does not parse it. */
export function uowContract(): ContractSuite<UowBench> {
  return {
    portId: "UnitOfWork",
    cases: [
      { id: "uow.commit.effects", async run(harness) {
        const box = valueBox(0);
        harness.register(box);
        const seen: number[] = [];
        await harness.run((tx) => {
          box.value = 1;
          tx.onAfterCommit(() => { seen.push(box.value); });
          expect(seen).toEqual([]);
          return Promise.resolve();
        });
        expect(box.value).toBe(1);
        expect(seen).toEqual([1]);
      } },
      { id: "uow.rollback.skips-effects", async run(harness) {
        const box = valueBox(0);
        harness.register(box);
        let ran = false;
        await expect(harness.run((tx) => {
          box.value = 4;
          tx.onAfterCommit(() => { ran = true; });
          throw new Error("no");
        })).rejects.toThrow("no");
        expect(box.value).toBe(0);
        expect(ran).toBe(false);
      } },
      { id: "uow.effect.keeps-commit", async run(harness) {
        const box = valueBox(0);
        harness.register(box);
        await expect(harness.run((tx) => {
          box.value = 2;
          tx.onAfterCommit(() => { throw new Error("drain"); });
          return Promise.resolve();
        })).rejects.toThrow("drain");
        expect(box.value).toBe(2);
      } },
      { id: "uow.query.refuses", async run(harness) {
        await expect(harness.run(async (tx) => { await tx.query("SELECT 1"); })).rejects.toThrow("does not execute SQL");
        await expect(harness.run(async (tx) => {
          await tx.acquireLock({ scope: "xact", key: "course:1" });
        })).resolves.toBeUndefined();
      } },
      { id: "uow.participants.rollback", async run(harness) {
        const first = valueBox(1);
        const second = valueBox(1);
        harness.register(first);
        harness.register(second);
        await expect(harness.run(() => {
          first.value = 8;
          second.value = 9;
          throw new Error("no");
        })).rejects.toThrow("no");
        expect(first.value).toBe(1);
        expect(second.value).toBe(1);
      } },
      { id: "uow.snapshot.copies", async run(harness) {
        const state = { map: new Map([["a", 1]]), set: new Set(["a"]), date: new Date("2020-01-01T00:00:00.000Z"), bytes: new Uint8Array([1, 2]) };
        const box = {
          state,
          snapshot: () => structuredClone(state),
          restore(snapshot: typeof state) { this.state = snapshot; },
        };
        harness.register(box);
        await harness.run(() => {
          const snap = box.snapshot();
          snap.map.set("a", 9);
          snap.set.add("b");
          snap.date.setUTCFullYear(1999);
          snap.bytes[0] = 7;
          expect(box.state.map.get("a")).toBe(1);
          expect([...box.state.set]).toEqual(["a"]);
          expect(box.state.date.getUTCFullYear()).toBe(2020);
          expect(box.state.bytes[0]).toBe(1);
          box.state.map.set("a", 3);
          return Promise.resolve();
        });
        expect(box.state.map.get("a")).toBe(3);
      } },
    ],
  };
}

export async function executeContract<T extends { reset(): Promise<void>; dispose(): Promise<void> }>(suite: ContractSuite<T>, harness: T): Promise<void> {
  for (const item of suite.cases) {
    await harness.reset();
    await item.run(harness);
  }
  await harness.dispose();
}

function valueBox(start: number): Participant<number> & { value: number } {
  const box = { value: start, snapshot: () => box.value, restore(snapshot: number) { box.value = snapshot; } };
  return box;
}
