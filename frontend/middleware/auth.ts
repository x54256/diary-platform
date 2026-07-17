/**
 * 认证中间件
 * 检查用户是否已登录，未登录则跳转到登录页
 */
export default defineNuxtRouteMiddleware((to, from) => {
  if (import.meta.server) return

  const authStore = useAuthStore()

  // 初始化（从 localStorage 读取 token）
  authStore.init()

  // 如果未登录且访问的不是登录页，则跳转到登录页
  if (!authStore.isLoggedIn && to.path !== '/login') {
    return navigateTo(getLoginPath(to.fullPath))
  }

  // 如果已登录且访问的是登录页，则跳转到主页
  if (authStore.isLoggedIn && to.path === '/login') {
    return navigateTo(getSafeRedirect(to.query.redirect))
  }
})
