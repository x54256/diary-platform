<template>
  <!-- 顶部导航栏：高度 44px -->
  <header class="sticky top-0 z-40 h-nav bg-white border-b border-neutral-200">
    <div class="flex items-center h-full px-2 max-w-md mx-auto">
      <!-- 左侧：返回按钮 -->
      <div class="flex w-10 shrink-0 items-center">
        <button
          v-if="showBack"
          @click="goBack"
          class="flex h-11 w-10 items-center justify-start pl-1 text-lg text-neutral-600"
          aria-label="返回"
        >
          ←
        </button>
      </div>

      <!-- 中间：标题 -->
      <div class="min-w-0 flex-1 px-2 text-center">
        <slot name="title">
          <h1 class="truncate whitespace-nowrap text-lg font-medium text-neutral-800">{{ title }}</h1>
        </slot>
      </div>

      <!-- 右侧：操作区（通过 slot 插入） -->
      <div class="flex shrink-0 items-center gap-2">
        <slot name="right" />
      </div>
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
