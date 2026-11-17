/** Query seconds are retained for sign-in return; signed out, playback always starts at zero. */
export function requestedSecond(value: string | string[] | undefined, duration: number): number {
  if (typeof value !== "string" || value.trim() === "") return 0;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.min(Math.floor(seconds), duration) : 0;
}

export function lessonDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${String(Math.floor(minutes / 60))}h ${String(minutes % 60).padStart(2, "0")}m` : `${String(minutes)}m`;
}
