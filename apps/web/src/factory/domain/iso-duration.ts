// YouTube Data API contentDetails.duration (ISO-8601, PT#H#M#S). A zero length is not a lesson.

const DURATION = /^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/;

/** Seconds, or null when the value is not a YouTube duration. PT0S is 0. */
export function youtubeDurationSeconds(value: string): number | null {
  const match = DURATION.exec(value);
  if (!match || (match[1] === undefined && match[2] === undefined && match[3] === undefined)) return null;
  return Number(match[1] ?? 0) * 3600 + Number(match[2] ?? 0) * 60 + Number(match[3] ?? 0);
}
