<template>
  <!-- 回顾模块顶部导航栏：与日记页 NavBar 同风格，高度 44px -->
  <header class="sticky top-0 z-40 h-nav bg-white border-b border-neutral-200">
    <div class="flex items-center h-full px-2 max-w-md mx-auto">
      <div class="flex w-10 shrink-0 items-center">
        <button
          v-if="showBack"
          type="button"
          class="flex h-11 w-10 items-center justify-start pl-1 text-lg text-neutral-600"
          aria-label="返回"
          @click="router.back()"
        >
          ←
        </button>
      </div>
      <div class="min-w-0 flex-1 px-2 text-center">
        <h1 class="truncate whitespace-nowrap text-lg font-medium text-neutral-800">{{ title }}</h1>
      </div>
      <div class="flex shrink-0 items-center gap-2"><slot name="right" /></div>
    </div>
  </header>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  showBack?: boolean
}>(), { showBack: false })

const router = useRouter()
</script>
