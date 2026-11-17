import { towerPosterNearMargin } from "../tokens/values";

/** Requests a poster once it comes within this distance of the viewport, on both axes. */
export const NEAR_MARGIN = towerPosterNearMargin;

const callbacks = new WeakMap<Element, () => void>();
let observer: IntersectionObserver | undefined;

function shared(): IntersectionObserver {
  observer ??= new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer?.unobserve(entry.target);
      callbacks.get(entry.target)?.();
      callbacks.delete(entry.target);
    }
  // scrollMargin widens every scroll container on the way, the page and each rail's horizontal clip; rootMargin only
  // the viewport (cards past a rail's edge stay clipped). Both together add up (400px), so one or the other.
  }, "scrollMargin" in IntersectionObserver.prototype ? { scrollMargin: NEAR_MARGIN } : { rootMargin: NEAR_MARGIN });
  return observer;
}

/** One observer for every poster. Without IntersectionObserver, shows at once and native `loading="lazy"` takes over. */
export function whenNear(element: Element, show: () => void): () => void {
  if (typeof IntersectionObserver === "undefined") {
    show();
    return () => undefined;
  }
  callbacks.set(element, show);
  shared().observe(element);
  return () => {
    callbacks.delete(element);
    observer?.unobserve(element);
  };
}
