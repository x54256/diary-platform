<template>
  <div class="min-h-dvh bg-neutral-50">
    <NavBar title="知识库" />
    <div class="flex border-b border-neutral-200 bg-white">
      <NuxtLink
        :to="{ path: '/knowledge', query: { tab: 'events' } }"
        class="flex min-h-11 flex-1 items-center justify-center text-sm font-medium"
        :class="tab === 'events' ? 'border-b-2 border-primary-600 text-primary-600' : 'text-neutral-500'"
      >事件</NuxtLink>
      <NuxtLink
        :to="{ path: '/knowledge', query: { tab: 'matters' } }"
        class="flex min-h-11 flex-1 items-center justify-center text-sm font-medium"
        :class="tab === 'matters' ? 'border-b-2 border-primary-600 text-primary-600' : 'text-neutral-500'"
      >事项</NuxtLink>
    </div>

    <main v-if="tab === 'events'" class="w-full px-4 py-4">
      <div v-if="error" class="mb-4 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        <span>{{ error }}</span>
        <button type="button" class="min-h-11 shrink-0 px-2 font-medium" @click="reload">重新加载</button>
      </div>
      <div v-if="upgradeError" class="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        {{ upgradeError }}
      </div>

      <div v-if="loading && events.length === 0" class="py-16 text-center text-sm text-neutral-400">加载中...</div>
      <div v-else-if="events.length === 0 && !error" class="py-20 text-center">
        <div class="text-4xl">📚</div>
        <h2 class="mt-4 text-base font-medium text-neutral-700">还没有事件知识</h2>
        <p class="mt-2 text-sm text-neutral-400">从已分析日记开始沉淀</p>
      </div>
      <div v-else class="space-y-6">
        <section v-for="diaryGroup in groupedEvents" :key="diaryGroup.diaryId" class="space-y-4">
          <div class="flex min-h-11 items-center justify-between gap-3 border-b border-neutral-200 pb-2">
            <h2 class="min-w-0 text-sm font-semibold text-neutral-700">
              {{ formatDateInAppTimeZone(diaryGroup.diaryDate) }} ·《{{ diaryGroup.diaryTitle || '未命名日记' }}》
            </h2>
            <button
              v-if="upgradePendingDiaryIds.has(diaryGroup.diaryId)"
              type="button"
              class="min-h-11 shrink-0 rounded-lg px-3 text-sm font-medium text-primary-600 disabled:text-neutral-400"
              :disabled="Boolean(activeKnowledgeTask) || upgradeStartingDiaryId === diaryGroup.diaryId"
              @click="startMatterUpgrade(diaryGroup.diaryId)"
            >{{ upgradeButtonLabel(diaryGroup.diaryId) }}</button>
          </div>
          <section v-for="eventGroup in diaryGroup.eventGroups" :key="eventGroup.sourceEventId" class="space-y-3">
            <NuxtLink
              v-for="event in eventGroup.items"
              :key="event.id"
              :to="`/knowledge/events/${event.id}`"
              class="block rounded-xl border border-neutral-100 bg-white p-4 shadow-sm active:bg-neutral-50"
            >
              <div class="flex items-start justify-between gap-3">
                <h3 class="min-w-0 truncate text-sm font-medium text-neutral-500">{{ eventGroup.sourceEventTitle || '未命名事件' }}</h3>
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

    <main v-else class="w-full px-4 py-4">
      <div v-if="matterError" class="mb-4 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        <span>{{ matterError }}</span>
        <button type="button" class="min-h-11 shrink-0 px-2 font-medium" @click="reloadMatters">重新加载</button>
      </div>

      <div v-if="matterLoading && matters.length === 0" class="py-16 text-center text-sm text-neutral-400">加载中...</div>
      <div v-else-if="matters.length === 0 && !matterError" class="py-20 text-center">
        <div class="text-4xl">🧵</div>
        <h2 class="mt-4 text-base font-medium text-neutral-700">还没有事项</h2>
        <p class="mt-2 text-sm text-neutral-400">沉淀新日记后自动生成事项</p>
      </div>
      <div v-else class="space-y-3">
        <NuxtLink
          v-for="matter in matters"
          :key="matter.id"
          :to="`/knowledge/matters/${matter.id}`"
          class="block rounded-xl border border-neutral-100 bg-white p-4 shadow-sm active:bg-neutral-50"
        >
          <div class="flex items-center justify-between gap-3">
            <h3 class="min-w-0 truncate text-base font-medium text-neutral-800">{{ matter.name }}</h3>
            <span
              class="shrink-0 rounded-full px-2 py-0.5 text-xs"
              :class="matterStatusClass(matter.status)"
            >{{ matterStatusLabel(matter.status) }}</span>
          </div>
          <p class="mt-2 line-clamp-2 whitespace-pre-wrap text-sm leading-6 text-neutral-600">{{ matter.overview }}</p>
          <div class="mt-2 text-xs text-neutral-400">{{ matter.event_count }} 个事件 · 最近 {{ formatDateInAppTimeZone(matter.last_event_on) }}</div>
        </NuxtLink>
        <div ref="matterSentinel" class="h-10 text-center text-xs text-neutral-400">
          {{ matterLoading ? '加载中...' : matterNextCursor ? '继续下滑加载更多' : '已显示全部事项' }}
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import type {
  KnowledgeEvent, KnowledgeEventListResponse,
  KnowledgeMatterListItem, KnowledgeMatterListResponse, KnowledgeMatterStatus,
  KnowledgeTask, KnowledgeUpgradeStatusResponse,
} from '~/types/knowledge'
import { formatDateInAppTimeZone } from '~/utils/datetime'
import { formatKnowledgeDateTime, knowledgePlainText } from '~/utils/knowledgeText'

