import { getCourseMedia } from "@tower/media";
import { signedOutHome } from "@/catalog/domain/home";
import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { CourseCard } from "@/ui/CourseCard/CourseCard";
import { CoursePlaylist } from "@/ui/PlaylistItem/CoursePlaylist";
import styles from "@/app/status.module.css";

/** 293:14604 C stress texts. */
const LONG_COURSE_TITLE = "Awakening from the Meaning Crisis: The Complete Lecture Series and Commentary";
const LONG_LESSON_TITLE = "XII: The Psychology of the Flood, Noah and the Tower of Babel, with an Extended Q&A";

/** Test-only long titles (293:14604 C): poster and Continue cards, and a playlist row. */
export default async function LongTitlesFixturePage() {
  const course = catalog.courses[3];
  if (!course) throw new Error("The fixture needs the fourth catalog course.");
  const home = signedOutHome(catalog, await getCourseMedia(catalog.courses.map((course) => course.id)));
  const cover = home.rails.flatMap((rail) => rail.courses).find((entry) => entry.id === course.id);
  if (!cover) throw new Error("The fixture needs the fourth course's card.");
  // An id outside the prototype's short cover names, so the card shows the catalog title.
  const long = { ...cover, id: "long-title", title: LONG_COURSE_TITLE };
  return (
    <div className={styles.page}>
      <h1>Long titles</h1>
      <div className={styles.rail} data-testid="fixture-long-titles">
        <CourseCard course={long} />
        <CourseCard course={long} resume={{ label: "Lecture 4 of 17", remaining: "1h 40m left", fraction: 0.42, href: "/" }} />
      </div>
      <CoursePlaylist title={LONG_COURSE_TITLE} noun="Lecture" thumbnails={[null]}
        lessons={[{ id: "long-title", href: "/", title: LONG_LESSON_TITLE, label: "Lecture 12", duration: "2h 38m" }]} />
    </div>
  );
}
