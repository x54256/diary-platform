<template>
  <NuxtLink
    :to="`/review/${review.id}`"
    class="block rounded-lg border border-neutral-200 bg-white p-4 active:bg-neutral-50"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <span class="rounded bg-primary-50 px-2 py-0.5 text-xs text-primary-700">
          {{ review.review_type === 'WEEK' ? '周回顾' : '月回顾' }}
        </span>
        <span v-if="review.is_unread" class="flex items-center gap-1 text-xs text-primary-600"><i class="h-1.5 w-1.5 rounded-full bg-primary-500" />新</span>
      </div>
      <span class="text-neutral-300">›</span>
    </div>
    <h2 class="mt-3 text-base font-medium text-neutral-800">{{ periodLabel }}</h2>
    <p class="mt-2 line-clamp-3 text-sm leading-6 text-neutral-600">
      {{ review.summary || '这份回顾已生成，点击查看本期的主要事件、分析和下一步。' }}
    </p>
    <div class="mt-4 flex items-center justify-between border-t border-neutral-100 pt-3 text-xs text-neutral-400">
      <span>v{{ review.current_version_no || 1 }} · {{ review.version_count || 1 }} 个版本 · {{ dateLabel(review.updated_at) }}</span>
      <span>查看回顾</span>
    </div>
  </NuxtLink>
</template>

<script setup lang="ts">
import type { ReviewSummary } from '~/types'
import { formatDateTimeInAppTimeZone, formatDateInAppTimeZone } from '~/utils/datetime'

const props = defineProps<{ review: ReviewSummary }>()

const formatDate = (value: string) => {
  return formatDateInAppTimeZone(value)
}
const periodLabel = computed(() => props.review.review_type === 'WEEK'
  ? `${formatDate(props.review.period_start)}－${formatDate(props.review.period_end)}`
  : `${props.review.period_start.slice(0, 4)} 年 ${Number(props.review.period_start.slice(5, 7))} 月`)
const dateLabel = (value: string | null) => value ? `${formatDateTimeInAppTimeZone(value)} 生成` : '已生成'
</script>
