<template>
  <div class="border border-neutral-200 rounded-lg mb-3 bg-white">
    <!-- 标题头区域 -->
    <template v-if="editable">
      <!-- 编辑模式：直接展示 -->
      <div class="px-4 pt-3">
        <div class="sticky top-0 z-20 -mx-4 flex items-start gap-2 border-b border-neutral-100 bg-white px-4 pb-2 pt-3">
          <input v-model="editTitle" class="min-w-0 flex-1 p-1 text-base font-semibold border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none" @click.stop />
          <div class="flex shrink-0 items-center gap-0.5" role="radiogroup" aria-label="修改事件重要性">
            <button
              v-for="option in importanceOptions"
              :key="option.code"
              type="button"
              class="h-6 w-6 rounded-full border text-[10px] font-medium leading-none transition-colors disabled:opacity-50"
              :class="importanceButtonClass(option.code)"
              :aria-label="`重要性：${option.label}`"
              :aria-pressed="effectiveImportanceCode === option.code"
              :disabled="importanceSaving"
              @click.stop="handleImportanceClick(option.code)"
            >
              {{ option.label }}
            </button>
          </div>
          <button
            type="button"
            class="shrink-0 -mr-1 -mt-1 w-8 h-8 text-lg leading-none text-amber-500 disabled:opacity-50"
            :aria-label="event.is_favorite ? '取消收藏事件' : '收藏事件'"
            :title="event.is_favorite ? '取消收藏' : '收藏'"
            :disabled="favoriteSaving"
            @click.stop="emit('favorite-toggle', event.id)"
          >
            {{ event.is_favorite ? '★' : '☆' }}
          </button>
        </div>
      </div>
    </template>
    <template v-else>
      <!-- 查看模式：始终展开，不可折叠 -->
      <div class="px-4 py-3">
        <div class="sticky top-0 z-20 -mx-4 flex items-start gap-2 border-b border-neutral-100 bg-white px-4 py-3">
          <template v-if="inlineEditField === 'title'">
            <div class="min-w-0 flex-1">
              <input
                :value="inlineDraft"
                class="w-full p-1 text-base font-semibold border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none"
                aria-label="编辑事件标题"
                @input="updateField($event, 'title')"
                @click.stop
                @keyup.enter="saveInlineEdit('title')"
                @keyup.esc="emit('inline-edit-cancel')"
              />
            </div>
            <div class="mt-2 flex justify-end gap-2">
              <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click.stop="emit('inline-edit-cancel')">取消</button>
              <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click.stop="saveInlineEdit('title')">保存</button>
            </div>
            <div class="flex shrink-0 items-center gap-0.5" role="radiogroup" aria-label="修改事件重要性">
              <button
                v-for="option in importanceOptions"
                :key="option.code"
                type="button"
                class="h-6 w-6 rounded-full border text-[10px] font-medium leading-none transition-colors disabled:opacity-50"
                :class="importanceButtonClass(option.code)"
                :aria-label="`重要性：${option.label}`"
                :aria-pressed="effectiveImportanceCode === option.code"
                :disabled="importanceSaving"
                @click.stop="handleImportanceClick(option.code)"
              >
                {{ option.label }}
              </button>
            </div>
          </template>
          <template v-else>
            <div class="min-w-0 flex-1 cursor-text text-base font-medium text-neutral-800" @dblclick="handleInlineDoubleClick($event, 'title')">
              <span v-if="keyword" v-html="highlight(event.event_title || '未命名事件', keyword)"></span>
              <span v-else>{{ event.event_title || '未命名事件' }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-0.5" role="radiogroup" aria-label="修改事件重要性">
              <button
                v-for="option in importanceOptions"
                :key="option.code"
                type="button"
                class="h-6 w-6 rounded-full border text-[10px] font-medium leading-none transition-colors disabled:opacity-50"
                :class="importanceButtonClass(option.code)"
                :aria-label="`重要性：${option.label}`"
                :aria-pressed="effectiveImportanceCode === option.code"
                :disabled="importanceSaving"
                @click.stop="handleImportanceClick(option.code)"
              >
                {{ option.label }}
              </button>
            </div>
          </template>
          <button
            type="button"
            class="shrink-0 -mr-1 -mt-1 w-8 h-8 text-lg leading-none text-amber-500 disabled:opacity-50"
            :aria-label="event.is_favorite ? '取消收藏事件' : '收藏事件'"
            :title="event.is_favorite ? '取消收藏' : '收藏'"
            :disabled="favoriteSaving"
            @click.stop="emit('favorite-toggle', event.id)"
          >
            {{ event.is_favorite ? '★' : '☆' }}
          </button>
        </div>
        <!-- 命中语义层徽标（纯文本，防 XSS） -->
        <div v-if="matchedChunkLabels.length > 0" class="flex flex-wrap gap-1 mt-1">
          <span
            v-for="label in matchedChunkLabels"
            :key="label"
            class="rounded-full bg-primary-50 px-2 py-0.5 text-[10px] text-primary-700"
          >{{ label }}</span>
        </div>
        <!-- 事件标签（按类别排序） -->
        <div v-if="sortedTags.length > 0" class="flex flex-wrap mt-1.5">
          <TagBadge v-for="tag in sortedTags" :key="tag.id" :tag="tag" />
        </div>
      </div>
    </template>

    <!-- 详细内容（始终显示） -->
    <div class="px-4 pb-4">
      <!-- 正文 -->
      <div class="mt-3">
        <template v-if="editable || inlineEditField === 'body'">
          <textarea
            :value="editable ? editBody : inlineDraft"
            rows="4"
            data-auto-resize
            class="w-full min-h-[6rem] p-2 text-base border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="updateField($event, 'body'); handleTextareaInput($event)"
          />
          <div v-if="!editable" class="mt-2 flex justify-end gap-2">
            <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click.stop="emit('inline-edit-cancel')">取消</button>
            <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click.stop="saveInlineEdit('body')">保存</button>
          </div>
        </template>
        <template v-else>
          <div class="cursor-text" @dblclick="handleInlineDoubleClick($event, 'body')">
              <DiaryAnnotationText
                v-if="event.body && event.body.length > 0"
                :paragraphs="event.body"
                target-type="EVENT_BODY"
                :event-id="event.id"
                :annotations="annotations"
                :keyword="keyword"
                container-class="space-y-2"
                paragraph-class="analysis-markup text-base text-neutral-600 leading-relaxed"
                @select="emit('annotation-select', $event)"
                @annotation-clicked="emit('annotation-clicked', $event)"
              />
          </div>
        </template>
      </div>

      <!-- 感受 -->
      <div v-if="editable || inlineEditField === 'feeling' || (event.feeling && event.feeling.length > 0)" class="mt-4">
        <div class="text-[17px] font-medium text-neutral-800 mb-2">感受</div>
        <template v-if="editable || inlineEditField === 'feeling'">
          <textarea
            :value="editable ? editFeeling : inlineDraft"
            rows="3"
            data-auto-resize
            class="w-full min-h-[4.5rem] p-2 text-base border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="updateField($event, 'feeling'); handleTextareaInput($event)"
          />
          <div v-if="!editable" class="mt-2 flex justify-end gap-2">
            <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click.stop="emit('inline-edit-cancel')">取消</button>
            <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click.stop="saveInlineEdit('feeling')">保存</button>
          </div>
        </template>
        <template v-else>
          <div class="cursor-text" @dblclick="handleInlineDoubleClick($event, 'feeling')">
              <DiaryAnnotationText
                :paragraphs="event.feeling || []"
                target-type="EVENT_FEELING"
                :event-id="event.id"
                :annotations="annotations"
                :keyword="keyword"
                container-class="space-y-2"
                paragraph-class="analysis-markup text-base text-neutral-600 leading-relaxed"
                :show-index="true"
                @select="emit('annotation-select', $event)"
                @annotation-clicked="emit('annotation-clicked', $event)"
              />
          </div>
        </template>
      </div>

      <!-- 反思与成长 -->
      <div v-if="editable || inlineEditField === 'reflection' || (event.reflection && event.reflection.length > 0)" class="mt-4">
        <div class="text-[17px] font-medium text-neutral-800 mb-2">反思与成长</div>
        <template v-if="editable || inlineEditField === 'reflection'">
          <textarea
            :value="editable ? editReflection : inlineDraft"
            rows="3"
            data-auto-resize
            class="w-full min-h-[4.5rem] p-2 text-base border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="updateField($event, 'reflection'); handleTextareaInput($event)"
          />
          <div v-if="!editable" class="mt-2 flex justify-end gap-2">
            <button type="button" class="px-3 py-1.5 rounded-lg border border-neutral-200 text-sm text-neutral-600" @click.stop="emit('inline-edit-cancel')">取消</button>
            <button type="button" class="px-3 py-1.5 rounded-lg bg-primary-600 text-sm text-white" @click.stop="saveInlineEdit('reflection')">保存</button>
          </div>
        </template>
        <template v-else>
          <div class="cursor-text" @dblclick="handleInlineDoubleClick($event, 'reflection')">
              <DiaryAnnotationText
                :paragraphs="event.reflection || []"
                target-type="EVENT_REFLECTION"
                :event-id="event.id"
                :annotations="annotations"
                :keyword="keyword"
                container-class="space-y-2"
                paragraph-class="analysis-markup text-base text-neutral-600 leading-relaxed"
                :show-index="true"
                @select="emit('annotation-select', $event)"
                @annotation-clicked="emit('annotation-clicked', $event)"
              />
          </div>
        </template>
      </div>

      <!-- 事件级分析 -->
      <template v-if="!editable && event.analysis">
        <div v-if="hasEventAnalysis" class="mt-3 pt-2 border-t border-neutral-100">
            <AnalysisSection
              v-for="section in sortedAnalysisSections"
              :key="section.analysis_type"
              :analysis-run-id="analysisRunId"
              :section="section"
              compact
              :annotations="annotations"
              :keyword="keyword"
              @annotation-select="emit('annotation-select', $event)"
              @annotation-clicked="emit('annotation-clicked', $event)"
            />
        </div>
      </template>

    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, computed, watch } from 'vue'
