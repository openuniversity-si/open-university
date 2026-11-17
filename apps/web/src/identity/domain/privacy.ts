export function minimizeUser<T extends object>(data: T) {
  return { ...data, image: null };
}

export function minimizeSession<T extends object>(data: T) {
  return { ...data, ipAddress: null, userAgent: null };
}

export function minimizeAccount<T extends object>(data: T) {
  return {
    ...data,
    accessToken: null,
    refreshToken: null,
    idToken: null,
    accessTokenExpiresAt: null,
    refreshTokenExpiresAt: null,
    scope: null,
    password: null,
  };
}
