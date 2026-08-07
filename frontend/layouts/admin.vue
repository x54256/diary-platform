<template>
  <div class="min-h-dvh overflow-x-hidden bg-neutral-100">
    <header class="h-14 bg-white border-b border-neutral-200">
      <div class="h-full px-4 md:px-6 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <button
            type="button"
            class="-ml-2 flex h-10 w-10 items-center justify-center rounded text-neutral-600 hover:bg-neutral-100 md:hidden"
            aria-label="打开管理菜单"
            :aria-expanded="mobileMenuOpen"
            @click="mobileMenuOpen = true"
          >
            <span class="text-xl leading-none">☰</span>
          </button>
          <div class="w-8 h-8 rounded bg-neutral-900 text-white flex items-center justify-center text-sm font-medium">
            管
          </div>
          <div>
            <div class="text-sm font-medium text-neutral-900">管理端 · 日记平台</div>
            <div class="hidden text-xs text-neutral-500 sm:block">系统管理</div>
          </div>
        </div>
        <div class="flex items-center gap-2 md:gap-4">
          <span class="hidden text-sm text-neutral-600 sm:block">{{ user?.username }}</span>
          <button class="text-sm text-neutral-500 hover:text-neutral-900" @click="handleLogout">
            退出
          </button>
        </div>
      </div>
    </header>

    <div class="flex min-h-[calc(100dvh-56px)]">
      <div
        v-if="mobileMenuOpen"
        class="fixed inset-0 z-30 bg-neutral-900/30 md:hidden"
        aria-hidden="true"
        @click="mobileMenuOpen = false"
      />

      <aside
        class="fixed inset-y-0 left-0 z-40 w-[min(18rem,84vw)] -translate-x-full bg-white px-3 py-4 shadow-xl transition-transform duration-200 md:static md:z-auto md:w-56 md:translate-x-0 md:shadow-none"
        :class="mobileMenuOpen ? 'translate-x-0' : ''"
      >
        <div class="mb-5 flex items-center justify-between px-3 md:hidden">
          <span class="text-sm font-medium text-neutral-900">系统管理</span>
          <button type="button" class="flex h-9 w-9 items-center justify-center rounded text-xl text-neutral-500 hover:bg-neutral-100" aria-label="关闭管理菜单" @click="mobileMenuOpen = false">×</button>
        </div>
        <div class="px-3 pb-2 text-xs font-medium text-neutral-400">系统管理</div>
        <NuxtLink
          to="/admin/backup-restore"
          class="flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/backup-restore') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
          @click="mobileMenuOpen = false"
        >
          备份与恢复
        </NuxtLink>
        <NuxtLink
          to="/admin/search-index"
          class="mt-1 flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/search-index') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
          @click="mobileMenuOpen = false"
        >
          搜索索引
        </NuxtLink>
        <NuxtLink
          to="/admin/models"
          class="mt-1 flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/models') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
          @click="mobileMenuOpen = false"
        >
          模型管理
        </NuxtLink>
        <NuxtLink
          to="/admin/channels"
          class="mt-1 flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/channels') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
          @click="mobileMenuOpen = false"
        >
          渠道管理
        </NuxtLink>
        <NuxtLink
          to="/admin/model-settings"
          class="mt-1 flex items-center px-3 py-2 rounded text-sm"
          :class="$route.path.startsWith('/admin/model-settings') ? 'bg-neutral-900 text-white' : 'text-neutral-700 hover:bg-neutral-100'"
          @click="mobileMenuOpen = false"
        >
          模型设置
        </NuxtLink>
      </aside>

      <main class="min-w-0 flex-1 p-4 md:p-6">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
const { user, logout } = useAuth()
const router = useRouter()
const route = useRoute()
const mobileMenuOpen = ref(false)

watch(() => route.path, () => {
  mobileMenuOpen.value = false
})

const handleLogout = () => {
  logout()
  router.push('/admin/login')
}
</script>
