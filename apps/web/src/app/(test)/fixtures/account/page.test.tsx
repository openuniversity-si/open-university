import HomePage from "@/app/page";
import { AccountFixture } from "./AccountFixture";

export default async function AccountFixturePage({ searchParams }: { readonly searchParams: Promise<{ kind?: string; capture?: string }> }) {
  const { kind, capture } = await searchParams;
  const variant = kind === "error" || kind === "cancelled" ? kind : "menu";
  return <>
    {variant !== "menu" ? <HomePage /> : null}
    <AccountFixture kind={variant} capture={capture === "1"} />
  </>;
}
