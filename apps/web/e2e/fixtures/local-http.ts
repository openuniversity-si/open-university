import type { APIRequestContext } from "@playwright/test";

/** Local API requests use one connection each, so a paused worker cannot reuse an expired socket. */
export function localHttpHeaders(baseURL: string | undefined): Record<string, string> {
  if (!baseURL) return {};
  const url = new URL(baseURL);
  return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    ? { Connection: "close" }
    : {};
}

/** All APIRequestContext verbs dispatch through fetch; browser requests keep their native transport. */
export function applyLocalHttpPolicy(api: APIRequestContext, baseURL: string | undefined): () => void {
  const headers = localHttpHeaders(baseURL);
  if (!headers.Connection) return () => {};
  // eslint-disable-next-line @typescript-eslint/unbound-method -- Invoke with the original API context below, and restore the exact method.
  const original = api.fetch;
  const fetch = original.bind(api);
  api.fetch = <T>(url: Parameters<APIRequestContext["fetch"]>[0], options?: Parameters<APIRequestContext["fetch"]>[1]) => fetch<T>(url, {
    ...options,
    headers: { ...options?.headers, ...headers },
  });
  return () => { api.fetch = original; };
}
