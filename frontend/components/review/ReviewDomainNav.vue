<template>
  <nav
    class="no-scrollbar gap-2 bg-[#fffdf8]"
    :class="orientation === 'vertical' ? 'flex flex-col px-0 py-0' : 'flex overflow-x-auto px-4 py-2'"
    aria-label="生活领域"
  >
    <button
      v-for="code in domains"
      :key="code"
      type="button"
      class="min-h-11 shrink-0 rounded-xl px-3 text-sm font-medium transition"
      :class="[orientation === 'vertical' ? 'flex w-full items-center text-left' : '', active === code ? 'bg-primary-100 text-primary-800' : 'text-neutral-500 hover:bg-neutral-100']"
      :aria-current="active === code ? 'location' : undefined"
      @click="$emit('select', code)"
    >
      {{ meta[code].icon }} {{ meta[code].short }}
    </button>
  </nav>
</template>

<script setup lang="ts">
import type { ReviewDomainCode } from '~/types'

withDefaults(defineProps<{ domains: ReviewDomainCode[]; active?: ReviewDomainCode; orientation?: 'horizontal' | 'vertical' }>(), { orientation: 'horizontal' })
defineEmits<{ (event: 'select', code: ReviewDomainCode): void }>()
const meta: Record<ReviewDomainCode, { icon: string; short: string }> = {
  WORK_CAREER: { icon: '💼', short: '工作事业' },
  HEALTH_WELLBEING: { icon: '🌿', short: '身心健康' },
  RELATIONSHIPS_SOCIAL: { icon: '🤝', short: '关系社交' },
  LEARNING_GROWTH: { icon: '📚', short: '学习成长' },
  LIFE_RESOURCES: { icon: '🏠', short: '生活管理' },
  LEISURE_EXPERIENCE: { icon: '🎈', short: '休闲体验' },
}
</script>
