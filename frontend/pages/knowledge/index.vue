<template>
  <div class="min-h-dvh bg-neutral-50">
    <NavBar title="知识库" />
    <main class="w-full px-4 py-4">
      <div v-if="error" class="mb-4 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        <span>{{ error }}</span>
        <button type="button" class="min-h-11 shrink-0 px-2 font-medium" @click="reload">重新加载</button>
      </div>

      <div v-if="loading && events.length === 0" class="py-16 text-center text-sm text-neutral-400">加载中...</div>
      <div v-else-if="events.length === 0 && !error" class="py-20 text-center">
        <div class="text-4xl">📚</div>
        <h2 class="mt-4 text-base font-medium text-neutral-700">还没有原子事件</h2>
        <p class="mt-2 text-sm text-neutral-400">从已分析日记开始沉淀</p>
      </div>
      <div v-else class="space-y-6">
        <section v-for="diaryGroup in groupedEvents" :key="diaryGroup.diaryId" class="space-y-4">
          <h2 class="border-b border-neutral-200 pb-2 text-sm font-semibold text-neutral-700">
            {{ formatDateInAppTimeZone(diaryGroup.diaryDate) }} ·《{{ diaryGroup.diaryTitle || '未命名日记' }}》
          </h2>
          <section v-for="eventGroup in diaryGroup.eventGroups" :key="eventGroup.sourceEventId" class="space-y-3">
            <h3 class="text-sm font-medium text-neutral-500">{{ eventGroup.sourceEventTitle || '未命名事件' }}</h3>
            <NuxtLink
              v-for="event in eventGroup.items"
              :key="event.id"
              :to="`/knowledge/events/${event.id}`"
              class="block rounded-xl border border-neutral-100 bg-white p-4 shadow-sm active:bg-neutral-50"
            >
              <div class="flex items-start justify-between gap-4">
                <h4 class="min-w-0 text-sm font-medium text-neutral-800">{{ event.title }}</h4>
                <time class="shrink-0 text-xs text-neutral-400">{{ formatKnowledgeDateTime(event.occurred_on, event.occurred_time) }}</time>
              </div>
              <p class="mt-2 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-neutral-600">{{ knowledgePlainText(event.content) }}</p>
            </NuxtLink>
          </section>
        </section>
        <div ref="sentinel" class="h-10 text-center text-xs text-neutral-400">
          {{ loading ? '加载中...' : nextCursor ? '继续下滑加载更多' : '已显示全部事件' }}
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { KnowledgeEvent, KnowledgeEventListResponse } from '~/types/knowledge'
import { formatDateInAppTimeZone } from '~/utils/datetime'
import { formatKnowledgeDateTime, knowledgePlainText } from '~/utils/knowledgeText'

definePageMeta({ middleware: 'auth' })
const { api } = useApi()
const events = ref<KnowledgeEvent[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

const groupedEvents = computed(() => {
  const diaryGroups: Array<{
    diaryId: string
    diaryDate: string
    diaryTitle?: string | null
    eventGroups: Array<{ sourceEventId: string, sourceEventTitle?: string | null, items: KnowledgeEvent[] }>
  }> = []
  for (const event of events.value) {
    let diaryGroup = diaryGroups.find(group => group.diaryId === event.diary_id)
    if (!diaryGroup) {
      diaryGroup = { diaryId: event.diary_id, diaryDate: event.source_diary_date, diaryTitle: event.source_diary_title, eventGroups: [] }
      diaryGroups.push(diaryGroup)
    }
    let eventGroup = diaryGroup.eventGroups.find(group => group.sourceEventId === event.source_diary_event_id)
    if (!eventGroup) {
      eventGroup = { sourceEventId: event.source_diary_event_id, sourceEventTitle: event.source_event_title, items: [] }
      diaryGroup.eventGroups.push(eventGroup)
    }
    eventGroup.items.push(event)
  }
  return diaryGroups
})

const load = async (reset = false) => {
  if (loading.value || (!reset && events.value.length > 0 && !nextCursor.value)) return
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({ limit: '20' })
    if (!reset && nextCursor.value) query.set('cursor', nextCursor.value)
    const response = await api<KnowledgeEventListResponse>(`/knowledge/events?${query}`)
    events.value = reset ? response.items : [...events.value, ...response.items]
    nextCursor.value = response.next_cursor || null
  } catch (exception: any) {
    error.value = exception?.data?.detail?.message || exception?.data?.detail || '知识事件加载失败'
  } finally {
    loading.value = false
  }
}

const reload = () => load(true)
watch(sentinel, (element, previous) => {
  if (previous && observer) observer.unobserve(previous)
  if (element && observer) observer.observe(element)
})
onMounted(async () => {
  await load(true)
  await nextTick()
  observer = new IntersectionObserver(entries => {
    if (entries[0]?.isIntersecting && nextCursor.value) load()
  }, { rootMargin: '160px' })
  if (sentinel.value) observer.observe(sentinel.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>
