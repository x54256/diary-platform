<template>
  <div class="min-h-dvh pb-[calc(6rem+env(safe-area-inset-bottom))]">
    <NavBar show-back>
      <template #title>
        <h1 class="truncate whitespace-nowrap text-lg font-medium text-neutral-800">
          {{ reviewTypeLabel }}<span v-if="detail" class="ml-1.5 text-sm font-normal text-neutral-400">{{ periodLabel }}</span>
        </h1>
      </template>
      <template #right>
        <button type="button" class="px-2 text-sm text-primary-600 font-medium" @click="versionOpen = true">版本</button>
      </template>
    </NavBar>

    <div v-if="loading" class="flex justify-center py-24"><span class="text-sm text-neutral-400">加载中...</span></div>

    <main v-else-if="detail">
      <div class="px-4 pt-4">
        <div class="space-y-3">
          <ReviewStatusBanner v-if="isHistorical" title="你正在查看历史版本" action-label="返回当前版本" @action="returnCurrent" />
          <ReviewStatusBanner v-if="detail.version.superseded_at_creation" title="生成期间内容已更新" description="这个版本没有设为当前版本。" tone="warning" />
          <ReviewStatusBanner v-if="detail.version.analysis_stale" title="事件事实已由你修改" description="当前分析和候选行动可能不再适用。" action-label="更新分析和行动" tone="warning" @action="regenerateAnalysis" />
          <ReviewStatusBanner v-if="detail.source_updates_available" title="回顾来源已有新版本" description="当前版本不会自动改变；需要时可以根据最新来源重新生成。" action-label="重新生成" tone="warning" @action="regenerateFull" />
          <ReviewStatusBanner v-if="missingPeriodDescription" title="部分下级周期资料缺失" :description="missingPeriodDescription" tone="warning" />
          <ReviewStatusBanner v-if="generationMessage" :title="generationMessage" :description="generationVersionId ? '当前版本仍然保留，你可以选择切换到新版本。' : '生成期间仍可阅读当前版本。'" :action-label="generationVersionId ? '查看新版本' : '查看任务'" @action="handleGenerationAction" />
        </div>

        <section class="mt-3 rounded-lg border border-neutral-200 bg-white px-4 py-3">
          <h2 class="text-lg font-medium text-neutral-800">{{ periodLabel }}</h2>
          <p class="mt-1 text-xs text-neutral-400">v{{ detail.version.version_no }} · {{ formatDateTime(detail.version.created_at) }}</p>
          <p class="mt-3 border-b border-neutral-100 pb-3 text-sm italic leading-6 text-neutral-600">{{ detail.version.summary || '这份回顾已根据本期记录生成。' }}</p>
          <p class="mt-2 text-xs text-neutral-400">{{ domainCodes.length }} 个领域 · {{ threadCount }} 条主要发展线</p>
        </section>

        
      </div>

      <div v-if="domainCodes.length" class="sticky top-11 z-30 mt-4 border-y border-neutral-200 bg-white">
        <div>
          <ReviewDomainNav :domains="domainCodes" :active="activeDomain" @select="scrollToDomain" />
        </div>
      </div>

      <div class="px-4">
        <div class="space-y-3 py-4">
          <ReviewDomainSection
            v-for="code in domainCodes"
            :key="code"
            :review-id="reviewId"
            :version-id="detail.version.id"
            :domain-code="code"
            :event-domain="eventDomain(code)"
            :related-entries="relatedEntries(code)"
            @related-select="scrollToDomain"
          />
          <p v-if="!domainCodes.length" class="py-16 text-center text-sm text-neutral-400">这个版本没有可展示的回顾内容。</p>
        </div>
      </div>
    </main>
    <div v-else class="px-4 pt-4"><ReviewStatusBanner :title="error || '回顾不存在'" action-label="重新加载" tone="error" @action="load" /></div>

    <div v-if="detail" class="fixed inset-x-0 bottom-[calc(52px+env(safe-area-inset-bottom))] z-40 border-t border-neutral-200 bg-white">
      <div class="mx-auto flex w-full gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <NuxtLink :to="`/review/${reviewId}/chat?version=${detail.version.id}`" class="flex flex-1 items-center justify-center rounded-lg border border-neutral-300 py-2.5 text-sm font-medium text-neutral-700 active:bg-neutral-50">围绕这份回顾对话</NuxtLink>
        <button type="button" class="flex-1 rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white active:bg-primary-700" @click="menuOpen = true">回顾操作</button>
      </div>
    </div>

    <ReviewVersionSheet :open="versionOpen" :review-id="reviewId" :current-version-id="detail?.version.id || ''" @close="versionOpen = false" @select="selectVersion" />

    <Teleport to="body">
      <div v-if="menuOpen" class="fixed inset-0 z-[75] flex items-end justify-center bg-black/35" @click.self="menuOpen = false" @keydown.esc="menuOpen = false">
        <section ref="menuRef" tabindex="-1" class="w-full rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] focus:outline-none sm:mx-auto sm:max-w-lg">
          <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-neutral-300" />
          <h2 class="font-medium text-neutral-900">回顾操作</h2>
          <button type="button" class="mt-3 min-h-14 w-full border-b border-neutral-100 text-left text-sm font-medium text-neutral-800" @click="regenerateFull">根据最新来源重新生成整个回顾</button>
          <button v-if="detail?.version.analysis_stale" type="button" class="min-h-14 w-full border-b border-neutral-100 text-left text-sm font-medium text-neutral-800" @click="regenerateAnalysis">根据事件修改更新分析和行动</button>
          <button type="button" class="min-h-14 w-full text-left text-sm font-medium text-neutral-800" @click="menuOpen = false; versionOpen = true">查看所有版本</button>
          <button type="button" class="mt-2 min-h-12 w-full rounded-lg border border-neutral-300 text-sm text-neutral-700" @click="menuOpen = false">取消</button>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="confirmRegenerateOpen" class="fixed inset-0 z-[85] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="确认重新生成" @click.self="confirmRegenerateOpen = false" @keydown.esc="confirmRegenerateOpen = false">
        <section class="w-full rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:mx-auto sm:max-w-lg">
          <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-neutral-300" />
          <h2 class="font-medium text-neutral-900">重新生成整个{{ reviewTypeLabel }}？</h2>
          <p class="mt-3 text-sm leading-6 text-neutral-600">将读取最新日记、分析反馈、日程和上一同级回顾，重新组织事件并更新分析和行动。当前版本和对话都会保留。</p>
          <div class="mt-5 grid grid-cols-2 gap-3">
            <button type="button" autofocus class="min-h-12 rounded-lg border border-neutral-300 text-sm text-neutral-700" @click="confirmRegenerateOpen = false">取消</button>
            <button type="button" class="min-h-12 rounded-lg bg-primary-600 text-sm font-medium text-white" @click="startFullRegeneration">开始生成</button>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import type { ReviewDailyDigest, ReviewDailyMatter, ReviewDomainCode, ReviewEventDomain, ReviewTask, ReviewVersionDetail } from '~/types'
