import { randomUUID } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { courseBySlug, lessonBySlug } from "../../src/catalog/domain/queries.ts";
import { snapshotCatalog as catalog } from "../../src/catalog/testing/fake.ts";
import { handleProgressPost, type ProgressRequestDependencies } from "../../src/progress/server/handler.ts";
import { readProgress } from "../../src/progress/server/repo.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";

const origin = "https://openuniversity.si";
const genesis = "fixture-course-1";
const lessonFour = "fixture-lesson-4";

describe("POST /api/progress on real PostgreSQL", () => {
  let pool: pg.Pool;
  let deps: ProgressRequestDependencies;
  let viewer: string | null;
  const users: string[] = [];

  const post = (body: unknown, headers: Record<string, string> = { origin }) => handleProgressPost(new Request(`${origin}/api/progress`, {
    method: "POST", headers: { "content-type": "application/json", ...headers }, body: typeof body === "string" ? body : JSON.stringify(body),
  }), deps);
  async function newViewer() {
    const id = randomUUID(); users.push(id);
    await pool.query('INSERT INTO "user" (id, name, email) VALUES ($1, $2, $3)', [id, "Progress Viewer", `${id}@example.invalid`]);
    viewer = id;
    return id;
  }
  const age = (id: string, seconds: number) => pool.query("UPDATE lesson_progress SET updated_at = updated_at - make_interval(secs => $2) WHERE user_id = $1", [id, seconds]);

  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required; no progress database mocks.");
    validateDatabaseUrl(connectionString, "container");
    await runMigrations(connectionString, false);
    pool = new pg.Pool({ connectionString });
    deps = {
      db: () => pool, expectedOrigin: () => origin, userId: () => Promise.resolve(viewer),
      resolvePublishedLesson: (courseSlug, lessonSlug) => {
        const course = courseBySlug(catalog, courseSlug);
        const lesson = course ? lessonBySlug(catalog, course.id, lessonSlug) : undefined;
        return Promise.resolve(course && lesson ? { courseId: course.id, lessonId: lesson.id, durationSeconds: lesson.durationSeconds } : null);
      },
    };
  });
  afterAll(async () => {
    await pool.query('DELETE FROM "user" WHERE id = ANY($1::text[])', [users]);
    await pool.end();
  });

  it("refuses foreign origins, signed-out viewers, bad bodies and unknown lessons without writing", async () => {
    const id = await newViewer();
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 10 }, { origin: "https://evil.example" })).status).toBe(403);
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 10 }, {})).status).toBe(403);
    viewer = null;
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 10 })).status).toBe(401);
    viewer = id;
    for (const body of ["{", "null", { courseSlug: genesis, lessonSlug: lessonFour }, { courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: "10" },
      { courseSlug: genesis, lessonSlug: lessonFour, completed: "yes" }, { courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 1, pad: "x".repeat(2000) }]) {
      expect((await post(body)).status).toBeGreaterThanOrEqual(400);
    }
    expect((await post({ courseSlug: genesis, lessonSlug: "no-such-lesson", positionSeconds: 10 })).status).toBe(404);
    expect((await post({ courseSlug: "fixture-course-2", lessonSlug: lessonFour, positionSeconds: 10 })).status).toBe(404);
    expect(await readProgress(pool, id)).toEqual([]);
  });

  it("clamps positions, throttles checkpoints to one per 5 s, and the last writer wins", async () => {
    const id = await newViewer();
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 99_999 })).status).toBe(204);
    expect((await readProgress(pool, id))[0]).toMatchObject({ lessonId: "lesson-4", courseId: "course-1", positionSeconds: 3600, durationSeconds: 3600, completed: false });
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 30 })).status).toBe(429);
    await age(id, 6);
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: -4.5 })).status).toBe(204);
    expect((await readProgress(pool, id))[0]?.positionSeconds).toBe(0);
    await age(id, 6);
    // Another device writes an earlier position later: it wins.
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 120.9 })).status).toBe(204);
    expect((await readProgress(pool, id))[0]?.positionSeconds).toBe(120);
  });

  it("completion always applies, keeps the position and survives later checkpoints until unchecked", async () => {
    const id = await newViewer();
    await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 500 });
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, completed: true })).status).toBe(204);
    expect((await readProgress(pool, id))[0]).toMatchObject({ positionSeconds: 500, completed: true });
    await age(id, 6);
    await post({ courseSlug: genesis, lessonSlug: lessonFour, positionSeconds: 600 });
    expect((await readProgress(pool, id))[0]).toMatchObject({ positionSeconds: 600, completed: true });
    expect((await post({ courseSlug: genesis, lessonSlug: lessonFour, completed: false })).status).toBe(204);
    expect((await readProgress(pool, id))[0]).toMatchObject({ completed: false });
    expect((await post({ courseSlug: genesis, lessonSlug: "fixture-lesson-5", completed: true })).status).toBe(204);
    expect((await readProgress(pool, id)).find((row) => row.lessonId === "lesson-5")).toMatchObject({ positionSeconds: 0, completed: true });
  });
});
