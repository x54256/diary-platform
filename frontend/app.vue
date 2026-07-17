<script setup lang="ts">
// 应用启动时从 localStorage 恢复认证状态
const authStore = useAuthStore()
authStore.init()
const router = useRouter()
let expiryTimer: ReturnType<typeof setTimeout> | null = null

const checkSessionExpiry = () => {
  if (!authStore.token) return
  const expiresAt = getTokenExpiresAt(authStore.token)
  if (expiresAt === null || expiresAt <= Date.now()) {
    const currentPath = router.currentRoute.value.fullPath
    authStore.logout()
    if (router.currentRoute.value.path !== '/login') {
      void navigateTo(getLoginPath(currentPath))
    }
    return
  }

  // 浏览器定时器存在最大延时限，每天重新校验直到真正过期。
  expiryTimer = setTimeout(checkSessionExpiry, Math.min(expiresAt - Date.now(), 24 * 60 * 60 * 1000))
}

watch(() => authStore.token, () => {
  if (expiryTimer) clearTimeout(expiryTimer)
  expiryTimer = null
  checkSessionExpiry()
}, { immediate: true })

onBeforeUnmount(() => {
  if (expiryTimer) clearTimeout(expiryTimer)
})
</script>

<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
