import { expect } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import type { UnitOfWork } from "../../platform/db/uow.ts";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import type { CatalogTables } from "../domain/tables.ts";
import type { CatalogCommandsPort, StatusChange } from "../ports/commands.ts";
import type { CatalogOwnersPort } from "../../media/ports/owner.ts";
import type { PublishedLessonLookup } from "../../progress/ports/lessons.ts";

export interface CatalogBench {
  readonly port: CatalogCommandsPort;
  ownersIn(tx: UnitOfWork): CatalogOwnersPort;
  readonly lessons: PublishedLessonLookup;
  reset(): Promise<void>;
  dispose(): Promise<void>;
  seed(kind: "ready" | "empty"): Promise<{ readonly courseId: string; readonly revision: number }>;
  course(courseId: string): Promise<{ readonly status: string; readonly revision: number }>;
  journalCount(courseId: string): Promise<number>;
  tables(): Promise<CatalogTables>;
  failNextEffect(message: string): void;
  effectRan(): boolean;
  transaction<T>(work: (tx: UnitOfWork) => Promise<T>): Promise<T>;
}

const review = (courseId: string, expectedRevision: number, target: StatusChange["target"]): StatusChange => ({ courseId, expectedRevision, target });

function rulesOf(error: unknown): string[] {
  if (!(error instanceof AppError)) throw error;
  const failed = (error.details as { failed?: { rule: string }[] } | undefined)?.failed ?? [];
  return failed.map((failure) => failure.rule);
}

/** Status, owner and lookup cases shared by the memory bench and the database adapter. */
export function catalogContract(): ContractSuite<CatalogBench> {
  return {
    portId: "CatalogCommandsPort",
    cases: [
      { id: "catalog.transition.review", async run(harness) {
        await harness.seed("ready");
        const result = await harness.port.transition(review("course-ready", 1, "review"));
        expect(result.revision).toBe(2);
        expect(result.course.status).toBe("review");
        expect(await harness.course("course-ready")).toEqual({ status: "review", revision: 2 });
        expect(await harness.journalCount("course-ready")).toBe(1);
      } },
      { id: "catalog.transition.preconditions", async run(harness) {
        await harness.seed("empty");
        harness.failNextEffect("drain");
        const error = await harness.port.transition(review("course-empty", 1, "review")).then(() => { throw new Error("expected preconditions"); }, (caught: unknown) => caught);
        expect(error).toMatchObject({ code: "preconditions_failed" });
        const rules = rulesOf(error);
        expect(new Set(rules)).toEqual(new Set(["covers.active", "editions.exists", "lessons.visible", "rights.fields", "texts.required"]));
        expect(rules.filter((rule) => rule === "texts.required")).toHaveLength(10);
        expect(rules.filter((rule) => rule === "covers.active")).toHaveLength(4);
        expect(rules.filter((rule) => rule === "rights.fields")).toHaveLength(3);
        expect(await harness.course("course-empty")).toEqual({ status: "draft", revision: 1 });
        expect(await harness.journalCount("course-empty")).toBe(0);
        expect(harness.effectRan()).toBe(false);
      } },
      { id: "catalog.transition.forbidden", async run(harness) {
        await harness.seed("ready");
        await expect(harness.port.transition({ courseId: "course-ready", expectedRevision: 1, target: "published" } as unknown as StatusChange)).rejects.toMatchObject({ code: "state_conflict" });
        expect(await harness.course("course-ready")).toEqual({ status: "draft", revision: 1 });
        expect(await harness.journalCount("course-ready")).toBe(0);
      } },
      { id: "catalog.transition.published", async run(harness) {
        await harness.seed("ready");
        await expect(harness.port.transition(review("course-live", 1, "draft"))).rejects.toMatchObject({ code: "state_conflict" });
        expect(await harness.course("course-live")).toEqual({ status: "published", revision: 1 });
        expect(await harness.journalCount("course-live")).toBe(0);
      } },
      { id: "catalog.transition.revision", async run(harness) {
        await harness.seed("ready");
        await expect(harness.port.transition(review("course-ready", 0, "review"))).rejects.toMatchObject({ code: "revision_conflict" });
        expect(await harness.course("course-ready")).toEqual({ status: "draft", revision: 1 });
        expect(await harness.journalCount("course-ready")).toBe(0);
      } },
      { id: "catalog.transition.retry", async run(harness) {
        await harness.seed("ready");
        await harness.port.transition(review("course-ready", 1, "review"));
        await expect(harness.port.transition(review("course-ready", 2, "review"))).rejects.toMatchObject({ code: "state_conflict" });
        expect(await harness.course("course-ready")).toEqual({ status: "review", revision: 2 });
        expect(await harness.journalCount("course-ready")).toBe(1);
      } },
      { id: "catalog.transition.effect-failure", async run(harness) {
        await harness.seed("ready");
        harness.failNextEffect("drain");
        await expect(harness.port.transition(review("course-ready", 1, "review"))).rejects.toThrow("drain");
        expect(harness.effectRan()).toBe(true);
        expect(await harness.course("course-ready")).toEqual({ status: "review", revision: 2 });
        expect(await harness.journalCount("course-ready")).toBe(1);
      } },
      { id: "catalog.snapshot.isolated", async run(harness) {
        await harness.seed("ready");
        const tables = await harness.tables();
        const course = tables.courses.find((row) => row.id === "course-ready");
        if (!course) throw new Error("missing course");
        course.title = "Mutated";
        const again = await harness.tables();
        expect(again.courses.find((row) => row.id === "course-ready")?.title).toBe("course-ready");
      } },
      { id: "catalog.owners.course", async run(harness) {
        await harness.seed("ready");
        await harness.transaction(async (tx) => {
          const owners = harness.ownersIn(tx);
          expect(await owners.courseOf("course", "course-ready")).toEqual({ courseId: "course-ready", published: false });
          expect(await owners.courseOf("lesson", "lesson-live")).toEqual({ courseId: "course-live", published: true });
          expect(await owners.courseOf("course", "missing")).toBeUndefined();
          expect(await owners.courseOf("subarea", "missing")).toBeUndefined();
          await owners.lockGraph();
        });
      } },
      { id: "catalog.owners.graph", async run(harness) {
        await harness.seed("ready");
        const graph = await harness.transaction((tx) => harness.ownersIn(tx).graph());
        expect(graph.courses.map((course) => course.id)).toEqual(["course-live", "course-ready"]);
        expect(graph.lessons.map((lesson) => lesson.id)).toEqual(["lesson-live", "lesson-ready"]);
      } },
      { id: "catalog.owners.inventory", async run(harness) {
        await harness.seed("ready");
        const covers = await harness.transaction((tx) => harness.ownersIn(tx).inventory());
        expect(covers).toEqual([{ ownerId: "author-a", kind: "author_cover_9x16", cover: { alt: "Author" } }]);
      } },
      { id: "catalog.lookup.published", async run(harness) {
        await harness.seed("ready");
        expect(await harness.lessons.resolvePublishedLesson("course-live", "lesson-live")).toEqual({ courseId: "course-live", lessonId: "lesson-live", durationSeconds: 60 });
      } },
      { id: "catalog.lookup.missing", async run(harness) {
        await harness.seed("ready");
        expect(await harness.lessons.resolvePublishedLesson("course-ready", "lesson-ready")).toBeNull();
        expect(await harness.lessons.resolvePublishedLesson("course-live", "missing")).toBeNull();
      } },
    ],
  };
}
