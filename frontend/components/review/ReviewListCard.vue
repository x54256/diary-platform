<template>
  <NuxtLink
    :to="`/review/${review.id}`"
    class="group relative block min-h-52 overflow-hidden rounded-3xl border border-[#e8e1d5] bg-white p-5 transition hover:-translate-y-0.5 hover:border-primary-300 hover:shadow-[0_14px_30px_-24px_rgba(100,69,37,0.55)] active:scale-[0.99]"
  >
    <span class="absolute inset-x-5 top-0 h-1 rounded-b-full bg-primary-400" />
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <span class="rounded-full bg-primary-50 px-2.5 py-1 text-xs font-semibold text-primary-700">
          {{ review.review_type === 'WEEK' ? '周回顾' : '月回顾' }}
        </span>
        <span v-if="review.is_unread" class="flex items-center gap-1 text-xs text-primary-600"><i class="h-1.5 w-1.5 rounded-full bg-primary-500" />新</span>
      </div>
      <span class="text-xl text-neutral-300 transition group-hover:translate-x-0.5 group-hover:text-primary-600">›</span>
    </div>
    <h2 class="mt-5 text-lg font-semibold tracking-tight text-[#26322b]">{{ periodLabel }}</h2>
    <p class="mt-2 line-clamp-3 text-sm leading-6 text-neutral-600">
      {{ review.summary || '这份回顾已生成，点击查看本期的主要事件、分析和下一步。' }}
    </p>
    <div class="mt-5 flex items-center justify-between border-t border-[#f0ebe4] pt-3 text-xs text-neutral-400">
      <span>v{{ review.current_version_no || 1 }} · {{ review.version_count || 1 }} 个版本 · {{ dateLabel(review.updated_at) }}</span>
      <span>查看回顾</span>
    </div>
  </NuxtLink>
</template>

<script setup lang="ts">
import type { ReviewSummary } from '~/types'

const props = defineProps<{ review: ReviewSummary }>()

const formatDate = (value: string) => {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}
const periodLabel = computed(() => props.review.review_type === 'WEEK'
  ? `${formatDate(props.review.period_start)}－${formatDate(props.review.period_end)}`
  : `${props.review.period_start.slice(0, 4)} 年 ${Number(props.review.period_start.slice(5, 7))} 月`)
const dateLabel = (value: string | null) => value ? `${new Date(value).toLocaleDateString('zh-CN')} 生成` : '已生成'
</script>
