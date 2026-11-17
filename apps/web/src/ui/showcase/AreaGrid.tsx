import type { HomeCourse } from "@/catalog/domain/home.ts";
import type { AreaGroup } from "@/catalog/domain/universities.ts";
import { cardView } from "@/catalog/domain/view-model.ts";
import { otherLabel } from "@/site/domain/reader-copy.ts";
import { CourseCard } from "@/ui/CourseCard/CourseCard.tsx";
import { isEagerPoster } from "@/ui/Rail/eager.ts";
import styles from "@/ui/Universities/Universities.module.css";

/** The heading a split section shows. A leftover group keeps the title the area page shows today. */
export function areaSectionTitle(group: Pick<AreaGroup, "kind" | "title">): string {
  return group.kind === "rest" ? otherLabel : group.title;
}

/** The area page's grid. Groups, the title, and the meta are already written; this only paints them. */
export function AreaGrid({ title, meta, groups }: {
  readonly title: string;
  readonly meta: string;
  readonly groups: readonly AreaGroup[];
}) {
  const grid = (courses: readonly HomeCourse[], offset: number) => (
    <div className={styles["area-grid"]}>
      {courses.map((course, index) => {
        const card = offset + index;
        return <CourseCard key={course.id} course={cardView(course)} eager={isEagerPoster(Math.floor(card / 7), card % 7)} />;
      })}
    </div>
  );
  const only = groups.length === 1 ? groups[0] : undefined;
  return (
    <>
      <h1 className={styles["area-title"]}>{title}</h1>
      <p className={styles["area-meta"]}>{meta}</p>
      {only ? grid(only.courses, 0) : groups.map((group, index) => (
        <section key={group.id} id={group.id} className={styles["area-section"]} data-kind={group.kind} aria-labelledby={`${group.id}-title`}>
          <h2 id={`${group.id}-title`} className={styles["area-section-title"]}>{areaSectionTitle(group)}</h2>
          {grid(group.courses, groups.slice(0, index).reduce((sum, previous) => sum + previous.courses.length, 0))}
        </section>
      ))}
    </>
  );
}
