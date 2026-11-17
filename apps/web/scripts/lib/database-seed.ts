import { lessonProgress, user } from "../../src/platform/db/schema.ts";
import { databaseForClient, type DatabaseClient } from "./database-client.ts";

export async function seedDatabase(client: DatabaseClient): Promise<void> {
  const db = databaseForClient(client);
  await db.transaction(async (tx) => {
    await tx.insert(user).values({ id: "tower-synthetic-viewer", name: "Synthetic Viewer", email: "viewer@example.invalid", emailVerified: true }).onConflictDoNothing();
    await tx.insert(lessonProgress).values([
      { userId: "tower-synthetic-viewer", courseId: "synthetic-course", lessonId: "synthetic-lesson-1", positionSeconds: 120, durationSeconds: 600, updatedAt: new Date("2026-01-01T12:00:00Z") },
      { userId: "tower-synthetic-viewer", courseId: "synthetic-course", lessonId: "synthetic-lesson-2", positionSeconds: 600, durationSeconds: 600, completedAt: new Date("2026-01-01T13:00:00Z"), updatedAt: new Date("2026-01-01T13:00:00Z") },
    ]).onConflictDoNothing();
  });
}
