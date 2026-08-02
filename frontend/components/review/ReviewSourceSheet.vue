<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="分析依据" @click.self="$emit('close')" @keydown.esc="$emit('close')">
      <section ref="dialogRef" tabindex="-1" class="max-h-[82dvh] w-full max-w-md overflow-y-auto rounded-t-3xl bg-white pb-[calc(1.25rem+env(safe-area-inset-bottom))] focus:outline-none">
        <div class="sticky top-0 z-10 border-b border-neutral-100 bg-white px-5 pb-3 pt-2">
          <div class="mx-auto mb-3 h-1 w-10 rounded-full bg-neutral-300" />
          <div class="flex items-center justify-between gap-3">
            <div>
              <button v-if="frames.length > 1" type="button" class="mb-1 min-h-11 text-sm font-medium text-primary-700" @click="goBack">‹ 返回上一级</button>
              <h2 class="font-semibold text-neutral-900">分析依据</h2>
              <p class="mt-0.5 text-xs text-neutral-500">{{ breadcrumb }}</p>
            </div>
            <button type="button" class="min-h-11 min-w-11 text-xl text-neutral-500" aria-label="关闭" @click="$emit('close')">×</button>
          </div>
        </div>
        <div class="space-y-3 p-5">
          <p v-if="loading" class="py-8 text-center text-sm text-neutral-400">正在读取依据…</p>
          <ReviewStatusBanner v-else-if="error" :title="error" tone="error" />
          <article v-for="source in sources" :key="source.id" class="rounded-xl border border-neutral-200 p-4">
            <p class="text-xs font-medium text-primary-700">{{ sourceTypeLabel(source.source_type || source.type || '') }}<span v-if="source.source_date || source.date"> · {{ source.source_date || source.date }}</span></p>
            <template v-if="source.source_type === 'USER_FACT_CORRECTION' && correctionOriginal(source)">
              <p class="mt-2 text-xs font-medium text-neutral-400">修正后内容</p>
              <p class="mt-1 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ source.content }}</p>
              <p class="mt-3 text-xs font-medium text-neutral-400">原依据</p>
              <p class="mt-1 whitespace-pre-wrap rounded-lg bg-neutral-50 p-3 text-sm leading-6 text-neutral-600">{{ correctionOriginal(source) }}</p>
            </template>
            <p v-else class="mt-2 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ source.content }}</p>
            <button v-if="canDrill(source)" type="button" class="mt-2 flex min-h-11 items-center text-sm font-medium text-primary-700" @click="drill(source)">沿来源链查看下一级 ›</button>
            <NuxtLink v-else-if="source.origin_review_id" :to="`/review/${source.origin_review_id}?version=${source.origin_review_version_id || ''}`" class="mt-2 flex min-h-11 items-center text-sm font-medium text-primary-700">查看下级回顾 ›</NuxtLink>
            <NuxtLink v-if="originUrl(source)" :to="originUrl(source)!" class="mt-2 flex min-h-11 items-center text-sm font-medium text-primary-700">查看原记录 ›</NuxtLink>
          </article>
          <p v-if="!loading && !error && !sources.length" class="py-8 text-center text-sm text-neutral-400">没有可展示的依据</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { ReviewSource } from '~/types'

const props = withDefaults(defineProps<{ open: boolean; versionId: string; sourceIds: string[]; title?: string }>(), { title: '' })
defineEmits<{ (event: 'close'): void }>()
const { api } = useApi()
const loading = ref(false)
const error = ref('')
const sources = ref<ReviewSource[]>([])
const dialogRef = ref<HTMLElement | null>(null)
let restoreFocus: HTMLElement | null = null
type Frame = { versionId: string; sourceIds: string[]; title: string }
const frames = ref<Frame[]>([])
const currentFrame = computed(() => frames.value[frames.value.length - 1])
const breadcrumb = computed(() => frames.value.map(frame => frame.title).join(' › ') || props.title)

const load = async () => {
  const frame = currentFrame.value
  if (!props.open || !frame?.versionId || !frame.sourceIds.length) { sources.value = []; return }
  loading.value = true
  error.value = ''
  try {
    sources.value = await Promise.all(frame.sourceIds.map(id => api<ReviewSource>(`/review-versions/${frame.versionId}/sources/${id}`)))
  } catch (cause: any) {
    error.value = cause?.data?.detail || '依据加载失败'
  } finally { loading.value = false }
}
watch(() => [props.open, props.versionId, props.sourceIds.join(',')], () => {
  if (props.open) frames.value = [{ versionId: props.versionId, sourceIds: [...props.sourceIds], title: props.title || '当前回顾' }]
  else frames.value = []
  void load()
}, { immediate: true })
watch(() => props.open, async (open) => {
  if (open) {
    restoreFocus = document.activeElement as HTMLElement | null
    await nextTick()
    dialogRef.value?.focus()
  } else {
    restoreFocus?.focus()
    restoreFocus = null
  }
})
const sourceTypeLabel = (type: string) => ({ DIARY_EVENT: '事实记录', SCHEDULE_OCCURRENCE: '日程记录', USER_FACT_CORRECTION: '你修改的事实', LOWER_REVIEW_EVENT: '下级回顾事件', LOWER_REVIEW_ANALYSIS: '下级回顾分析', PRIOR_REVIEW_EVENT: '上一周期背景' }[type] || '回顾来源')
const lowerSourceId = (source: ReviewSource) => {
  const value = source.snapshot?.lower_source_id
  return typeof value === 'string' ? value : ''
}
const canDrill = (source: ReviewSource) => !!source.origin_review_version_id && !!lowerSourceId(source)
const drill = async (source: ReviewSource) => {
  if (!source.origin_review_version_id || !lowerSourceId(source)) return
  frames.value.push({ versionId: source.origin_review_version_id, sourceIds: [lowerSourceId(source)], title: `${source.source_date || ''} 下级回顾` })
  await load()
}
const goBack = async () => { if (frames.value.length > 1) frames.value.pop(); await load() }
const correctionOriginal = (source: ReviewSource) => {
  const value = source.snapshot?.original_narrative
  return typeof value === 'string' ? value : ''
}
const originUrl = (source: ReviewSource) => {
  const origin = source.origin
  if (!origin) return null
  if (origin.diary_id || origin.type === 'DIARY') return `/diary/${origin.diary_id || origin.id}`
  if (origin.date || origin.type === 'SCHEDULE') return `/schedule?date=${origin.date || source.source_date || source.date}`
  return null
}
</script>
