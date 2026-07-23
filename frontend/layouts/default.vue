<template>
  <!-- 默认布局：带底部 Tab 栏 -->
  <div class="min-h-dvh flex flex-col">
    <!-- 页面内容 -->
    <main class="flex-1 pb-tab">
      <slot />
    </main>

    <!-- 底部 Tab 栏 -->
    <BottomTabBar :active="tabActive" />
  </div>
</template>

<script setup lang="ts">
// 默认布局：包含页面内容 + 底部 Tab 栏

const route = useRoute()

// 根据当前路由计算 Tab 高亮状态
const tabActive = computed(() => {
  const path = route.path
  if (path === '/') return 'diary'
  if (path.startsWith('/schedule')) return 'schedule'
  if (path.startsWith('/review')) return 'review'
  if (path.startsWith('/ai')) return 'ai'
  if (path.startsWith('/profile')) return 'profile'
  return ''
})
</script>
