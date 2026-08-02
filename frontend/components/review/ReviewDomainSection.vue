<template>
  <section :id="`review-domain-${domainCode}`" class="scroll-mt-[88px] rounded-3xl border border-[#e8e1d5] bg-[#fffdf8] px-5 py-6 sm:px-6">
    <header>
      <p class="text-[11px] font-semibold tracking-[0.16em] text-primary-700">生活领域</p>
      <h2 class="mt-1 text-xl font-semibold tracking-tight text-[#26322b]">{{ domainMeta.icon }} {{ domainMeta.label }}</h2>
      <p v-if="focusLabel" class="mt-1 text-sm leading-6 text-neutral-500">核心关注：{{ focusLabel }}</p>
    </header>

    <div v-if="relatedEntries.length" class="mt-4 rounded-xl bg-neutral-50 px-4 py-3">
      <p class="text-xs font-semibold text-neutral-500">相关领域引用</p>
      <button
        v-for="entry in relatedEntries"
        :key="entry.key"
        type="button"
        class="flex min-h-11 w-full items-center justify-between border-b border-neutral-100 text-left text-sm text-neutral-700 last:border-b-0"
        @click="$emit('related-select', entry.primaryDomain)"
      >
        <span>{{ entry.label }}</span><span class="text-primary-600">查看原领域 ›</span>
      </button>
    </div>

    <div v-if="eventDomain?.event_threads?.length" class="mt-5">
      <h3 class="border-l-4 border-primary-400 pl-3 text-sm font-semibold text-neutral-700">我的回顾</h3>
      <div class="mt-2 divide-y divide-neutral-100">
        <ReviewEventThread v-for="thread in eventDomain.event_threads" :key="thread.thread_key" :review-id="reviewId" :version-id="versionId" :thread="thread" @sources="forwardSources" />
      </div>
    </div>

    <div v-if="analysisDomain?.analysis_items?.length" class="mt-6 border-t border-neutral-100 pt-5">
      <h3 class="border-l-4 border-[#8f87a8] pl-3 text-sm font-semibold text-neutral-700">观察与分析</h3>
      <div class="mt-4 space-y-3">
        <ReviewAnalysisItem
          v-for="item in analysisDomain.analysis_items"
          :key="item.analysis_key"
          :version-id="versionId"
          :item="item"
          :feedback="feedbackFor(item)"
          @saved="$emit('feedback-updated', $event)"
          @sources="forwardSources"
        />
      </div>
    </div>

    <div v-if="domainChecks.length" class="mt-6 border-t border-neutral-100 pt-5">
      <h3 class="text-sm font-semibold text-neutral-700">上期行动回看</h3>
      <article v-for="check in domainChecks" :key="check.id" class="mt-3 rounded-xl bg-neutral-50 p-4">
        <p v-if="check.previous_action_content || check.previous_action" class="text-sm font-medium text-neutral-800">{{ check.previous_action_content || check.previous_action?.edited_content || check.previous_action?.content }}</p>
        <p class="mt-1 text-sm leading-6 text-neutral-600">{{ check.explanation }}</p>
        <button v-if="check.evidence_source_ids.length" type="button" class="mt-1 min-h-11 text-sm text-neutral-500" @click="forwardSources(check.evidence_source_ids, '上期行动回看')">{{ check.evidence_source_ids.length }} 条依据</button>
      </article>
    </div>

    <div v-if="visibleActions.length || ignoredActions.length" class="mt-6 border-t border-neutral-100 pt-5">
      <h3 class="border-l-4 border-emerald-400 pl-3 text-sm font-semibold text-neutral-700">下一步</h3>
      <div class="mt-4 space-y-3">
        <ReviewActionItem v-for="action in visibleActions" :key="action.id" :version-id="versionId" :action="action" @updated="$emit('action-updated', $event)" @sources="forwardSources" @ignored="$emit('action-ignored', $event)" />
      </div>
      <button v-if="ignoredActions.length" type="button" class="mt-2 min-h-11 text-sm text-neutral-500" @click="showIgnored = !showIgnored">
        {{ showIgnored ? '收起' : `查看 ${ignoredActions.length} 项已忽略行动` }}
      </button>
      <div v-if="showIgnored" class="mt-2 space-y-3">
        <ReviewActionItem v-for="action in ignoredActions" :key="action.id" :version-id="versionId" :action="action" show-ignored @updated="$emit('action-updated', $event)" @sources="forwardSources" />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ReviewAction, ReviewActionCheck, ReviewAnalysisDomain, ReviewAnalysisItemData, ReviewDomainCode, ReviewEventDomain, ReviewFeedback } from '~/types'

const props = defineProps<{
  reviewId: string
  versionId: string
  domainCode: ReviewDomainCode
  eventDomain?: ReviewEventDomain
  analysisDomain?: ReviewAnalysisDomain
  actions: ReviewAction[]
  checks: ReviewActionCheck[]
  feedback: ReviewFeedback[]
  relatedEntries: Array<{ key: string; label: string; primaryDomain: ReviewDomainCode }>
}>()
const emit = defineEmits<{
  (event: 'sources', ids: string[], title: string): void
  (event: 'feedback-updated', feedback: ReviewFeedback): void
  (event: 'action-updated', action: ReviewAction): void
  (event: 'action-ignored', action: ReviewAction): void
  (event: 'related-select', code: ReviewDomainCode): void
}>()
const showIgnored = ref(false)
const meta: Record<ReviewDomainCode, { icon: string; label: string }> = {
  WORK_CAREER: { icon: '💼', label: '工作与事业' }, HEALTH_WELLBEING: { icon: '🌿', label: '身心健康' },
  RELATIONSHIPS_SOCIAL: { icon: '🤝', label: '关系与社交' }, LEARNING_GROWTH: { icon: '📚', label: '学习与个人成长' },
  LIFE_RESOURCES: { icon: '🏠', label: '生活管理与资源' }, LEISURE_EXPERIENCE: { icon: '🎈', label: '休闲与体验' },
}
const domainMeta = computed(() => meta[props.domainCode])
const focusLabel = computed(() => (props.eventDomain?.core_focus || []).map(focus => focus.label).join('、'))
const domainActions = computed(() => props.actions.filter(action => (action.domain_code || action.primary_domain) === props.domainCode))
const visibleActions = computed(() => domainActions.value.filter(action => action.status !== 'IGNORED'))
const ignoredActions = computed(() => domainActions.value.filter(action => action.status === 'IGNORED'))
const domainChecks = computed(() => props.checks.filter(check => (check.primary_domain || check.previous_action?.domain_code || check.previous_action?.primary_domain) === props.domainCode))
const feedbackFor = (item: ReviewAnalysisItemData) => {
  const id = item.analysis_item_id || item.id || item.analysis_key
  return props.feedback.find(entry => entry.analysis_item_id === id) || null
}
const forwardSources = (ids: string[], title: string) => emit('sources', ids, title)
</script>
