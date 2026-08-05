<template>
  <nav class="no-scrollbar flex gap-2 overflow-x-auto bg-white px-4 py-2" aria-label="回顾领域">
    <button
      v-for="code in domains"
      :key="code"
      type="button"
      class="shrink-0 rounded-full px-3 py-1 text-xs"
      :class="active === code ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-500'"
      :aria-current="active === code ? 'location' : undefined"
      @click="$emit('select', code)"
    >
      {{ reviewDomainLabel(code) }}
    </button>
  </nav>
</template>

<script setup lang="ts">
import type { ReviewDomainCode } from '~/types'
import { reviewDomainLabel } from '~/utils/reviewLabels'

defineProps<{ domains: ReviewDomainCode[]; active?: ReviewDomainCode }>()
defineEmits<{ (event: 'select', code: ReviewDomainCode): void }>()
</script>
