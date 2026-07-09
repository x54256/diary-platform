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
            class="w-full p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="autoResize"
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
            class="w-full p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="autoResize"
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
            class="w-full p-2 text-sm border border-neutral-300 rounded focus:ring-2 focus:ring-primary-500 outline-none resize-none overflow-hidden"
            @input="autoResize"
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
          <AnalysisGroup
            v-if="hasUnderstanding"
            title="自我理解与行动"
            :data="event.analysis"
            group="understanding"
            compact
            :show-action-suggestions="false"
          />
          <div
            v-if="event.analysis.action_suggestions?.length"
            class="mt-3"
          >
            <div class="text-[15px] font-medium text-neutral-800 mb-1">可行动建议</div>
            <div class="space-y-2">
              <div
                v-for="(item, idx) in event.analysis.action_suggestions"
                :key="idx"
                class="text-sm text-neutral-600 leading-relaxed"
              >
                {{ item }}
              </div>
            </div>
          </div>
          <AnalysisGroup
            v-if="hasCognition"
            title="认知整理"
            :data="event.analysis"
            group="cognition"
            compact
          />
        </div>
      </template>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps<{
  event: any
  editable?: boolean
}>()

const emit = defineEmits<{
  (e: 'update', data: any): void
}>()

const editTitle = ref('')
const editBody = ref('')
const editFeeling = ref('')
const editReflection = ref('')

const autoResize = (e: Event) => {
  const target = e.target as HTMLTextAreaElement
  target.style.height = 'auto'
  target.style.height = target.scrollHeight + 'px'
}

// 编辑模式切换时初始化编辑值和 textarea 高度
watch(() => props.editable, (val) => {
  if (val) {
    editTitle.value = props.event.event_title || ''
    editBody.value = (props.event.body || []).join('\n')
    editFeeling.value = (props.event.feeling || []).join('\n')
    editReflection.value = (props.event.reflection || []).join('\n')
    nextTick(() => {
      document.querySelectorAll('textarea').forEach(el => {
        el.style.height = 'auto'
        el.style.height = el.scrollHeight + 'px'
      })
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

// 事件级分析内容判断
const hasUnderstanding = computed(() => {
  const a = props.event.analysis
  if (!a) return false
  return (a.emotion_analyses?.length || 0) > 0 ||
         (a.behavior_decision_analyses?.length || 0) > 0 ||
         (a.self_understanding_analyses?.length || 0) > 0 ||
         (a.action_suggestions?.length || 0) > 0
})

const hasCognition = computed(() => {
  const a = props.event.analysis
  if (!a) return false
  return (a.cognitive_calibration_analyses?.length || 0) > 0 ||
         (a.question_answers?.length || 0) > 0 ||
         (a.cognitive_enhancements?.length || 0) > 0
})

const hasEventAnalysis = computed(() => hasUnderstanding.value || hasCognition.value)
</script>
