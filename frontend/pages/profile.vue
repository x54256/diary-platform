<template>
  <div class="min-h-dvh">
    <!-- 用户信息卡片 -->
    <div class="bg-white px-4 py-6 mb-3">
      <div class="flex items-center gap-4">
        <!-- 头像占位 -->
        <div class="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center text-2xl">
          👤
        </div>
        <div>
          <div class="text-lg font-medium text-neutral-800">{{ user?.username || '未登录' }}</div>
          <div class="text-xs text-neutral-400 mt-1">ID: {{ user?.id || '-' }}</div>
        </div>
      </div>
    </div>

    <!-- 模块入口列表 -->
    <div class="bg-white">
      <NuxtLink
        v-for="item in menuItems"
        :key="item.path"
        :to="item.path"
        class="flex items-center justify-between px-4 py-3.5 border-b border-neutral-100 active:bg-neutral-50"
      >
        <div class="flex items-center gap-3">
          <span class="text-xl">{{ item.icon }}</span>
          <span class="text-sm text-neutral-800">{{ item.label }}</span>
        </div>
        <span class="text-neutral-300 text-sm">›</span>
      </NuxtLink>
    </div>

    <!-- 设置入口 -->
    <div class="bg-white mt-3">
      <div class="flex items-center justify-between px-4 py-3.5 border-b border-neutral-100">
        <div class="flex items-center gap-3">
          <span class="text-xl">⚙️</span>
          <span class="text-sm text-neutral-800">设置</span>
        </div>
        <span class="text-neutral-300 text-sm">›</span>
      </div>
      <button
        @click="handleLogout"
        class="w-full flex items-center gap-3 px-4 py-3.5 text-sm text-red-500"
      >
        <span class="text-xl">🚪</span>
        <span>退出登录</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// 我的页面：使用 default 布局（带 Tab 栏）
definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const { user, logout } = useAuth()
const router = useRouter()

// 模块入口列表
const menuItems = [
  { icon: '🎯', label: '人物画像', path: '/profile/persona' },
  { icon: '📈', label: '心路历程', path: '/profile/journey' },
  { icon: '💡', label: '认知洞察', path: '/profile/insights' },
]

// 退出登录
const handleLogout = () => {
  logout()
  router.push('/login')
}
</script>
