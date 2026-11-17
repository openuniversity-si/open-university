import { AppError } from "../../kernel/errors.ts";
import type { MediaKind } from "./types.ts";

const KiB = 1024;
/**
 * Byte budget of a stored asset per kind (docs/media/README.md). Uploads above it are refused unless forced.
 * cover_16x9/cover_9x16 follow the measured p95 of the 126 lesson covers (297 KiB, 10/10/2026); optimizing
 * them is backlog. The media command reads this table (budget.test.ts checks it).
 */
export const MEDIA_BYTE_BUDGETS: Readonly<Record<MediaKind | "author_cover_9x16" | "university_cover_9x16" | "university_og", number>> = {
  poster_9x16: 120 * KiB,
  hero_desktop_16x9: 250 * KiB,
  hero_present: 250 * KiB,
  hero_mobile_9x16: 250 * KiB,
  still_16x9: 200 * KiB,
  lesson_default: 200 * KiB,
  og: 300 * KiB,
  cover_16x9: 300 * KiB,
  cover_9x16: 300 * KiB,
  thumb: 60 * KiB,
  author_cover_9x16: 300 * KiB,
  university_cover_9x16: 300 * KiB,
  university_og: 300 * KiB,
};

/** The stored bytes are larger than the kind's budget (nothing was stored). */
export class MediaBudgetError extends AppError {
  constructor(message: string) { super("payload_too_large", message); this.name = "MediaBudgetError"; }
}

const kib = (bytes: number) => `${String(Math.ceil(bytes / KiB))} KiB`;

/** Reason an asset of `size` bytes is over its kind's budget, or undefined when it fits. */
export function overBudget(kind: MediaKind, size: number): string | undefined {
  const budget = MEDIA_BYTE_BUDGETS[kind];
  return size > budget ? `${kind} is ${kib(size)}, over its ${kib(budget)} budget. Resize/compress it (WebP q≈78) or force a conscious exception with --force-oversize.` : undefined;
}

export function assertWithinBudget(kind: MediaKind, size: number, force = false) {
  const reason = overBudget(kind, size);
  if (reason && !force) throw new MediaBudgetError(reason);
}
