import { describe, expect, it } from "vitest";
import { topNavContext } from "./context";

const labels = { home: "Back to Home", course: "Back to course" };
const nav = (path: string) => topNavContext(path, labels);

describe("topNavContext (TopNav Context, D10)", () => {
  it("uses the Home context without a back link on Home and other pages", () => {
    expect(nav("/")).toEqual({ context: "home", tab: "home", back: null });
    expect(nav("/privacy")).toEqual({ context: "home", tab: null, back: null });
    expect(nav("/c")).toEqual({ context: "home", tab: null, back: null });
    expect(nav("/c/genesis/lesson/extra")).toEqual({ context: "home", tab: null, back: null });
  });

  it("marks the active Primary tab on /universities and /authors", () => {
    expect(nav("/universities")).toEqual({ context: "home", tab: "universities", back: null });
    expect(nav("/universities/mit")).toEqual({ context: "home", tab: "universities", back: null });
    expect(nav("/universities/mit/economics")).toEqual({ context: "home", tab: "universities", back: null });
    expect(nav("/authors/")).toEqual({ context: "home", tab: "authors", back: null });
  });

  it("points Course to Home and Player to its Course", () => {
    expect(nav("/c/genesis")).toEqual({ context: "course", tab: null, back: { href: "/", label: "Back to Home" } });
    expect(nav("/c/genesis/")).toEqual({ context: "course", tab: null, back: { href: "/", label: "Back to Home" } });
    expect(nav("/c/genesis/adam-and-eve")).toEqual({ context: "course", tab: null, back: { href: "/c/genesis", label: "Back to course" } });
  });
});
