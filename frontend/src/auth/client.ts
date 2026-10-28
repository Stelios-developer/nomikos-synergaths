import { createAuthClient } from 'better-auth/react'

// Vite proxies this path to Better Auth locally. In production set this to
// the auth subdomain which shares the secure Documents Made Clear cookie domain.
const authBaseUrl = import.meta.env.VITE_AUTH_BASE_URL || window.location.origin

export const authClient = createAuthClient({
  baseURL: authBaseUrl,
  basePath: '/api/auth',
  fetchOptions: { credentials: 'include' },
})
