export interface IdentitySession {
  readonly userId: string;
  readonly expiresAt: number;
}

export interface IdentitySessionPort {
  session(headers: Headers, options: { readonly verifyRevocation: boolean }): Promise<IdentitySession | null>;
}
