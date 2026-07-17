import type { FetchOptions } from 'ofetch'

/**
 * API 请求封装
 * - 自动添加 Authorization header
 * - baseURL 从 runtimeConfig 读取
 */
export function useApi() {
  const config = useRuntimeConfig()
  const authStore = useAuthStore()
  const router = useRouter()

  const redirectToLogin = async () => {
    const currentPath = router.currentRoute.value.fullPath
    authStore.logout()
    if (router.currentRoute.value.path !== '/login') {
      await navigateTo(getLoginPath(currentPath))
    }
  }

  /**
   * 封装 $fetch，自动携带 token
   */
  const api = <T = any>(
    url: string,
    options: FetchOptions = {}
  ): Promise<T> => {
    if (authStore.token && isTokenExpired(authStore.token)) {
      void redirectToLogin()
      return Promise.reject(new Error('登录状态已失效'))
    }

    // 构建请求头
    const headers: Record<string, string> = {
      ...((options.headers as Record<string, string>) || {}),
    }

    // 如果有 token，自动添加 Authorization
    if (authStore.token) {
      headers['Authorization'] = `Bearer ${authStore.token}`
    }

    return $fetch<T>(url, {
      ...options,
      baseURL: config.public.apiBase,
      headers,
      onResponse({ response }) {
        const renewedToken = response.headers.get('X-Access-Token')
        if (renewedToken) authStore.setToken(renewedToken)
      },
      async onResponseError({ response }) {
        if (response.status === 401) await redirectToLogin()
      },
    })
  }

  return {
    api,
  }
}
