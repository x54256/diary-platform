<template>
  <div v-if="compact" class="mb-2 text-sm text-neutral-500 leading-relaxed">
    <div class="mb-0.5">问：{{ qa.question }}</div>
    <div v-html="'答：' + qa.answer.replace(/\n/g, '<br>')" />
  </div>
  <div v-else class="bg-white rounded-lg border border-neutral-200 p-3 mb-2">
    <div class="text-sm font-medium text-neutral-800 mb-1">Q：{{ qa.question }}</div>
    <div class="text-sm text-neutral-600" v-html="'A：' + qa.answer.replace(/\n/g, '<br>')" />
  </div>
</template>

<script setup lang="ts">
import type { QuestionAnswer } from '~/types'

defineProps<{
  qa: QuestionAnswer
  compact?: boolean
}>()
</script>