import { normalizeKeyQuotes } from '~/utils/review-daily-material'

definePageMeta({ layout: 'default', middleware: 'auth' })
const route = useRoute()
const router = useRouter()
const { api } = useApi()
const reviewId = route.params.id as string
const detail = ref<ReviewVersionDetail | null>(null)
const dailyDigests = ref<ReviewDailyDigest[]>([])
const loading = ref(true)
const error = ref('')
const menuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)
let menuRestoreFocus: HTMLElement | null = null
const versionOpen = ref(false)
const activeDomain = ref<ReviewDomainCode>()
const generationMessage = ref('')
const generationVersionId = ref('')
const watchedTaskId = ref('')
const confirmRegenerateOpen = ref(false)
let taskPollTimer: ReturnType<typeof setInterval> | null = null
let observer: IntersectionObserver | null = null

const load = async (versionId?: string) => {
  loading.value = true; error.value = ''
  try {
    const url = versionId ? `/reviews/${reviewId}/versions/${versionId}` : `/reviews/${reviewId}`
    detail.value = await api<ReviewVersionDetail>(url)
    dailyDigests.value = await api<ReviewDailyDigest[]>(`/review-versions/${detail.value.version.id}/daily-digests`).catch(() => [])
    if (!versionId) void api(`/reviews/${reviewId}/read`, { method: 'POST' }).catch(() => undefined)
    await nextTick(); observeDomains()
  } catch (cause: any) { detail.value = null; dailyDigests.value = []; error.value = cause?.data?.detail || '回顾加载失败' } finally { loading.value = false }
}
onMounted(() => { void load(typeof route.query.version === 'string' ? route.query.version : undefined) })
onBeforeUnmount(() => {
  observer?.disconnect()
  if (taskPollTimer) clearInterval(taskPollTimer)
})
watch(menuOpen, async (open) => {
  if (open) {
    menuRestoreFocus = document.activeElement as HTMLElement | null
    await nextTick()
    menuRef.value?.focus()
  } else {
    menuRestoreFocus?.focus()
    menuRestoreFocus = null
  }
})

