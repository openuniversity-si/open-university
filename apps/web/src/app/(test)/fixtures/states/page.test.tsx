import Loading from "@/app/c/CatalogLoading";
import { emptyCatalogBody, emptyCatalogTitle } from "@/site/domain/reader-copy";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";
import styles from "@/app/status.module.css";

/** Test-only examples of the approved empty/skeleton components and the CTA states. */
export default function StatesFixturePage() {
  return (
    <div className={styles.page}>
      <EmptyCatalog headingLevel="h1" title={emptyCatalogTitle} body={emptyCatalogBody} />
      <PrimaryCTA href="/" play>Start</PrimaryCTA>
      <PrimaryCTA href="/" play disabled>Start</PrimaryCTA>
      <PrimaryCTA href="/" kind="secondary" arrow>Course details</PrimaryCTA>
      <Loading />
    </div>
  );
}
