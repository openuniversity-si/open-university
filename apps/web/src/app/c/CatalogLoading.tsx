import { mediaLoading } from "@/site/domain/reader-copy.ts";
import { CourseCardSkeleton } from "@/ui/CourseCardSkeleton/CourseCardSkeleton";
import styles from "@/app/status.module.css";

const SKELETONS = ["a", "b", "c", "d", "e", "f", "g", "h"] as const;

/**
 * §8.6: course and lesson transitions show a rail of CourseCardSkeleton (293:14477). Each route's loading.tsx sits
 * below its layout guard, so a 404 or 308 is decided before anything streams (ADR-17).
 */
export default function CatalogLoading() {
  return (
    <div className={styles.page} role="status" aria-label={mediaLoading} data-testid="tower-loading">
      <div className={styles.rail}>
        {SKELETONS.map((key) => (
          <CourseCardSkeleton key={key} />
        ))}
      </div>
    </div>
  );
}
