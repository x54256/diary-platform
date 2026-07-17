const decodePayload = (token: string): { exp?: number } | null => {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return null
  }
}

export const getTokenExpiresAt = (token: string): number | null => {
  const expiration = decodePayload(token)?.exp
  return typeof expiration === 'number' ? expiration * 1000 : null
}

export const isTokenExpired = (token: string, now = Date.now()): boolean => {
  const expiresAt = getTokenExpiresAt(token)
  return expiresAt === null || expiresAt <= now
}

export const getLoginPath = (currentPath: string): string =>
  `/login?redirect=${encodeURIComponent(currentPath)}`

export const getSafeRedirect = (redirect: unknown): string => {
  if (typeof redirect !== 'string' || !redirect.startsWith('/') || redirect.startsWith('//')) {
    return '/'
  }
  return redirect
}
