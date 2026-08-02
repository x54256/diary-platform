<template>
  <div class="rounded-xl border px-4 py-3" :class="toneClass">
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-sm font-semibold">{{ title }}</p>
        <p v-if="description" class="mt-1 text-sm leading-5 opacity-80">{{ description }}</p>
      </div>
      <button v-if="dismissible" type="button" class="min-h-11 min-w-11 -mr-3 -mt-2 text-lg opacity-60" aria-label="关闭提示" @click="$emit('dismiss')">×</button>
    </div>
    <button v-if="actionLabel" type="button" class="mt-2 min-h-11 text-sm font-semibold underline underline-offset-4" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  title: string
  description?: string
  actionLabel?: string
  tone?: 'info' | 'warning' | 'success' | 'error'
  dismissible?: boolean
}>(), { tone: 'info', description: '', actionLabel: '', dismissible: false })
defineEmits<{ (event: 'action'): void; (event: 'dismiss'): void }>()

const toneClass = computed(() => ({
  info: 'border-primary-200 bg-primary-50 text-primary-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  error: 'border-red-200 bg-red-50 text-red-700',
}[props.tone]))
</script>
