<template>
  <div class="min-h-dvh bg-neutral-50 pb-24">
    <NavBar :title="reviewTypeLabel" show-back>
      <template #right>
        <button type="button" class="min-h-11 text-sm font-semibold text-primary-700" @click="versionOpen = true">版本</button>
      </template>
    </NavBar>

    <div v-if="loading" class="mx-auto max-w-md space-y-4 p-4"><div class="h-40 animate-pulse rounded-2xl bg-white"/><div v-for="index in 2" :key="index" class="h-72 animate-pulse rounded-2xl bg-white"/></div>
    <main v-else-if="detail" class="mx-auto max-w-md">
      <header class="bg-white px-5 py-6">
        <p class="text-sm font-medium text-primary-700">{{ periodLabel }}</p>
        <p class="mt-1 text-xs text-neutral-400">v{{ detail.version.version_no }} · {{ formatDateTime(detail.version.created_at) }}</p>
        <p class="mt-4 whitespace-pre-wrap text-base leading-7 text-neutral-700">{{ detail.version.summary || '这份回顾已根据本期记录生成。' }}</p>
        <p class="mt-4 text-xs text-neutral-400">{{ domainCodes.length }} 个领域 · {{ threadCount }} 条主要发展线</p>
      </header>

      <div class="space-y-3 px-4 pt-4">
        <ReviewStatusBanner v-if="isHistorical" title="你正在查看历史版本" action-label="返回当前版本" @action="returnCurrent" />
        <ReviewStatusBanner v-if="detail.version.superseded_at_creation" title="生成期间内容已更新" description="这个版本没有设为当前版本。" tone="warning" />
        <ReviewStatusBanner v-if="detail.version.analysis_stale" title="事件事实已由你修改" description="当前分析和候选行动可能不再适用。" action-label="更新分析和行动" tone="warning" @action="regenerateAnalysis" />
        <ReviewStatusBanner v-if="detail.source_updates_available" title="回顾来源已有新版本" description="当前版本不会自动改变；需要时可以根据最新来源重新生成。" action-label="重新生成" tone="warning" @action="regenerateFull" />
        <ReviewStatusBanner v-if="missingPeriodDescription" title="部分下级周期资料缺失" :description="missingPeriodDescription" tone="warning" />
        <ReviewStatusBanner v-if="generationMessage" :title="generationMessage" :description="generationVersionId ? '当前版本仍然保留，你可以选择切换到新版本。' : '生成期间仍可阅读当前版本。'" :action-label="generationVersionId ? '查看新版本' : '查看任务'" @action="handleGenerationAction" />
      </div>

      <section v-if="dailyDigests.length" class="mx-4 mt-4 rounded-2xl bg-white px-4 py-4">
        <h2 class="text-base font-semibold text-neutral-900">每日提炼</h2>
        <p class="mt-1 text-sm leading-5 text-neutral-500">按自然日合并当日多篇日记，仅供查看；修改原始日记、分析反馈或划线评论后，重新生成回顾即可更新。</p>
        <details v-for="digest in dailyDigests" :key="digest.id" class="border-b border-neutral-100 py-3 last:border-b-0">
          <summary class="cursor-pointer list-none text-sm font-medium text-neutral-800">{{ shortDate(digest.digest_date) }} · {{ digestItems(digest).length }} 条本日事项</summary>
          <div class="mt-3 space-y-3">
            <article v-for="item in digestItems(digest)" :key="item.item_key" class="rounded-xl bg-neutral-50 px-3 py-3">
              <p class="text-sm font-semibold text-neutral-800">{{ item.title }}</p>
              <p class="mt-1 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ item.fact }}</p>
              <p v-if="item.open_points?.length" class="mt-2 text-xs leading-5 text-neutral-500">待跟进：{{ item.open_points.join('；') }}</p>
            </article>
            <template v-for="item in digestAnalysisItems(digest)" :key="item.item_key">
              <article v-if="digestAnalysisText(item)" class="rounded-xl bg-primary-50 px-3 py-3">
                <p class="text-xs font-semibold text-primary-700">分析</p>
                <p class="mt-1 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ digestAnalysisText(item) }}</p>
              </article>
            </template>
            <button v-if="digestSourceIds(digest).length" type="button" class="min-h-11 text-sm text-primary-700" @click="openSources(digestSourceIds(digest), `${shortDate(digest.digest_date)}每日提炼依据`)">查看原始事件定位</button>
          </div>
        </details>
      </section>

      <div v-if="domainCodes.length" class="sticky top-nav z-30 mt-4 border-y border-neutral-100 bg-white">
        <ReviewDomainNav :domains="domainCodes" :active="activeDomain" @select="scrollToDomain" />
      </div>
      <div class="space-y-4 px-4 py-4">
        <ReviewDomainSection
          v-for="code in domainCodes"
          :key="code"
          :review-id="reviewId"
          :version-id="detail.version.id"
          :domain-code="code"
          :event-domain="eventDomain(code)"
          :analysis-domain="analysisDomain(code)"
          :actions="detail.actions"
          :checks="detail.action_checks"
          :feedback="detail.feedback"
          :related-entries="relatedEntries(code)"
          @sources="openSources"
          @feedback-updated="updateFeedback"
          @action-updated="updateAction"
          @action-ignored="showUndoToast"
          @related-select="scrollToDomain"
        />
        <section v-if="detail.version.event_document.other_matters?.length" class="rounded-2xl bg-white px-5 py-4">
          <h2 class="text-base font-semibold text-neutral-900">其他事项</h2>
          <article v-for="item in detail.version.event_document.other_matters" :key="`${item.title}-${item.narrative}`" class="border-b border-neutral-100 py-3 last:border-b-0">
            <p class="text-sm font-semibold text-neutral-800">{{ item.title }}</p>
            <p class="mt-1 text-sm leading-6 text-neutral-700">{{ item.narrative }}</p>
            <button type="button" class="mt-1 min-h-11 text-sm text-primary-700" @click="openSources(item.source_ids, item.title)">查看依据</button>
          </article>
        </section>
        <section v-if="!domainCodes.length" class="rounded-2xl bg-white px-5 py-16 text-center text-sm text-neutral-500">这个版本没有可展示的回顾内容。</section>
      </div>
    </main>
    <div v-else class="mx-auto max-w-md p-4"><ReviewStatusBanner :title="error || '回顾不存在'" action-label="重新加载" tone="error" @action="load" /></div>

    <div v-if="detail" class="fixed inset-x-0 bottom-0 z-40 border-t border-neutral-200 bg-white pb-[env(safe-area-inset-bottom)]">
      <div class="mx-auto flex max-w-md gap-3 px-4 py-3">
        <NuxtLink v-if="detail" :to="`/review/${reviewId}/chat?version=${detail.version.id}`" class="flex min-h-12 flex-1 items-center justify-center rounded-xl border border-primary-200 bg-primary-50 text-sm font-semibold text-primary-700">围绕这份回顾对话</NuxtLink>
        <button type="button" class="min-h-12 flex-1 rounded-xl bg-primary-600 text-sm font-semibold text-white" @click="menuOpen = true">回顾操作</button>
        <button type="button" class="min-h-12 w-12 rounded-xl bg-neutral-100 text-xl text-neutral-600" aria-label="更多操作" @click="menuOpen = true">···</button>
      </div>
    </div>

    <ReviewSourceSheet :open="sourceOpen" :version-id="detail?.version.id || ''" :source-ids="sourceIds" :title="sourceTitle" @close="sourceOpen = false" />
    <ReviewVersionSheet :open="versionOpen" :review-id="reviewId" :current-version-id="detail?.version.id || ''" @close="versionOpen = false" @select="selectVersion" />

    <Teleport to="body">
      <div v-if="menuOpen" class="fixed inset-0 z-[75] flex items-end justify-center bg-black/35" @click.self="menuOpen = false" @keydown.esc="menuOpen = false">
        <section ref="menuRef" tabindex="-1" class="w-full max-w-md rounded-t-3xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] focus:outline-none">
          <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-neutral-300" />
          <h2 class="font-semibold text-neutral-900">回顾操作</h2>
          <button type="button" class="mt-3 min-h-14 w-full border-b border-neutral-100 text-left text-sm font-medium text-neutral-800" @click="regenerateFull">根据最新来源重新生成整个回顾</button>
          <button v-if="detail?.version.analysis_stale" type="button" class="min-h-14 w-full border-b border-neutral-100 text-left text-sm font-medium text-neutral-800" @click="regenerateAnalysis">根据事件修改更新分析和行动</button>
          <button type="button" class="min-h-14 w-full text-left text-sm font-medium text-neutral-800" @click="menuOpen = false; versionOpen = true">查看所有版本</button>
          <button type="button" class="mt-2 min-h-12 w-full rounded-xl bg-neutral-100 text-sm text-neutral-600" @click="menuOpen = false">取消</button>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="confirmRegenerateOpen" class="fixed inset-0 z-[85] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="确认重新生成" @click.self="confirmRegenerateOpen = false" @keydown.esc="confirmRegenerateOpen = false">
        <section class="w-full max-w-md rounded-t-3xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
          <div class="mx-auto mb-4 h-1 w-10 rounded-full bg-neutral-300" />
          <h2 class="font-semibold text-neutral-900">重新生成整个{{ reviewTypeLabel }}？</h2>
          <p class="mt-3 text-sm leading-6 text-neutral-600">将读取最新日记、分析反馈、日程和上一同级回顾，重新组织事件并更新分析和行动。当前版本和对话都会保留。</p>
          <div class="mt-5 grid grid-cols-2 gap-3">
            <button type="button" autofocus class="min-h-12 rounded-xl bg-neutral-100 text-sm text-neutral-600" @click="confirmRegenerateOpen = false">取消</button>
            <button type="button" class="min-h-12 rounded-xl bg-primary-600 text-sm font-semibold text-white" @click="startFullRegeneration">开始生成</button>
          </div>
        </section>
      </div>
    </Teleport>

    <div v-if="undoAction" class="fixed inset-x-4 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] z-[90] mx-auto flex max-w-sm items-center justify-between rounded-xl bg-neutral-900 px-4 py-3 text-sm text-white shadow-xl">
      <span>已忽略行动</span>
      <button type="button" class="min-h-11 px-3 font-semibold text-primary-200" @click="undoIgnoredAction">撤销</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ReviewAction, ReviewAnalysisDomain, ReviewDailyAnalysisItem, ReviewDailyDigest, ReviewDomainCode, ReviewEventDomain, ReviewFeedback, ReviewTask, ReviewVersionDetail } from '~/types'

