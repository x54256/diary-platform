<template>
  <div class="flex gap-1 rounded-xl bg-neutral-100 p-1" aria-label="回顾周期筛选">
    <button
      v-for="item in items"
      :key="item.value"
      type="button"
      class="min-h-11 flex-1 rounded-lg px-4 text-sm font-medium transition"
      :class="modelValue === item.value ? 'bg-white text-primary-700 shadow-sm' : 'text-neutral-500'"
      :aria-current="modelValue === item.value ? 'true' : undefined"
      @click="$emit('update:modelValue', item.value)"
    >
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { ReviewType } from '~/types'

defineProps<{ modelValue: 'ALL' | ReviewType }>()
defineEmits<{ (event: 'update:modelValue', value: 'ALL' | ReviewType): void }>()

const items: Array<{ label: string; value: 'ALL' | ReviewType }> = [
  { label: '全部', value: 'ALL' },
  { label: '周', value: 'WEEK' },
  { label: '月', value: 'MONTH' },
]
</script>
