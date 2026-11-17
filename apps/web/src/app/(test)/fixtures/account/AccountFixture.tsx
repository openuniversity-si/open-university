"use client";

import { useState } from "react";
import { AccountMenuOverlay } from "@/ui/identity/AccountMenu";
import { SignInFeedback } from "@/ui/identity/SignInFeedback";

export function AccountFixture({ kind, capture = false }: { readonly kind: "menu" | "error" | "cancelled"; readonly capture?: boolean }) {
  const [open, setOpen] = useState(true);
  const [action, setAction] = useState("");
  return <>
    {!capture ? <div style={{ paddingTop: 80 }}><button type="button" onClick={() => { setOpen(true); }} data-testid="account-fixture-open">Open account</button></div> : null}
    {!capture ? <output data-testid="account-fixture-action">{action}</output> : null}
    {open ? kind === "menu" ? <AccountMenuOverlay name="Daniel Bello" onClose={() => { setOpen(false); }} onSignOut={() => { setAction("Sign out"); setOpen(false); }} /> : <SignInFeedback kind={kind} onRetry={() => { setAction("Try again"); }} /> : null}
  </>;
}
