import { homeRowKind, homeRowKinds } from "../../kernel/home-row-kind.ts";
import { universityCoverSchema } from "./university-cover.ts";

/** Home row kinds. The words live in the kernel so the database CHECK reads the same list. */
export { homeRowKind, homeRowKinds };

export type HomeRowTab = "universities" | "authors";

/** What one kind does, read as data so a check stays a check. */
export type HomeRowSpec = {
  readonly maxRows: number | null;
  readonly catalogCourses: boolean;
  readonly titleRequired: boolean;
  readonly author: boolean;
  readonly institution: boolean;
  readonly cover: "none" | "own" | "author";
  readonly fullName: boolean;
  readonly place: boolean;
  readonly tab: HomeRowTab | null;
};

/**
 * What one Home-row kind already does. Readers use this sheet; they do not grow a second list of kinds.
 * A kind with no tab stays off the Home portals.
 */
export const homeRowSheet = {
  continue: {
    maxRows: 1,
    catalogCourses: false,
    titleRequired: false,
    author: false,
    institution: false,
    cover: "none",
    fullName: false,
    place: false,
    tab: null,
  },
  author: {
    maxRows: null,
    catalogCourses: true,
    titleRequired: false,
    author: true,
    institution: false,
    cover: "author",
    fullName: false,
    place: false,
    tab: "authors",
  },
  curated: {
    maxRows: null,
    catalogCourses: true,
    titleRequired: true,
    author: false,
    institution: true,
    cover: "own",
    fullName: true,
    place: true,
    tab: "universities",
  },
} as const satisfies Record<(typeof homeRowKinds)[number], HomeRowSpec>;

/** The sheet for one Home-row kind, read as data so a check is not collapsed by the kind. */
export function homeRowSpec(kind: (typeof homeRowKinds)[number]): HomeRowSpec {
  return homeRowSheet[kind];
}

/**
 * One Home row, as both compilers emit it. The caller resolves the title.
 * Cover, full name and place are emitted only when this kind's sheet allows them.
 */
export function projectHomeRow(row: {
  readonly id: string;
  readonly kind: (typeof homeRowKinds)[number];
  readonly title: string;
  readonly authorId: string | null;
  readonly institutionId: string | null | undefined;
  readonly courseIds: readonly string[];
  readonly cover: unknown;
  readonly fullName: string | null;
  readonly place: string | null;
}) {
  const spec = homeRowSpec(row.kind);
  return {
    id: row.id,
    kind: row.kind,
    title: row.title,
    ...(row.authorId === null ? {} : { authorId: row.authorId }),
    ...(row.institutionId ? { institutionId: row.institutionId } : {}),
    courseIds: [...row.courseIds],
    ...(spec.cover === "own" && row.cover ? { cover: universityCoverSchema.parse(row.cover) } : {}),
    ...(spec.fullName && row.fullName !== null ? { fullName: row.fullName } : {}),
    ...(spec.place && row.place !== null ? { place: row.place } : {}),
  };
}

/** The sheet for a stored kind, or nothing when the word is not a Home-row kind. */
export function homeRowRecord(kind: string): HomeRowSpec | undefined {
  return (homeRowKinds as readonly string[]).includes(kind) ? homeRowSpec(kind as (typeof homeRowKinds)[number]) : undefined;
}
