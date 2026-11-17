export const REQUEST_ID_HEADER = "x-request-id";
const REQUEST_ID = /^[A-Za-z0-9._-]{1,64}$/;
export interface RequestContext { readonly requestId: string; readonly route: string; readonly startedAt: number }
export function requestIdFrom(header: string | null, uuid: () => string): string {
  return header !== null && REQUEST_ID.test(header) ? header : uuid();
}
export function requestContextFrom(request: Request, route: string, uuid: () => string = () => crypto.randomUUID()): RequestContext {
  return { requestId: requestIdFrom(request.headers.get(REQUEST_ID_HEADER), uuid), route, startedAt: Date.now() };
}
