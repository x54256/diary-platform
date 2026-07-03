import type { FetchOptions } from 'ofetch'

/**
 * API 请求封装
 * - 自动添加 Authorization header
 * - baseURL 从 runtimeConfig 读取
 */
export function useApi() {
  const config = useRuntimeConfig()
  const authStore = useAuthStore()

  /**
   * 封装 $fetch，自动携带 token
   */
  const api = <T = any>(
    url: string,
    options: FetchOptions = {}
  ): Promise<T> => {
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
    })
  }

  return {
    api,
  }
}
