/**
 * The one place that names what the browser shows the visitor under the product's name: cookie names and storage keys.
 * They carry the product name (Open University, ADR-20), not the organization's. Internal identifiers (`tower-*` test ids,
 * CSS tokens, the `x-tower-actor` API header, the repository) keep "tower" on purpose and are not user-visible.
 * Never hard-code these strings elsewhere: `brand-ids.test.ts` fails if one reappears. Changing BRAND_ID signs everyone out.
 * No imports: this file ships in the client bundle.
 */
export const BRAND_ID = "open-university";
/** Session cookie prefix: the cookie is `open-university.session_token` (`__Secure-` on HTTPS). */
export const AUTH_COOKIE_PREFIX = BRAND_ID;
/** Draft-preview cookie of the admin catalog API (httpOnly, operator only). */
export const PREVIEW_COOKIE_NAME = `${BRAND_ID}-preview`;
/** `sessionStorage` keys. */
export const PENDING_COMPLETION_KEY = `${BRAND_ID}:pending-completion:v1`;
export const AUTH_RETURN_UI_KEY = `${BRAND_ID}:auth-return-ui:v1`;
