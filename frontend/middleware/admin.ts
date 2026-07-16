/**
 * 管理端权限中间件
 * 当前系统以 username=admin 作为超级管理员。
 */
export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return

  const authStore = useAuthStore()
  authStore.init()

  if (!authStore.isLoggedIn) {
    return navigateTo(`/admin/login?redirect=${encodeURIComponent(to.fullPath)}`)
  }

  if (authStore.user?.username !== 'admin') {
    return navigateTo('/admin/forbidden')
  }
})
