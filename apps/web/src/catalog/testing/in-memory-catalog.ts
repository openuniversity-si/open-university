import { notFound, assertRevision } from "../../kernel/errors.ts";
import { createInMemoryUnitOfWork, type InMemoryUnitOfWork } from "../../platform/db/testing/in-memory-uow.ts";
import type { Queryable, UnitOfWork } from "../../platform/db/uow.ts";
import { courseView } from "../domain/course-view.ts";
import { createTransition } from "../domain/transition.ts";
import type { CatalogTables } from "../domain/tables.ts";
import type { CatalogState } from "../domain/rules-helpers.ts";
import type { CatalogCommandsPort, CatalogStatePort, StatusChange } from "../ports/commands.ts";
import type { CatalogCoverRef, CatalogOwnersPort, MediaOwner } from "../../media/ports/owner.ts";
import type { PublishedLessonLookup } from "../../progress/ports/lessons.ts";
import type { CatalogBench } from "./catalog-contract.ts";
import { emptyCatalogFixture, readyCatalogFixture, type CatalogFixture } from "./catalog-fixture.ts";

interface JournalEntry {
  readonly action: string;
  readonly entityKind: string;
  readonly entityId: string;
  readonly before?: unknown;
  readonly after?: unknown;
}

interface MemoryState {
  tables: CatalogTables;
  revisions: Map<string, number>;
  covers: Map<string, Set<string>>;
  journal: JournalEntry[];
}

function blank(): MemoryState {
  const seeded = emptyCatalogFixture();
  return { tables: seeded.tables, revisions: new Map(), covers: new Map(), journal: [] };
}

function copyState(state: MemoryState): MemoryState {
  return structuredClone(state);
}

function load(fixture: CatalogFixture): MemoryState {
  const revisions = new Map(fixture.tables.courses.map((course) => [course.id, 1]));
  const covers = new Map(Object.entries(fixture.covers).map(([id, kinds]) => [id, new Set(kinds)]));
  return { tables: structuredClone(fixture.tables), revisions, covers, journal: [] };
}

/**
 * Catalog state, commands and owner lookup on one participant.
 * Transitions call the same `createTransition` the database adapter uses.
 */
