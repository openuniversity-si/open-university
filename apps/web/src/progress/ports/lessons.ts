export interface PublishedLessonLookup {
  resolvePublishedLesson(courseSlug: string, lessonSlug: string): Promise<{ readonly courseId: string; readonly lessonId: string; readonly durationSeconds: number } | null>;
}
