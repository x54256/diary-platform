<template>
  <!-- 底部 Tab 栏：固定底部，高度 52px -->
  <nav class="fixed bottom-0 left-0 right-0 z-50 h-tab bg-white border-t border-neutral-200 safe-area-bottom">
    <div class="flex items-center justify-around h-full max-w-md mx-auto">
      <NuxtLink
        v-for="tab in tabs"
        :key="tab.path"
        :to="tab.path"
        class="flex flex-col items-center justify-center flex-1 h-full gap-0.5"
        :class="active === tab.key ? 'text-primary-600' : 'text-neutral-400'"
      >
        <span class="relative text-xl leading-none">
          {{ tab.icon }}
        </span>
        <span class="text-xs leading-none">{{ tab.label }}</span>
      </NuxtLink>
    </div>
  </nav>
</template>

<script setup lang="ts">
// 底部 Tab 栏组件
// 六个 Tab：日记、日程、回顾、AI伙伴、知识、我的

interface TabItem {
  key: string
  label: string
  icon: string
  path: string
}

// 当前激活的 Tab，通过 props 传入
const props = defineProps<{
  active?: string
}>()
// Tab 配置
const tabs: TabItem[] = [
  { key: 'diary', label: '日记', icon: '📓', path: '/' },
  { key: 'schedule', label: '日程', icon: '🗓️', path: '/schedule' },
  { key: 'review', label: '回顾', icon: '🔄', path: '/review' },
  { key: 'ai', label: 'AI伙伴', icon: '💬', path: '/ai' },
  { key: 'profile', label: '我的', icon: '👤', path: '/profile' },
]
</script>
