<template>
  <!-- 顶部导航栏：高度 44px -->
  <header class="sticky top-0 z-40 h-nav bg-white border-b border-neutral-200">
    <div class="flex items-center justify-between h-full px-4 max-w-md mx-auto">
      <!-- 左侧：返回按钮 -->
      <div class="flex items-center w-8">
        <button
          v-if="showBack"
          @click="goBack"
          class="text-neutral-600 text-lg"
          aria-label="返回"
        >
          ←
        </button>
      </div>

      <!-- 中间：标题 -->
      <h1 class="text-base font-medium text-neutral-800">{{ title }}</h1>

      <!-- 右侧：占位 -->
      <div class="w-8"></div>
    </div>
  </header>
</template>

<script setup lang="ts">
// 顶部导航栏组件

const props = withDefaults(defineProps<{
  title?: string
  showBack?: boolean
}>(), {
  title: '',
  showBack: false,
})

// 返回上一页
const router = useRouter()
const goBack = () => {
  router.back()
}
</script>
