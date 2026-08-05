<template>
  <form class="rounded-lg border border-neutral-200 bg-white p-4 space-y-6" @submit.prevent="submit">
    <fieldset>
      <legend class="mb-2 text-sm font-medium text-neutral-700">回顾类型</legend>
      <div class="grid grid-cols-2 gap-2 rounded-lg bg-neutral-100 p-1">
        <button v-for="item in typeOptions" :key="item.value" type="button" class="min-h-11 rounded-lg text-sm font-medium" :class="type === item.value ? 'bg-white text-primary-700 shadow-sm' : 'text-neutral-500'" @click="selectType(item.value)">
          {{ item.label }}<span v-if="type === item.value"> ●</span>
        </button>
      </div>
    </fieldset>

    <fieldset>
      <legend class="mb-2 text-sm font-medium text-neutral-700">选择周期</legend>
      <div class="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <label v-for="option in options" :key="option.start" class="flex min-h-14 items-center gap-3 border-b border-neutral-100 px-4 last:border-b-0" :class="option.disabled ? 'text-neutral-400' : 'text-neutral-800'">
          <input v-model="periodStart" type="radio" name="review-period" :value="option.start" :disabled="option.disabled" class="h-5 w-5 accent-primary-600" />
          <span class="flex-1 text-sm">{{ option.label }}</span>
          <span v-if="option.reason" class="text-xs">{{ option.reason }}</span>
        </label>
      </div>
    </fieldset>

    <p class="rounded-lg bg-primary-50 px-4 py-3 text-sm leading-6 text-primary-800">
      将使用目前保存的事件、分析、日程和上一同级回顾，生成一个固定版本。
    </p>
    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <button type="submit" class="min-h-12 w-full rounded-lg bg-primary-600 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="submitting || !periodStart || selectedOption?.disabled">
      {{ submitting ? '正在创建…' : selectedOption?.reason === '已有回顾' ? '查看回顾' : '开始生成' }}
    </button>
  </form>
</template>

<script setup lang="ts">
import type { ReviewSummary, ReviewTask, ReviewType } from '~/types'

const props = withDefaults(defineProps<{ reviews?: ReviewSummary[]; tasks?: ReviewTask[]; submitting?: boolean; error?: string }>(), { reviews: () => [], tasks: () => [], submitting: false, error: '' })
const emit = defineEmits<{ (event: 'submit', payload: { review_type: ReviewType; period_start: string }): void }>()
const type = ref<ReviewType>('WEEK')
const periodStart = ref('')
const typeOptions: Array<{ label: string; value: ReviewType }> = [{ label: '周回顾', value: 'WEEK' }, { label: '月回顾', value: 'MONTH' }]

const dateKey = (date: Date) => {
  const year = date.getFullYear()
  return `${year}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const weekStart = (date: Date) => {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const day = copy.getDay() || 7
  copy.setDate(copy.getDate() - day + 1)
  return copy
}
const addDays = (date: Date, days: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days)
const shortDate = (date: Date) => `${date.getMonth() + 1}月${date.getDate()}日`

const statusFor = (start: string) => {
  if (props.reviews.some(item => item.review_type === type.value && item.period_start === start)) return { disabled: true, reason: '已有回顾' }
  if (props.tasks.some(item => item.review_type === type.value && item.period_start === start && ['PENDING', 'QUEUED', 'RUNNING'].includes(item.status))) return { disabled: true, reason: '生成中' }
  return { disabled: false, reason: '' }
}
const options = computed(() => {
  if (type.value === 'WEEK') {
    const current = weekStart(new Date())
    return Array.from({ length: 16 }, (_, index) => {
      const start = addDays(current, -7 * (index + 1))
      const end = addDays(start, 6)
      const state = statusFor(dateKey(start))
      return { start: dateKey(start), label: `${shortDate(start)}－${shortDate(end)}`, ...state }
    })
  }
  const now = new Date()
  return Array.from({ length: 12 }, (_, index) => {
    const start = new Date(now.getFullYear(), now.getMonth() - index - 1, 1)
    const state = statusFor(dateKey(start))
    return { start: dateKey(start), label: `${start.getFullYear()} 年 ${start.getMonth() + 1} 月`, ...state }
  })
})
const selectedOption = computed(() => options.value.find(option => option.start === periodStart.value))
const selectType = (value: ReviewType) => { type.value = value; periodStart.value = '' }
const submit = () => {
  if (!periodStart.value || selectedOption.value?.disabled) return
  emit('submit', { review_type: type.value, period_start: periodStart.value })
}
</script>
