<template>
  <div class="min-h-dvh">
    <NavBar title="定期回顾">
      <template #right>
        <NuxtLink to="/review/tasks" class="relative flex h-11 w-11 items-center justify-center text-neutral-600" aria-label="回顾任务">
          <svg viewBox="0 0 24 24" class="h-6 w-6 fill-none stroke-current stroke-2"><path d="M6 5h14M6 12h14M6 19h14"/><circle cx="3" cy="5" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="19" r="1"/></svg>
          <span v-if="attentionTaskCount" class="absolute right-0 top-0 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1 text-[11px] font-medium text-white">{{ attentionTaskCount > 99 ? '99+' : attentionTaskCount }}</span>
        </NuxtLink>
      </template>
    </NavBar>

    <main class="w-full px-4 py-4 sm:px-6 lg:px-8">
      <p class="text-sm leading-6 text-neutral-500">把已经发生的事，连成下一段更清楚的生活线索。</p>
      <ReviewPeriodFilter v-model="filter" class="mt-3" />
      <NuxtLink v-if="activeTaskCount || failedTaskCount" to="/review/tasks" class="mt-3 flex min-h-12 items-center justify-between rounded-lg border border-primary-200 bg-primary-50 px-4 text-sm text-primary-800">
        <span>{{ activeTaskCount ? `${activeTaskCount} 项任务进行中` : '' }}{{ activeTaskCount && failedTaskCount ? '，' : '' }}{{ failedTaskCount ? `${failedTaskCount} 项需要处理` : '' }}</span><span>›</span>
      </NuxtLink>

      <div v-if="loading" class="flex justify-center py-24"><span class="text-sm text-neutral-400">加载中...</span></div>
      <ReviewStatusBanner v-else-if="error" class="mt-4" :title="error" action-label="重新加载" tone="error" @action="load" />
      <div v-else-if="groupedReviews.length" class="mt-4 space-y-6">
        <section v-for="group in groupedReviews" :key="group.key">
          <h2 class="mb-3 text-sm font-medium text-neutral-500">{{ group.label }}</h2>
          <div class="space-y-3"><ReviewListCard v-for="review in group.items" :key="review.id" :review="review" /></div>
        </section>
        <button v-if="nextCursor" type="button" class="min-h-12 w-full rounded-lg border border-neutral-300 bg-white text-sm font-medium text-neutral-700 disabled:opacity-50" :disabled="loadingMore" @click="loadMore">{{ loadingMore ? '正在加载…' : '加载更多' }}</button>
      </div>
      <section v-else class="py-16 text-center">
        <p class="text-sm text-neutral-400">还没有可以查看的回顾</p>
        <p class="mx-auto mt-2 max-w-xs text-sm leading-6 text-neutral-500">周期结束后系统会自动生成；也可以从任务中心选择过去的周期生成。</p>
        <NuxtLink to="/review/tasks?create=1" class="mt-5 inline-flex items-center rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-medium text-white">新建回顾任务</NuxtLink>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { ReviewSummary, ReviewTask, ReviewType } from '~/types'

definePageMeta({ layout: 'default', middleware: 'auth' })
const { api } = useApi()
const reviews = ref<ReviewSummary[]>([])
const tasks = ref<ReviewTask[]>([])
const loading = ref(true)
const error = ref('')
const nextCursor = ref<string | null>(null)
const loadingMore = ref(false)
const filter = ref<'ALL' | ReviewType>('ALL')
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  const saved = localStorage.getItem('review-period-filter')
  if (saved === 'ALL' || saved === 'WEEK' || saved === 'MONTH') filter.value = saved
  void load()
  pollTimer = window.setInterval(() => { if (activeTaskCount.value) void loadTasks() }, 8000)
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
watch(filter, value => { if (import.meta.client) localStorage.setItem('review-period-filter', value) })

const unwrap = <T,>(response: T[] | { items: T[] }) => Array.isArray(response) ? response : response.items
const loadTasks = async () => { tasks.value = unwrap(await api<ReviewTask[] | { items: ReviewTask[] }>('/review-tasks?limit=100')) }
const load = async () => {
  loading.value = true; error.value = ''
  try {
    const [reviewResponse] = await Promise.all([api<ReviewSummary[] | { items: ReviewSummary[]; next_cursor?: string | null }>('/reviews'), loadTasks()])
    reviews.value = unwrap(reviewResponse)
    nextCursor.value = Array.isArray(reviewResponse) ? null : reviewResponse.next_cursor || null
  } catch (cause: any) { error.value = cause?.data?.detail || '回顾加载失败，请重试' } finally { loading.value = false }
}
const loadMore = async () => {
  if (!nextCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const response = await api<{ items: ReviewSummary[]; next_cursor?: string | null }>(`/reviews?cursor=${encodeURIComponent(nextCursor.value)}`)
    const known = new Set(reviews.value.map(item => item.id))
    reviews.value.push(...response.items.filter(item => !known.has(item.id)))
    nextCursor.value = response.next_cursor || null
  } catch (cause: any) { error.value = cause?.data?.detail || '更多回顾加载失败' } finally { loadingMore.value = false }
}
const activeStatuses = ['PENDING', 'QUEUED', 'RUNNING']
const activeTaskCount = computed(() => tasks.value.filter(task => activeStatuses.includes(task.status)).length)
const failedTaskCount = computed(() => tasks.value.filter(task => task.status === 'FAILED').length)
const attentionTaskCount = computed(() => activeTaskCount.value + failedTaskCount.value)
const visibleReviews = computed(() => reviews.value
  .filter(review => filter.value === 'ALL' || review.review_type === filter.value)
  .sort((a, b) => b.period_end.localeCompare(a.period_end) || (a.review_type === 'MONTH' ? -1 : 1)))
const groupedReviews = computed(() => {
  const groups = new Map<string, ReviewSummary[]>()
  for (const review of visibleReviews.value) {
    const key = review.period_end.slice(0, 7)
    groups.set(key, [...(groups.get(key) || []), review])
  }
  return [...groups.entries()].map(([key, items]) => ({ key, label: `${key.slice(0, 4)} 年 ${Number(key.slice(5, 7))} 月`, items }))
})
</script>