definePageMeta({ layout: 'auth', middleware: 'auth' })
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
const sourceOpen = ref(false)
const sourceIds = ref<string[]>([])
const sourceTitle = ref('')
const activeDomain = ref<ReviewDomainCode>()
const generationMessage = ref('')
const generationVersionId = ref('')
const watchedTaskId = ref('')
const confirmRegenerateOpen = ref(false)
const undoAction = ref<ReviewAction | null>(null)
let undoTimer: ReturnType<typeof setTimeout> | null = null
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
  if (undoTimer) clearTimeout(undoTimer)
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
const shortDate = (value: string) => `${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日`
const periodLabel = computed(() => {
  if (!detail.value) return ''
  const review = detail.value.review
  return review.review_type === 'MONTH' ? `${review.period_start.slice(0, 4)} 年 ${Number(review.period_start.slice(5, 7))} 月` : `${shortDate(review.period_start)}－${shortDate(review.period_end)}`
})
const formatDateTime = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
const eventDomains = computed(() => detail.value?.version.event_document?.domains || [])
const analysisDomains = computed(() => detail.value?.version.analysis_document?.domains || [])
const domainCodes = computed(() => {
  const values = new Set<ReviewDomainCode>()
  eventDomains.value.forEach(domain => {
    values.add(domain.domain_code)
    domain.event_threads?.forEach(thread => thread.related_domains?.forEach(code => values.add(code)))
  })
  analysisDomains.value.forEach(domain => {
    values.add(domain.domain_code)
    domain.analysis_items?.forEach(item => item.related_domains?.forEach(code => values.add(code)))
  })
  detail.value?.actions.forEach(action => {
    values.add(action.primary_domain || action.domain_code!)
    action.related_domains?.forEach(code => values.add(code))
  })
  detail.value?.action_checks.forEach(check => { if (check.primary_domain) values.add(check.primary_domain) })
  return [...values].filter(Boolean)
})
const threadCount = computed(() => eventDomains.value.reduce((sum, domain) => sum + (domain.event_threads?.length || 0), 0))
const digestItems = (digest: ReviewDailyDigest) => digest.event_document?.items || []
const digestAnalysisItems = (digest: ReviewDailyDigest) => digest.analysis_document?.items || []
const digestAnalysisText = (item: ReviewDailyAnalysisItem) => [
  ...(item.user_attention || []),
  ...(item.preferred_explanations || []),
  ...(item.feedback_constraints || []),
  ...(item.insufficient_evidence || []),
].join('；')
const digestSourceIds = (digest: ReviewDailyDigest) => [...new Set(digestItems(digest).flatMap(item => item.source_ids || []))]
const missingPeriodDescription = computed(() => {
  const periods = (detail.value?.version.missing_periods || []) as Array<{ period_start?: string; period_end?: string; status?: string }>
  if (!periods.length) return ''
  return periods.map(item => `${item.period_start || '?'}－${item.period_end || '?'}（${item.status === 'FAILED' ? '生成失败' : item.status === 'SKIPPED_NO_DATA' ? '无有效记录' : '缺失'}）`).join('；')
})
const eventDomain = (code: ReviewDomainCode) => eventDomains.value.find(domain => domain.domain_code === code) as ReviewEventDomain | undefined
const analysisDomain = (code: ReviewDomainCode) => analysisDomains.value.find(domain => domain.domain_code === code) as ReviewAnalysisDomain | undefined
const relatedEntries = (code: ReviewDomainCode) => {
  const entries: Array<{ key: string; label: string; primaryDomain: ReviewDomainCode }> = []
  for (const domain of eventDomains.value) for (const thread of domain.event_threads || []) {
    if (domain.domain_code !== code && thread.related_domains?.includes(code)) entries.push({ key: `event-${thread.thread_key}`, label: thread.title, primaryDomain: domain.domain_code })
  }
  for (const domain of analysisDomains.value) for (const item of domain.analysis_items || []) {
    if (domain.domain_code !== code && item.related_domains?.includes(code)) entries.push({ key: `analysis-${item.analysis_item_id || item.analysis_key}`, label: item.claim.slice(0, 36), primaryDomain: domain.domain_code })
  }
  for (const action of detail.value?.actions || []) {
    if (action.primary_domain !== code && action.related_domains?.includes(code)) entries.push({ key: `action-${action.id}`, label: action.edited_content || action.content, primaryDomain: action.primary_domain })
  }
  return entries
}
const isHistorical = computed(() => !!detail.value && detail.value.review.current_version_id !== detail.value.version.id)
const scrollToDomain = (code: ReviewDomainCode) => document.getElementById(`review-domain-${code}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
const observeDomains = () => {
  observer?.disconnect()
  observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
    if (visible) activeDomain.value = visible.target.id.replace('review-domain-', '') as ReviewDomainCode
  }, { rootMargin: '-110px 0px -65% 0px' })
  domainCodes.value.forEach(code => { const node = document.getElementById(`review-domain-${code}`); if (node) observer?.observe(node) })
  activeDomain.value = domainCodes.value[0]
}
const openSources = (ids: string[], title: string) => { sourceIds.value = ids; sourceTitle.value = title; sourceOpen.value = true }
const updateFeedback = (saved: ReviewFeedback) => {
  if (!detail.value) return
  const index = detail.value.feedback.findIndex(item => item.analysis_item_id === saved.analysis_item_id)
  if (index >= 0) detail.value.feedback[index] = saved
  else detail.value.feedback.push(saved)
}
const updateAction = (saved: ReviewAction) => {
  if (!detail.value) return
  const index = detail.value.actions.findIndex(item => item.id === saved.id)
  if (index >= 0) detail.value.actions[index] = saved
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
const showUndoToast = (action: ReviewAction) => {
  undoAction.value = action
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = window.setTimeout(() => { undoAction.value = null }, 5000)
}
const undoIgnoredAction = async () => {
  if (!undoAction.value || !detail.value) return
  const action = undoAction.value
  undoAction.value = null
  const saved = await api<ReviewAction>(`/review-versions/${detail.value.version.id}/actions/${action.id}`, { method: 'PATCH', body: { status: 'CANDIDATE' } })
  updateAction(saved)
}
</script>
