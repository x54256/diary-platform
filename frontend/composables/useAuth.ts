/**
 * 认证状态 composable
 * 封装 auth store 的常用方法，简化页面调用
 */
export function useAuth() {
  const authStore = useAuthStore()

  return {
    // 状态
    token: computed(() => authStore.token),
    user: computed(() => authStore.user),
    isLoggedIn: computed(() => authStore.isLoggedIn),

    // 方法
    login: authStore.login,
    register: authStore.register,
    logout: authStore.logout,
    init: authStore.init,
  }
}