definePageMeta({ middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const tab = computed(() => (route.query.tab === 'matters' ? 'matters' : 'events'))

// ---------- 事件页签 ----------
const events = ref<KnowledgeEvent[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null
const upgradePendingDiaryIds = ref(new Set<string>())
const activeKnowledgeTask = ref<KnowledgeTask | null>(null)
const upgradeStartingDiaryId = ref('')
const upgradeError = ref('')
let upgradePoller: ReturnType<typeof setInterval> | null = null
let upgradePolling = false

const loadUpgradeStatus = async () => {
  const response = await api<KnowledgeUpgradeStatusResponse>('/knowledge/matters/upgrade-status')
  upgradePendingDiaryIds.value = new Set(response.pending_diaries.map(item => item.diary_id))
  activeKnowledgeTask.value = response.active_task || null
}

const refreshUpgradeStatus = async () => {
  try {
    await loadUpgradeStatus()
  } catch (exception: any) {
    upgradeError.value = exception?.data?.detail?.message || exception?.data?.detail || '事项整理状态加载失败'
  }
}

const upgradeButtonLabel = (diaryId: string) => {
  if (upgradeStartingDiaryId.value === diaryId) return '正在创建…'
  const task = activeKnowledgeTask.value
  if (task?.task_type === 'UPGRADE' && task.diary_id === diaryId) {
    return task.status === 'QUEUED' ? '等待整理…' : '整理中…'
  }
  return task ? '其他任务处理中' : '整理事项'
}

const startMatterUpgrade = async (diaryId: string) => {
  if (activeKnowledgeTask.value || upgradeStartingDiaryId.value) return
  upgradeStartingDiaryId.value = diaryId
  upgradeError.value = ''
  try {
    activeKnowledgeTask.value = await api<KnowledgeTask>('/knowledge/matters/upgrade', {
      method: 'POST', body: { diary_id: diaryId },
    })
  } catch (exception: any) {
    upgradeError.value = exception?.data?.detail?.message || exception?.data?.detail || '事项整理任务创建失败'
    await loadUpgradeStatus().catch(() => undefined)
  } finally {
    upgradeStartingDiaryId.value = ''
  }
}

const pollMatterUpgrade = async () => {
  const task = activeKnowledgeTask.value
  if (!task || upgradePolling || !['QUEUED', 'RUNNING'].includes(task.status)) return
  upgradePolling = true
  try {
    const latest = await api<KnowledgeTask>(`/knowledge-tasks/${task.id}`)
    activeKnowledgeTask.value = latest
    if (latest.status === 'SUCCEEDED') {
      await loadUpgradeStatus()
      if (mattersLoaded) await loadMatters(true)
    } else if (latest.status === 'FAILED') {
      if (latest.task_type === 'UPGRADE') {
        upgradeError.value = latest.error_message || '事项整理失败，请重试'
      }
      await loadUpgradeStatus()
    }
  } catch (exception: any) {
    upgradeError.value = exception?.data?.detail?.message || exception?.data?.detail || '事项整理状态获取失败'
  } finally {
    upgradePolling = false
  }
}

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

// ---------- 事项页签 ----------
const matters = ref<KnowledgeMatterListItem[]>([])
const matterNextCursor = ref<string | null>(null)
const matterLoading = ref(false)
const matterError = ref('')
const matterSentinel = ref<HTMLElement | null>(null)
let matterObserver: IntersectionObserver | null = null
let mattersLoaded = false

const matterStatusLabel = (status: KnowledgeMatterStatus) => (
  status === 'ONGOING' ? '进行中' : status === 'ENDED' ? '已结束' : '搁置'
)
const matterStatusClass = (status: KnowledgeMatterStatus) => (
  status === 'ONGOING'
    ? 'bg-primary-50 text-primary-600'
    : status === 'ENDED'
      ? 'bg-neutral-100 text-neutral-500'
      : 'bg-amber-50 text-amber-600'
)

const loadMatters = async (reset = false) => {
  if (matterLoading.value || (!reset && matters.value.length > 0 && !matterNextCursor.value)) return
  matterLoading.value = true
  matterError.value = ''
  try {
    const query = new URLSearchParams({ limit: '20' })
    if (!reset && matterNextCursor.value) query.set('cursor', matterNextCursor.value)
    const response = await api<KnowledgeMatterListResponse>(`/knowledge/matters?${query}`)
    matters.value = reset ? response.items : [...matters.value, ...response.items]
    matterNextCursor.value = response.next_cursor || null
    mattersLoaded = true
  } catch (exception: any) {
    matterError.value = exception?.data?.detail?.message || exception?.data?.detail || '事项加载失败'
  } finally {
    matterLoading.value = false
  }
}

const reloadMatters = () => loadMatters(true)
watch(matterSentinel, (element, previous) => {
  if (previous && matterObserver) matterObserver.unobserve(previous)
  if (element && matterObserver) matterObserver.observe(element)
})

watch(tab, async (value) => {
  if (value === 'matters' && !mattersLoaded) {
    await loadMatters(true)
    await nextTick()
    if (matterObserver && matterSentinel.value) matterObserver.observe(matterSentinel.value)
  } else if (value === 'events') {
    await refreshUpgradeStatus()
  }
})

onMounted(async () => {
  observer = new IntersectionObserver(entries => {
    if (entries[0]?.isIntersecting && nextCursor.value) load()
  }, { rootMargin: '160px' })
  matterObserver = new IntersectionObserver(entries => {
    if (entries[0]?.isIntersecting && matterNextCursor.value) loadMatters()
  }, { rootMargin: '160px' })
  await refreshUpgradeStatus()
  if (tab.value === 'matters') {
    await loadMatters(true)
    await nextTick()
    if (matterSentinel.value) matterObserver.observe(matterSentinel.value)
  } else {
    await load(true)
    await nextTick()
    if (sentinel.value) observer.observe(sentinel.value)
  }
  upgradePoller = window.setInterval(() => { void pollMatterUpgrade() }, 2000)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  matterObserver?.disconnect()
  if (upgradePoller) clearInterval(upgradePoller)
})
</script>
