<template>
  <div class="border border-neutral-200 rounded-lg mb-3 overflow-hidden">
    <!-- 标题头区域 -->
    <template v-if="editable">
      <!-- 编辑模式：直接展示 -->
      <div class="px-4 pt-3">
        <input v-model="editTitle" class="w-full p-1 text-base font-semibold border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none" @click.stop />
      </div>
    </template>
    <template v-else>
      <!-- 查看模式：始终展开，不可折叠 -->
      <div class="px-4 py-3">
        <div class="text-base font-medium text-neutral-800">
            {{ event.event_title || '未命名事件' }}
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
            class="w-full max-h-56 p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-y-auto"
          />
        </template>
        <template v-else>
          <div v-if="event.body && event.body.length > 0" class="space-y-2">
            <p
              v-for="(item, idx) in event.body"
              :key="idx"
              class="text-sm text-neutral-600 leading-relaxed"
            >
              {{ item }}
            </p>
          </div>
        </template>
      </div>

      <!-- 感受 -->
      <div v-if="editable || (event.feeling && event.feeling.length > 0)" class="mt-4">
        <div class="text-[15px] font-medium text-neutral-800 mb-2">感受</div>
        <template v-if="editable">
          <textarea
            v-model="editFeeling"
            rows="3"
            class="w-full max-h-48 p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-y-auto"
          />
        </template>
        <template v-else>
          <div class="space-y-2">
            <p
              v-for="(item, idx) in event.feeling"
              :key="idx"
              class="text-sm text-neutral-600 leading-relaxed"
            >
              <template v-if="event.feeling.length > 1">{{ idx + 1 }}. </template>{{ item }}
            </p>
          </div>
        </template>
      </div>

      <!-- 反思与成长 -->
      <div v-if="editable || (event.reflection && event.reflection.length > 0)" class="mt-4">
        <div class="text-[15px] font-medium text-neutral-800 mb-2">反思与成长</div>
        <template v-if="editable">
          <textarea
            v-model="editReflection"
            rows="3"
            class="w-full max-h-48 p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-y-auto"
          />
        </template>
        <template v-else>
          <div class="space-y-2">
            <p
              v-for="(item, idx) in event.reflection"
              :key="idx"
              class="text-sm text-neutral-600 leading-relaxed"
            >
              <template v-if="event.reflection.length > 1">{{ idx + 1 }}. </template>{{ item }}
            </p>
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
          />
        </div>
      </template>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  event: any
  editable?: boolean
  analysisRunId?: string
}>()

const emit = defineEmits<{
  (e: 'update', data: any): void
}>()

const editTitle = ref('')
const editBody = ref('')
const editFeeling = ref('')
const editReflection = ref('')

// 编辑模式切换时初始化编辑值
watch(() => props.editable, (val) => {
  if (val) {
    editTitle.value = props.event.event_title || ''
    editBody.value = (props.event.body || []).join('\n')
    editFeeling.value = (props.event.feeling || []).join('\n')
    editReflection.value = (props.event.reflection || []).join('\n')
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
</script>
