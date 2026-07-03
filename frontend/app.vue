<script setup>
// 应用启动时从 localStorage 恢复认证状态
const authStore = useAuthStore()
authStore.init()
</script>

<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
