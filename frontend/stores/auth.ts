import { defineStore } from 'pinia'
import type { User } from '~/types'
import { isTokenExpired } from '~/utils/auth-session'

// 认证状态管理
export const useAuthStore = defineStore('auth', {
  state: () => ({
    // 登录 token，从 localStorage 持久化读取
    token: '' as string,
    // 当前登录用户信息
    user: null as User | null,
  }),

  getters: {
    // 是否已登录
    isLoggedIn: (state) => !!state.token,
  },

  actions: {
    /**
     * 初始化：从 localStorage 读取 token 和用户信息
     * 在应用启动时调用
     */
    init() {
      if (import.meta.client) {
        const token = localStorage.getItem('token')
        const userStr = localStorage.getItem('user')
        if (token && isTokenExpired(token)) {
          this.logout()
          return
        }
        if (token) this.token = token
        if (userStr) {
          try {
            this.user = JSON.parse(userStr)
          } catch {
            this.user = null
          }
        }
      }
    },

    /**
     * 保存服务端续期后的令牌
     */
    setToken(token: string) {
      this.token = token
      if (import.meta.client) {
        localStorage.setItem('token', token)
      }
    },

    /**
     * 登录
     * @param username 用户名
     * @param password 密码
     */
    async login(username: string, password: string) {
      const config = useRuntimeConfig()
      try {
        const res = await $fetch<{ access_token: string; token_type: string; user: User }>(
          '/auth/login',
          {
            method: 'POST',
            body: { username, password },
            baseURL: config.public.apiBase,
          }
        )
        this.token = res.access_token
        this.user = res.user
        if (import.meta.client) {
          localStorage.setItem('token', res.access_token)
          localStorage.setItem('user', JSON.stringify(res.user))
        }
      } catch (error: any) {
        const detail = error?.data?.detail || '登录失败，请检查用户名和密码'
        throw new Error(detail)
      }
    },

    /** 注册并保存登录状态 */
    async register(username: string, password: string) {
      const config = useRuntimeConfig()
      try {
        const res = await $fetch<{ access_token: string; token_type: string; user: User }>(
          '/auth/register',
          {
            method: 'POST',
            body: { username, password },
            baseURL: config.public.apiBase,
          }
        )
        this.token = res.access_token
        this.user = res.user
        if (import.meta.client) {
          localStorage.setItem('token', res.access_token)
          localStorage.setItem('user', JSON.stringify(res.user))
        }
      } catch (error: any) {
        const detail = error?.data?.detail || '注册失败，请稍后重试'
        throw new Error(detail)
      }
    },

    /**
     * 登出
     */
    logout() {
      this.token = ''
      this.user = null

      // 清除 localStorage
      if (import.meta.client) {
        localStorage.removeItem('token')
        localStorage.removeItem('user')
      }
    },
  },
})