import { resizeTextarea } from '~/composables/useAutoResizeTextarea'
import { highlight } from '~/utils/highlight'
import type { DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'

const props = defineProps<{
  event: any
  editable?: boolean
  analysisRunId?: string
  annotations?: DiaryAnnotation[]
  inlineEditField?: 'title' | 'body' | 'feeling' | 'reflection' | null
  favoriteSaving?: boolean
  importanceSaving?: boolean
  keyword?: string
  // 命中语义层（fact / self_understanding / cognition）；仅作层高亮徽标，不注入 HTML。
  matchedChunkTypes?: string[]
}>()

const emit = defineEmits<{
  (e: 'update', data: any): void
  (e: 'importance-change', eventId: string, importance: 'HIGH' | 'MEDIUM' | 'LOW'): void
  (e: 'annotation-select', selection: DiaryAnnotationSelection): void
  (e: 'annotation-clicked', payload: DiaryAnnotationClick): void
  (e: 'favorite-toggle', eventId: string): void
  (e: 'inline-edit-start', field: 'title' | 'body' | 'feeling' | 'reflection'): void
  (e: 'inline-edit-save', field: 'title' | 'body' | 'feeling' | 'reflection', value: string): void
  (e: 'inline-edit-cancel'): void
}>()

const annotations = computed(() => props.annotations || [])

// 命中语义层徽标：仅展示层名称，纯文本渲染（绝不注入 HTML，复用现有防 XSS 约定）。
const CHUNK_TYPE_LABELS: Record<string, string> = {
  fact: '事实',
  self_understanding: '自我理解',
  cognition: '认知',
}
const matchedChunkLabels = computed(() =>
  (props.matchedChunkTypes || [])
    .filter((t: string) => CHUNK_TYPE_LABELS[t])
    .map((t: string) => CHUNK_TYPE_LABELS[t]),
)

const editTitle = ref('')
const editBody = ref('')
const editFeeling = ref('')
const editReflection = ref('')
const inlineDraft = ref('')

const inlineFieldValue = (field: 'title' | 'body' | 'feeling' | 'reflection') =>
  field === 'title' ? (props.event?.event_title || '') : (props.event?.[field] || []).join('\n')

watch(() => [props.inlineEditField, props.event], () => {
  if (props.inlineEditField) inlineDraft.value = inlineFieldValue(props.inlineEditField)
}, { deep: true })

const handleInlineDoubleClick = (event: MouseEvent, field: 'title' | 'body' | 'feeling' | 'reflection') => {
  const target = event.target as HTMLElement
  if (target.closest('[data-annotation-id]')) return
  if (!window.getSelection()?.isCollapsed) return
  emit('inline-edit-start', field)
}

const saveInlineEdit = (field: 'title' | 'body' | 'feeling' | 'reflection') => {
  emit('inline-edit-save', field, inlineDraft.value)
}

const updateField = (event: Event, field: 'title' | 'body' | 'feeling' | 'reflection') => {
  const value = (event.target as HTMLTextAreaElement).value
  if (props.inlineEditField === field) {
    inlineDraft.value = value
    return
  }
  if (field === 'title') editTitle.value = value
  if (field === 'body') editBody.value = value
  if (field === 'feeling') editFeeling.value = value
  if (field === 'reflection') editReflection.value = value
}

const handleTextareaInput = (event: Event) => {
  resizeTextarea(event.target as HTMLTextAreaElement)
}

// 编辑模式切换时初始化编辑值
watch(() => props.editable, (val) => {
  if (val) {
    editTitle.value = props.event.event_title || ''
    editBody.value = (props.event.body || []).join('\n')
    editFeeling.value = (props.event.feeling || []).join('\n')
    editReflection.value = (props.event.reflection || []).join('\n')
    nextTick(() => {
      document.querySelectorAll<HTMLTextAreaElement>('textarea[data-auto-resize]').forEach(resizeTextarea)
    })
  }
}, { immediate: true })

// 编辑模式下，实时向父组件发送更新通知
watch([editTitle, editBody, editFeeling, editReflection], () => {
  if (props.editable) {
    emit('update', {
      id: props.event.id,
      event_title: editTitle.value,
      body: editBody.value.split('\n').filter((s: string) => s.trim()),
      feeling: editFeeling.value.split('\n').filter((s: string) => s.trim()),
      reflection: editReflection.value.split('\n').filter((s: string) => s.trim()),
    })
  }
}, { deep: true })

// 标签按类别排序：领域 → 主题 → 人物/对象 → 心理 → 知识点
const TAG_TYPE_ORDER: Record<string, number> = {
  domain: 0,
  topic: 1,
  person_object: 2,
  psychological: 3,
  knowledge: 4,
}

const sortedTags = computed(() => {
  const tags = props.event.tags || []
  return [...tags].sort((a: any, b: any) => {
    const orderA = TAG_TYPE_ORDER[a.type] ?? 99
    const orderB = TAG_TYPE_ORDER[b.type] ?? 99
    return orderA - orderB
  })
})

const sectionOrder = [
  'EMOTION',
  'BEHAVIOR_DECISION',
  'SELF_UNDERSTANDING',
  'ACTION_SUGGESTION',
  'COGNITIVE_CALIBRATION',
  'QUESTION_ANSWER',
  'COGNITIVE_ENHANCEMENT',
]

const sortedAnalysisSections = computed(() => {
  const sections = props.event.analysis || []
  return [...sections].sort((a: any, b: any) => sectionOrder.indexOf(a.analysis_type) - sectionOrder.indexOf(b.analysis_type))
})

const analysisRunId = computed(() => props.analysisRunId || '')
const hasEventAnalysis = computed(() => sortedAnalysisSections.value.length > 0 && !!analysisRunId.value)
const importanceOptions = [
  { code: 'HIGH' as const, label: '高' },
  { code: 'MEDIUM' as const, label: '中' },
  { code: 'LOW' as const, label: '低' },
]
const effectiveImportanceCode = computed<'HIGH' | 'MEDIUM' | 'LOW' | ''>(() => {
  const value = props.event.user_importance || props.event.ai_importance
  return value === 'HIGH' || value === 'MEDIUM' || value === 'LOW' ? value : ''
})

const importanceButtonClass = (importance: 'HIGH' | 'MEDIUM' | 'LOW') => {
  if (effectiveImportanceCode.value === importance) {
    return importance === 'HIGH'
      ? 'border-red-500 bg-red-500 text-white'
      : importance === 'MEDIUM'
        ? 'border-orange-500 bg-orange-500 text-white'
        : 'border-neutral-500 bg-neutral-500 text-white'
  }
  return importance === 'HIGH'
    ? 'border-red-200 text-red-500 hover:bg-red-50'
    : importance === 'MEDIUM'
      ? 'border-orange-200 text-orange-500 hover:bg-orange-50'
      : 'border-neutral-300 text-neutral-500 hover:bg-neutral-50'
}

const handleImportanceClick = (importance: 'HIGH' | 'MEDIUM' | 'LOW') => {
  emit('importance-change', props.event.id, importance)
}
</script>

<style>
.search-keyword {
  background-color: #fef08a;
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}
</style>
