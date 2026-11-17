import { snapshotCatalog as catalog } from "@/catalog/testing/fake";
import { signedOutHome, type HomeRail } from "@/catalog/domain/home";
import { BillboardSelection } from "@/ui/Billboard/BillboardSelection";
import { homeShelves } from "@/ui/showcase/home-shelves";

/** Poster bytes: the e2e (lazy-posters.spec.ts) answers these requests; nothing is stored. */
const LAZY_POSTER_PATH = "/fixtures/lazy-posters/poster/";
const ROWS = 8;
const CARDS = 24;

/** Test-only Home at catalog scale (P8): the real BillboardSelection with 8 rails of 24 courses, one poster each. */
export default function LazyPostersFixturePage() {
  const home = signedOutHome(catalog);
  const featured = home.featured;
  const courses = home.rails.flatMap((rail) => rail.courses);
  if (!featured || courses.length === 0) throw new Error("The fixture needs the snapshot's featured course and rails.");
  const rails: HomeRail[] = Array.from({ length: ROWS }, (_, row) => ({
    id: `fixture-row-${String(row + 1)}`,
    title: `Row ${String(row + 1)}`,
    courses: Array.from({ length: CARDS }, (_, card) => {
      const id = `fixture-${String(row + 1)}-${String(card + 1)}`;
      const base = courses[card % courses.length] ?? featured;
      return { ...base, id, title: `${base.title} ${String(card + 1)}`, assets: { poster: { url: `${LAZY_POSTER_PATH}${id}.svg`, width: 540, height: 960, transform: null } } };
    }),
  }));
  return <BillboardSelection featured={featured} shelves={homeShelves(rails)} intro={{ text: "Great lectures, in order. Universal, Free & Luxurious.", link: "About Open University", href: "/about" }} />;
}
