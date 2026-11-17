export interface ProgressMaintenancePort {
  countForLessons(lessonIds: readonly string[]): Promise<number>;
  orphanedLessons(knownLessonIds: readonly string[]): Promise<{ count: number; sample: readonly string[] }>;
}
