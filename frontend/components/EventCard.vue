<template>
  <div class="border border-neutral-200 rounded-lg mb-3 overflow-hidden">
    <!-- 标题头区域 -->
    <template v-if="editable">
      <!-- 编辑模式：直接展示 -->
      <div class="px-4 pt-3">
        <input v-model="editTitle" class="w-full p-1 text-base font-semibold border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none" @click.stop />
        <label class="mt-3 flex items-center gap-2 text-sm text-neutral-700">
          <span>重要性</span>
          <select v-model="editImportance" class="min-h-10 rounded border border-neutral-300 bg-white px-2 text-base" @click.stop>
            <option value="">按 AI 判断</option>
            <option value="HIGH">高</option>
            <option value="MEDIUM">中</option>
            <option value="LOW">低</option>
          </select>
        </label>
        <input v-if="editImportance" v-model="editImportanceReason" class="mt-2 min-h-10 w-full rounded border border-neutral-300 px-2 text-base" placeholder="调整原因（可选）" @click.stop>
      </div>
    </template>
    <template v-else>
      <!-- 查看模式：始终展开，不可折叠 -->
      <div class="px-4 py-3">
        <div class="flex items-start justify-between gap-3">
          <div class="text-base font-medium text-neutral-800">
              {{ event.event_title || '未命名事件' }}
          </div>
          <span v-if="effectiveImportance" class="rounded bg-primary-50 px-2 py-1 text-xs text-primary-700">{{ effectiveImportance }}重要</span>
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
        <template v-if="editable">
          <textarea
            v-model="editBody"
            rows="4"
            data-auto-resize
            class="w-full min-h-[6rem] p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="handleTextareaInput"
          />
        </template>
        <template v-else>
          <DiaryAnnotationText
            v-if="event.body && event.body.length > 0"
            :paragraphs="event.body"
            target-type="EVENT_BODY"
            :event-id="event.id"
            :annotations="annotations"
            container-class="space-y-2"
            paragraph-class="analysis-markup text-sm text-neutral-600 leading-relaxed"
            @select="emit('annotation-select', $event)"
            @annotation-clicked="emit('annotation-clicked', $event)"
          />
        </template>
      </div>

      <!-- 感受 -->
      <div v-if="editable || (event.feeling && event.feeling.length > 0)" class="mt-4">
        <div class="text-[15px] font-medium text-neutral-800 mb-2">感受</div>
        <template v-if="editable">
          <textarea
            v-model="editFeeling"
            rows="3"
            data-auto-resize
            class="w-full min-h-[4.5rem] p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="handleTextareaInput"
          />
        </template>
        <template v-else>
          <DiaryAnnotationText
            :paragraphs="event.feeling || []"
            target-type="EVENT_FEELING"
            :event-id="event.id"
            :annotations="annotations"
            container-class="space-y-2"
            paragraph-class="analysis-markup text-sm text-neutral-600 leading-relaxed"
            :show-index="true"
            @select="emit('annotation-select', $event)"
            @annotation-clicked="emit('annotation-clicked', $event)"
          />
        </template>
      </div>

      <!-- 反思与成长 -->
      <div v-if="editable || (event.reflection && event.reflection.length > 0)" class="mt-4">
        <div class="text-[15px] font-medium text-neutral-800 mb-2">反思与成长</div>
        <template v-if="editable">
          <textarea
            v-model="editReflection"
            rows="3"
            data-auto-resize
            class="w-full min-h-[4.5rem] p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="handleTextareaInput"
          />
        </template>
        <template v-else>
          <DiaryAnnotationText
            :paragraphs="event.reflection || []"
            target-type="EVENT_REFLECTION"
            :event-id="event.id"
            :annotations="annotations"
            container-class="space-y-2"
            paragraph-class="analysis-markup text-sm text-neutral-600 leading-relaxed"
            :show-index="true"
            @select="emit('annotation-select', $event)"
            @annotation-clicked="emit('annotation-clicked', $event)"
          />
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
import type { DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'

const props = defineProps<{
  event: any
  editable?: boolean
  analysisRunId?: string
  annotations?: DiaryAnnotation[]
  favoriteSaving?: boolean
}>()

const emit = defineEmits<{
  (e: 'update', data: any): void
  (e: 'annotation-select', selection: DiaryAnnotationSelection): void
  (e: 'annotation-clicked', payload: DiaryAnnotationClick): void
  (e: 'favorite-toggle', eventId: string): void
}>()

const annotations = computed(() => props.annotations || [])

const editTitle = ref('')
const editBody = ref('')
const editFeeling = ref('')
const editReflection = ref('')
const editImportance = ref('')
const editImportanceReason = ref('')

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
    editImportance.value = props.event.user_importance || ''
    editImportanceReason.value = props.event.user_importance_reason || ''
    nextTick(() => {
      document.querySelectorAll<HTMLTextAreaElement>('textarea[data-auto-resize]').forEach(resizeTextarea)
    })
  }
}, { immediate: true })

// 编辑模式下，实时向父组件发送更新通知
watch([editTitle, editBody, editFeeling, editReflection, editImportance, editImportanceReason], () => {
  if (props.editable) {
    emit('update', {
      id: props.event.id,
      event_title: editTitle.value,
      body: editBody.value.split('\n').filter((s: string) => s.trim()),
      feeling: editFeeling.value.split('\n').filter((s: string) => s.trim()),
      reflection: editReflection.value.split('\n').filter((s: string) => s.trim()),
      user_importance: editImportance.value || null,
      user_importance_reason: editImportance.value ? editImportanceReason.value || null : null,
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
const effectiveImportance = computed(() => ({ HIGH: '高', MEDIUM: '中', LOW: '低' }[props.event.user_importance || props.event.ai_importance || ''] || ''))
</script>
