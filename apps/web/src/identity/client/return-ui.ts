import { AUTH_RETURN_UI_KEY as KEY } from "../../kernel/brand-ids.ts";
export interface ReturnUI {
  route: string;
  scrollX: number;
  scrollY: number;
  selection: Record<string, string | undefined>;
  rails: { id: string; left: number }[];
}

// Hand-written on purpose: this module ships in every page's shell, and zod alone was ~34 KB gzip of it.
const isOffset = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

/** The stored value when it has the ReturnUI shape (unknown keys dropped), else null. */
export function parseReturnUI(value: unknown): ReturnUI | null {
  if (!isRecord(value)) return null;
  const { route, scrollX, scrollY, selection, rails } = value;
  if (typeof route !== "string" || !isOffset(scrollX) || !isOffset(scrollY)) return null;
  if (!isRecord(selection) || !Object.values(selection).every((entry) => entry === undefined || typeof entry === "string")) return null;
  if (!Array.isArray(rails) || !rails.every((rail) => isRecord(rail) && typeof rail.id === "string" && isOffset(rail.left))) return null;
  return { route, scrollX, scrollY, selection: { ...selection } as Record<string, string | undefined>, rails: (rails as { id: string; left: number }[]).map(({ id, left }) => ({ id, left })) };
}

export function saveReturnUI(value: ReturnUI): void {
  try { sessionStorage.setItem(KEY, JSON.stringify(value)); } catch { /* Navigation still works without storage. */ }
}

export function takeReturnUI(route: string): ReturnUI | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    const result = parseReturnUI(JSON.parse(raw ?? "null"));
    return result?.route === route ? result : null;
  } catch { return null; }
}
