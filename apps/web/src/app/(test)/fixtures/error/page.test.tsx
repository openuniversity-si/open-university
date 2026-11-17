/** Test build only: a render error, so E2E can prove the D6 error boundary inside the normal shell. */
export const dynamic = "force-dynamic";

export default function ErrorFixturePage(): never {
  throw new Error("Deliberate render error for the D6 error page test.");
}