const reviewTypeLabel = computed(() => detail.value?.review.review_type === 'MONTH' ? '月回顾' : '周回顾')
const shortDate = (value: string) => (value && value.length >= 10 ? `${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日` : '')
const periodLabel = computed(() => {
  if (!detail.value) return ''
  const review = detail.value.review
  return review.review_type === 'MONTH' ? `${review.period_start.slice(0, 4)} 年 ${Number(review.period_start.slice(5, 7))} 月` : `${shortDate(review.period_start)}－${shortDate(review.period_end)}`
})
const formatDateTime = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
const eventDomains = computed(() => detail.value?.version.event_document?.domains || [])
const domainCodes = computed(() => {
  const values = new Set<ReviewDomainCode>()
  eventDomains.value.forEach(domain => {
    values.add(domain.domain_code)
    domain.event_threads?.forEach(thread => thread.related_domains?.forEach(code => values.add(code)))
  })
  return [...values].filter(Boolean)
})
const threadCount = computed(() => eventDomains.value.reduce((sum, domain) => sum + (domain.event_threads?.length || 0), 0))
type DisplayDailyMatter = Omit<ReviewDailyMatter, 'key_quotes'> & { key_quotes: string[] }
const digestMatters = (digest: ReviewDailyDigest): DisplayDailyMatter[] => (
  digest.material_document?.matters || []
).map(item => ({ ...item, key_quotes: normalizeKeyQuotes(item.key_quotes) }))
const missingPeriodDescription = computed(() => {
  const periods = (detail.value?.version.missing_periods || []) as Array<{ period_start?: string; period_end?: string; status?: string }>
  if (!periods.length) return ''
  return periods.map(item => `${item.period_start || '?'}－${item.period_end || '?'}（${item.status === 'FAILED' ? '生成失败' : item.status === 'SKIPPED_NO_DATA' ? '无有效记录' : '缺失'}）`).join('；')
})
const eventDomain = (code: ReviewDomainCode) => eventDomains.value.find(domain => domain.domain_code === code) as ReviewEventDomain | undefined
const relatedEntries = (code: ReviewDomainCode) => {
  const entries: Array<{ key: string; label: string; primaryDomain: ReviewDomainCode }> = []
  for (const domain of eventDomains.value) for (const thread of domain.event_threads || []) {
    if (domain.domain_code !== code && thread.related_domains?.includes(code)) entries.push({ key: `event-${thread.thread_key}`, label: thread.title, primaryDomain: domain.domain_code })
  }
  return entries
}
const isHistorical = computed(() => !!detail.value && detail.value.review.current_version_id !== detail.value.version.id)
const scrollToDomain = (code: ReviewDomainCode) => document.getElementById(`review-domain-${code}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
const observeDomains = () => {
  observer?.disconnect()
  // NavBar 44px + 横向领域导航约 44px，锚点偏移按 88px 观察
  observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
    if (visible) activeDomain.value = visible.target.id.replace('review-domain-', '') as ReviewDomainCode
  }, { rootMargin: '-88px 0px -65% 0px' })
  domainCodes.value.forEach(code => { const node = document.getElementById(`review-domain-${code}`); if (node) observer?.observe(node) })
  activeDomain.value = domainCodes.value[0]
}
const selectVersion = async (id: string) => {
  versionOpen.value = false
  await router.replace({ query: { ...route.query, version: id } })
  await load(id)
}
const returnCurrent = async () => { await router.replace({ query: {} }); await load() }
const startTask = async (url: string, message: string) => {
  try {
    const task = await api<ReviewTask>(url, { method: 'POST' })
    generationMessage.value = message
    generationVersionId.value = ''
    watchedTaskId.value = task.id
    menuOpen.value = false
    startTaskPolling()
  } catch (cause: any) { error.value = cause?.data?.detail || '生成任务创建失败' }
}
const regenerateFull = () => {
  menuOpen.value = false
  confirmRegenerateOpen.value = true
}
const startFullRegeneration = () => { confirmRegenerateOpen.value = false; void startTask(`/reviews/${reviewId}/regenerate`, '新版本正在生成') }
const regenerateAnalysis = () => {
  if (!detail.value) return
  menuOpen.value = false
  void startTask(`/review-versions/${detail.value.version.id}/regenerate-analysis`, '正在更新分析和行动')
}
const startTaskPolling = () => {
  if (taskPollTimer) clearInterval(taskPollTimer)
  taskPollTimer = window.setInterval(async () => {
    if (!watchedTaskId.value) return
    try {
      const task = await api<ReviewTask>(`/review-tasks/${watchedTaskId.value}`)
      if (task.status === 'SUCCEEDED' && task.result_version_id) {
        generationMessage.value = '新版本已生成'
        generationVersionId.value = task.result_version_id
      } else if (task.status === 'FAILED') generationMessage.value = task.error_message || '生成失败，请前往任务中心重试'
      else if (task.status === 'SKIPPED_NO_DATA') generationMessage.value = '没有新的有效记录可生成回顾'
      else return
      watchedTaskId.value = ''
      if (taskPollTimer) clearInterval(taskPollTimer)
      taskPollTimer = null
    } catch { /* 保留当前提示，下一轮继续轮询 */ }
  }, 5000)
}
const handleGenerationAction = () => generationVersionId.value ? selectVersion(generationVersionId.value) : navigateTo('/review/tasks')
</script>
