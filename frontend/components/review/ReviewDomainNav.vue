<template>
  <nav class="no-scrollbar flex gap-2 overflow-x-auto bg-white px-4 py-2" aria-label="生活领域">
    <button
      v-for="code in domains"
      :key="code"
      type="button"
      class="min-h-11 shrink-0 rounded-full px-3 text-sm font-medium"
      :class="active === code ? 'bg-primary-100 text-primary-800' : 'text-neutral-500'"
      :aria-current="active === code ? 'location' : undefined"
      @click="$emit('select', code)"
    >
      {{ meta[code].icon }} {{ meta[code].short }}
    </button>
  </nav>
</template>

<script setup lang="ts">
import type { ReviewDomainCode } from '~/types'

defineProps<{ domains: ReviewDomainCode[]; active?: ReviewDomainCode }>()
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
