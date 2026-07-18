<template>
  <div class="min-h-dvh bg-neutral-100 flex items-center justify-center px-4">
    <div class="w-full max-w-md bg-white border border-neutral-200 rounded p-8 text-center">
      <div class="text-lg font-medium text-neutral-900">无权限访问管理端</div>
      <p class="mt-2 text-sm text-neutral-500">系统备份与恢复仅允许 admin 账号访问。</p>
      <div class="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
        <NuxtLink to="/admin/login" class="inline-flex items-center justify-center px-4 py-2 bg-neutral-900 text-white text-sm rounded">
          切换 admin 账号
        </NuxtLink>
        <NuxtLink to="/" class="inline-flex items-center justify-center px-4 py-2 border border-neutral-300 text-neutral-700 text-sm rounded">
          返回用户端
        </NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  layout: false,
})
</script>
