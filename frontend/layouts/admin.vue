<template>
  <div class="min-h-dvh bg-neutral-100">
    <header class="h-14 bg-white border-b border-neutral-200">
      <div class="h-full px-6 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded bg-neutral-900 text-white flex items-center justify-center text-sm font-medium">
            管
          </div>
          <div>
            <div class="text-sm font-medium text-neutral-900">管理端 · 日记平台</div>
            <div class="text-xs text-neutral-500">系统管理</div>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <span class="text-sm text-neutral-600">{{ user?.username }}</span>
          <button class="text-sm text-neutral-500 hover:text-neutral-900" @click="handleLogout">
            退出
          </button>
        </div>
      </div>
    </header>

    <div class="flex min-h-[calc(100dvh-56px)]">
      <aside class="w-56 bg-white border-r border-neutral-200 px-3 py-4">
        <div class="px-3 pb-2 text-xs font-medium text-neutral-400">系统管理</div>
        <NuxtLink
          to="/admin/backup-restore"
          class="flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/backup-restore') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
        >
          备份与恢复
        </NuxtLink>
      </aside>

      <main class="flex-1 p-6">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
const { user, logout } = useAuth()
const router = useRouter()

const handleLogout = () => {
  logout()
  router.push('/admin/login')
}
</script>