export function createInMemoryCatalog(uow: InMemoryUnitOfWork = createInMemoryUnitOfWork()): CatalogBench {
  let state = blank();
  let closed = false;
  let pendingEffect: (() => void) | null = null;
  let effectDidRun = false;
  const participant = {
    snapshot: () => copyState(state),
    restore(snapshot: MemoryState) { state = snapshot; },
  };
  uow.register(participant);

  function assertOpen(): void {
    if (closed) throw new Error("The in-memory catalog is closed.");
  }
  function assertTx(tx: Queryable): asserts tx is UnitOfWork {
    if (!uow.owns(tx as UnitOfWork)) throw new Error("Transaction is not the in-memory unit of work.");
  }
  function viewOf(courseId: string) {
    const course = state.tables.courses.find((row) => row.id === courseId);
    if (!course) throw notFound(`Course ${courseId}`);
    const revision = state.revisions.get(courseId) ?? 1;
    return { course, revision };
  }

  const commands: CatalogCommandsPort = {
    transition(change, options) {
      assertOpen();
      return uow.run(async (tx) => {
        const courseState: CatalogStatePort = {
          async read(expected) {
            assertTx(tx);
            await tx.acquireLock({ scope: "xact", key: `course:${expected.courseId}` });
            const found = viewOf(expected.courseId);
            assertRevision(found.revision, expected.expectedRevision);
            const snapshot: CatalogState = {
              tables: structuredClone(state.tables),
              revisions: structuredClone(state.revisions),
              covers: structuredClone(state.covers),
            };
            return snapshot;
          },
          changeStatus(next: StatusChange) {
            assertTx(tx);
            const { course, revision } = viewOf(next.courseId);
            assertRevision(revision, next.expectedRevision);
            const revisionNext = revision + 1;
            state.revisions.set(next.courseId, revisionNext);
            state.tables = {
              ...state.tables,
              courses: state.tables.courses.map((row) => row.id === next.courseId ? { ...row, status: next.target } : row),
            };
            const updated = state.tables.courses.find((row) => row.id === next.courseId) ?? course;
            return Promise.resolve({ revision: revisionNext, course: courseView({ ...updated, revision: revisionNext }) });
          },
        };
        const result = await createTransition(change, options, {
          state: courseState,
          audit: (entry) => {
            state.journal.push(entry);
            return Promise.resolve();
          },
        });
        if (pendingEffect) {
          const effect = pendingEffect;
          pendingEffect = null;
          tx.onAfterCommit(() => { effectDidRun = true; effect(); });
        }
        return result;
      });
    },
  };

  function ownersIn(tx: UnitOfWork): CatalogOwnersPort {
    assertTx(tx);
    return {
      courseOf(owner: MediaOwner, id) {
        if (owner === "area") {
          const known = state.tables.subject_areas.some((area) => area.id === id);
          if (!known) return Promise.resolve(undefined);
          const rows = state.tables.courses.filter((course) => course.area_id === id);
          return Promise.resolve({ courseId: id, published: true, courses: rows.map((course) => ({ courseId: course.id, published: course.status === "published" })) });
        }
        if (owner === "institution") {
          const author = state.tables.authors.find((row) => row.id === id);
          return Promise.resolve(author ? { courseId: id, published: false } : undefined);
        }
        if (owner === "subarea") {
          const rows = state.tables.courses.filter((course) => course.subarea_id === id);
          const known = state.tables.subject_subareas.some((subarea) => subarea.id === id);
          if (!known) return Promise.resolve(undefined);
          return Promise.resolve({ courseId: id, published: true, subareaId: id, courses: rows.map((course) => ({ courseId: course.id, published: course.status === "published" })) });
        }
        if (owner === "course") {
          const course = state.tables.courses.find((row) => row.id === id);
          return Promise.resolve(course ? { courseId: course.id, published: course.status === "published" } : undefined);
        }
        const lesson = state.tables.lessons.find((row) => row.id === id);
        const course = state.tables.courses.find((row) => row.id === lesson?.course_id);
        return Promise.resolve(course ? { courseId: course.id, published: course.status === "published" } : undefined);
      },
      graph() {
        const byId = (left: string, right: string) => (left < right ? -1 : left > right ? 1 : 0);
        return Promise.resolve({
          courses: [...state.tables.courses].sort((a, b) => byId(a.id, b.id)).map((course) => ({
            id: course.id, area_id: course.area_id, subarea_id: course.subarea_id, cover_from: course.cover_from, status: course.status,
          })),
          lessons: [...state.tables.lessons].sort((a, b) => byId(a.id, b.id)).map((lesson) => ({ id: lesson.id, course_id: lesson.course_id })),
        });
      },
      async lockGraph() {
        await tx.acquireLock({ scope: "xact", key: "catalog:graph" });
      },
      inventory() {
        const covers: CatalogCoverRef[] = [];
        for (const author of state.tables.authors) if (author.cover) covers.push({ ownerId: author.id, kind: "author_cover_9x16", cover: structuredClone(author.cover) });
        for (const row of state.tables.home_rows) if (row.cover) covers.push({ ownerId: row.id, kind: "university_cover_9x16", cover: structuredClone(row.cover) });
        return Promise.resolve(covers);
      },
    };
  }

  const lessons: PublishedLessonLookup = {
    resolvePublishedLesson(courseSlug, lessonSlug) {
      const course = state.tables.courses.find((row) => row.slug === courseSlug && row.status === "published");
      if (!course) return Promise.resolve(null);
      const lesson = state.tables.lessons.find((row) => row.course_id === course.id && row.slug === lessonSlug && row.visible);
      return Promise.resolve(lesson ? { courseId: course.id, lessonId: lesson.id, durationSeconds: lesson.duration_seconds } : null);
    },
  };

  return {
    port: commands,
    ownersIn,
    lessons,
    reset() {
      assertOpen();
      state = blank();
      pendingEffect = null;
      effectDidRun = false;
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    seed(kind) {
      assertOpen();
      const fixture = kind === "ready" ? readyCatalogFixture() : emptyCatalogFixture();
      state = load(fixture);
      const courseId = kind === "ready" ? "course-ready" : "course-empty";
      return Promise.resolve({ courseId, revision: 1 });
    },
    course(courseId) {
      const { course, revision } = viewOf(courseId);
      return Promise.resolve({ status: course.status, revision });
    },
    journalCount(courseId) {
      return Promise.resolve(state.journal.filter((entry) => entry.entityId === courseId && entry.action === "course.status").length);
    },
    tables() { return Promise.resolve(structuredClone(state.tables)); },
    failNextEffect(message) {
      effectDidRun = false;
      pendingEffect = () => { throw new Error(message); };
    },
    effectRan: () => effectDidRun,
    transaction(work) { assertOpen(); return uow.run(work); },
  };
}
