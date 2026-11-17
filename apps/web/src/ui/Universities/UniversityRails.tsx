import Link from "next/link";
import type { UniversityRailView } from "@/catalog/domain/view-model";
import { fill, seeAllTemplate } from "@/site/domain/reader-copy.ts";
import { CourseCard } from "@/ui/CourseCard/CourseCard";
import { Rail } from "@/ui/Rail/Rail";
import { isEagerPoster } from "@/ui/Rail/eager";
import { ChevronRightIcon } from "@/ui/icons/icons";
import styles from "./Universities.module.css";

/** The rails of a university page. Every course of each rail is a card; "See all N" links to the area page. */
export function UniversityRails({ rails }: { readonly rails: readonly UniversityRailView[] }) {
  return (
    <>
      {rails.map((rail, index) => (
        <div key={rail.id} className={styles["rail-anchor"]} data-area={rail.areaId} data-kind={rail.kind}>
          <Rail id={rail.id} title={rail.title} action={
            <Link className={styles["see-all"]} href={rail.href} prefetch={false} data-testid={`see-all-${rail.id}`}>{fill(seeAllTemplate, { count: String(rail.courses.length) })} <ChevronRightIcon /></Link>
          }>
            {rail.courses.map((course, card) => <CourseCard key={course.id} course={course} eager={isEagerPoster(index, card)} />)}
          </Rail>
        </div>
      ))}
    </>
  );
}
