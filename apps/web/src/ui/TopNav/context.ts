/** TopNav 21:61 Context: Home on `/` and every non-course page; Course on Course and Player (D10). */
export interface TopNavContext {
  readonly context: "home" | "course";
  /** The active Primary tab; null on Course and Player. */
  readonly tab: "home" | "universities" | "authors" | null;
  /** D10: "‹" goes to the parent (Player → Course, Course → Home), never `history.back()`. */
  readonly back: { readonly href: string; readonly label: string } | null;
}

export function topNavContext(pathname: string, labels: { readonly home: string; readonly course: string }): TopNavContext {
  const segments = pathname.split("/").filter((segment) => segment !== "");
  if (segments[0] !== "c" || segments.length < 2 || segments.length > 3) {
    // Universities keeps its tab on its university and area pages (ADR-25).
    const tab = segments[0] === "universities" && segments.length <= 3 ? "universities" : segments.length === 1 && segments[0] === "authors" ? "authors" : segments.length === 0 ? "home" : null;
    return { context: "home", tab, back: null };
  }
  if (segments.length === 2) return { context: "course", tab: null, back: { href: "/", label: labels.home } };
  return { context: "course", tab: null, back: { href: `/c/${segments[1] ?? ""}`, label: labels.course } };
}
