/** The body the sign-in screen posts. The provider value is filled by the client adapter. */
export interface SignInRequest {
  readonly provider: string;
  readonly callbackURL: string;
  readonly newUserCallbackURL: string;
  readonly errorCallbackURL: string;
}

type SignInRequestBuilder = (route: string, currentSecond?: number) => SignInRequest;
type SignInRedirect = (url: URL) => boolean;

let buildSignInRequest: SignInRequestBuilder | undefined;
let acceptSignInRedirect: SignInRedirect | undefined;

export function registerSignInRequest(build: SignInRequestBuilder): void {
  buildSignInRequest = build;
}

export function registerSignInRedirect(accept: SignInRedirect): void {
  acceptSignInRedirect = accept;
}

export function createSignInRequest(route: string, currentSecond?: number): SignInRequest {
  if (!buildSignInRequest) throw new Error("Sign-in is not available.");
  return buildSignInRequest(route, currentSecond);
}

export function isSignInRedirect(url: URL): boolean {
  if (!acceptSignInRedirect) throw new Error("Sign-in is not available.");
  return acceptSignInRedirect(url);
}
