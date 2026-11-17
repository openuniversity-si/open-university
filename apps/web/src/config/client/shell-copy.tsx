"use client";

import { createContext, useContext, type ReactNode } from "react";
import {
  accountForTemplate, authorsTitle, brandHomeLabel, homeTitle, legalLabel, primaryNavLabel, signInLabel, skipToContent, universitiesTitle,
} from "@/site/domain/reader-copy.ts";

/** The shell strings. The default is the code, so a page with no stored revision renders those words. */
export const shellCopyDefaults = {
  skipToContent,
  homeTitle,
  universitiesTitle,
  authorsTitle,
  brandHomeLabel,
  primaryNavLabel,
  signInLabel,
  accountForTemplate,
  legalLabel,
} as const;

const ShellCopyContext = createContext<Readonly<Record<string, string>>>(shellCopyDefaults);

export function ShellCopyProvider({ copy, children }: { readonly copy: Readonly<Record<string, string>>; readonly children: ReactNode }) {
  return <ShellCopyContext.Provider value={copy}>{children}</ShellCopyContext.Provider>;
}

export function useShellCopy(): Readonly<Record<string, string>> {
  return useContext(ShellCopyContext);
}
