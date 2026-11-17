"use client";

import type { ReactNode } from "react";
import { AuthProvider } from "@/identity/client/AuthProvider";
import { ContinuingWithGoogle } from "@/ui/identity/ContinuingWithGoogle";
import { SignInFeedback } from "@/ui/identity/SignInFeedback";

/** Client boundary: the server layout cannot pass components into AuthProvider. */
export function AuthShell({ children }: { readonly children: ReactNode }) {
  return <AuthProvider slots={{ busyOverlay: ContinuingWithGoogle, signInFeedback: SignInFeedback }}>{children}</AuthProvider>;
}
