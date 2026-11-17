"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

const subscribe = () => () => {};
/** Body-level overlays stay above a later desktop Player, including transformed ancestors. */
export function OverlayLayer({ children }: { readonly children: ReactNode }) {
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  return mounted ? createPortal(children, document.body) : null;
}
