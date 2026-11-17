import { getCourseMedia } from "@tower/media";
import { signedOutHome } from "@/catalog/domain/home";
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { CourseCard } from "@/ui/CourseCard/CourseCard";
import { Rail } from "@/ui/Rail/Rail";

/** Reviewable first F06 slice; excluded from the production build. */
export default async function CardsFixturePage() {
  const home = signedOutHome(catalog, await getCourseMedia(catalog.courses.map((course) => course.id)));
  return <Rail id="poster-cards" title="Jordan B. Peterson">{(home.rails[0]?.courses ?? []).map((course) => <CourseCard key={course.id} course={course} />)}</Rail>;
}
