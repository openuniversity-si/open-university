import styles from "./CourseCardSkeleton.module.css";

/** Skeleton / CourseCard 293:14477: Size=Mobile 140 below 1024 px, Size=Desktop 208 from 1024 px. Static (no shimmer). */
export function CourseCardSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true" data-testid="tower-course-card-skeleton">
      <div className={styles.cover} />
      <div className={styles.meta}>
        <div className={styles.line} />
        <div className={styles.line} />
        <div className={styles.line} />
      </div>
    </div>
  );
}
