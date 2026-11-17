import type { courseView } from "../domain/course-view.ts";
import type { RuleOptions } from "../domain/rules/status.ts";
import type { CatalogState } from "../domain/rules-helpers.ts";

export interface StatusChange {
  readonly courseId: string;
  readonly expectedRevision: number;
  readonly target: "draft" | "review" | "archived";
}
export interface CatalogStatePort {
  /** Locks the course and checks its revision before facts and rules run. */
  read(expected: Pick<StatusChange, "courseId" | "expectedRevision">): Promise<CatalogState>;
  /** Compare-and-swap. A revision conflict writes neither state nor journal. */
  changeStatus(change: StatusChange): Promise<{
    readonly revision: number;
    readonly course: ReturnType<typeof courseView>;
  }>;
}
export interface CatalogCommandsPort {
  transition(change: StatusChange, options?: RuleOptions): Promise<{
    readonly revision: number;
    readonly course: ReturnType<typeof courseView>;
  }>;
}
