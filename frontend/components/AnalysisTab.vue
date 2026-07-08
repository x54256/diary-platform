<template>
  <div class="p-4 pb-24">
    <!-- 今日心情 -->
    <div v-if="analysis?.mood" class="text-center mb-5">
      <span class="text-2xl font-bold text-neutral-800">{{ analysis.mood }}</span>
      <p class="text-xs text-neutral-400 mt-1">今日心情</p>
    </div>

    <!-- 无分析数据提示 -->
    <div v-if="!hasAnyContent" class="text-center text-neutral-400 py-8">
      暂无分析数据
    </div>

    <template v-else>
      <!-- 可行动建议前置：直接使用现有 action_suggestions 字段 -->
      <section v-if="analysisData.action_suggestions?.length" class="mb-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-base font-semibold text-neutral-800">可行动建议</h3>
          <span class="text-xs text-neutral-400">{{ analysisData.action_suggestions.length }} 条</span>
        </div>
        <div class="space-y-2">
          <div
            v-for="(item, i) in visibleActionSuggestions"
            :key="i"
            class="rounded-lg border border-primary-100 bg-primary-50/60 px-3.5 py-3"
          >
            <div class="flex gap-2.5">
              <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-600 text-[11px] font-medium text-white">
                {{ i + 1 }}
              </span>
              <p class="text-sm leading-relaxed text-neutral-700">{{ item }}</p>
            </div>
          </div>
        </div>
        <button
          v-if="hasMoreActionSuggestions"
          type="button"
          class="mt-2 min-h-[36px] text-sm font-medium text-primary-600"
          @click="showAllActionSuggestions = !showAllActionSuggestions"
        >
          {{ showAllActionSuggestions ? '收起' : '展开全部建议' }}
        </button>
      </section>

      <!-- 分析页内分段切换 -->
      <div
        v-if="hasUnderstandingDetailContent && hasCognitionContent"
        class="sticky top-0 z-10 -mx-4 mb-4 border-y border-neutral-100 bg-white/95 px-4 py-2 backdrop-blur"
      >
        <div class="grid grid-cols-2 rounded-lg bg-neutral-100 p-1">
          <button
            type="button"
            class="min-h-[36px] rounded-md text-sm font-medium transition-colors"
            :class="activeGroup === 'understanding' ? 'bg-white text-primary-600 shadow-sm' : 'text-neutral-500'"
            @click="activeGroup = 'understanding'"
          >
            自我理解
          </button>
          <button
            type="button"
            class="min-h-[36px] rounded-md text-sm font-medium transition-colors"
            :class="activeGroup === 'cognition' ? 'bg-white text-primary-600 shadow-sm' : 'text-neutral-500'"
            @click="activeGroup = 'cognition'"
          >
            认知整理
          </button>
        </div>
      </div>

      <!-- 自我理解与行动 -->
      <AnalysisGroup
        v-if="hasUnderstandingDetailContent && activeGroup === 'understanding'"
        title="自我理解与行动"
        :data="analysisData"
        group="understanding"
        :show-action-suggestions="false"
      />

      <!-- 认知整理 -->
      <AnalysisGroup
        v-if="hasCognitionContent && activeGroup === 'cognition'"
        title="认知整理"
        :data="analysisData"
        group="cognition"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import type { DiaryAnalysis, EventAnalysis } from '~/types'

const props = defineProps<{
  analysis: DiaryAnalysis | null
}>()

const activeGroup = ref<'understanding' | 'cognition'>('understanding')
const showAllActionSuggestions = ref(false)

// 将 DiaryAnalysis 转换为 EventAnalysis 格式供 AnalysisGroup 使用
const analysisData = computed<EventAnalysis>(() => ({
  emotion_analyses: props.analysis?.emotion_analyses || [],
  behavior_decision_analyses: props.analysis?.behavior_decision_analyses || [],
  self_understanding_analyses: props.analysis?.self_understanding_analyses || [],
  action_suggestions: props.analysis?.action_suggestions || [],
  cognitive_calibration_analyses: props.analysis?.cognitive_calibration_analyses || [],
  question_answers: props.analysis?.question_answers || [],
  cognitive_enhancements: props.analysis?.cognitive_enhancements || [],
}))

const hasUnderstandingContent = computed(() => {
  const d = analysisData.value
  return (d.emotion_analyses?.length || 0) > 0 ||
         (d.behavior_decision_analyses?.length || 0) > 0 ||
         (d.self_understanding_analyses?.length || 0) > 0 ||
         (d.action_suggestions?.length || 0) > 0
})

const hasUnderstandingDetailContent = computed(() => {
  const d = analysisData.value
  return (d.emotion_analyses?.length || 0) > 0 ||
         (d.behavior_decision_analyses?.length || 0) > 0 ||
         (d.self_understanding_analyses?.length || 0) > 0
})

const hasCognitionContent = computed(() => {
  const d = analysisData.value
  return (d.cognitive_calibration_analyses?.length || 0) > 0 ||
         (d.question_answers?.length || 0) > 0 ||
         (d.cognitive_enhancements?.length || 0) > 0
})

const hasAnyContent = computed(() => hasUnderstandingContent.value || hasCognitionContent.value)

const hasMoreActionSuggestions = computed(() => analysisData.value.action_suggestions.length > 3)

const visibleActionSuggestions = computed(() => {
  const suggestions = analysisData.value.action_suggestions
  return showAllActionSuggestions.value ? suggestions : suggestions.slice(0, 3)
})

watchEffect(() => {
  if (!hasUnderstandingDetailContent.value && hasCognitionContent.value) {
    activeGroup.value = 'cognition'
  } else if (hasUnderstandingDetailContent.value && !hasCognitionContent.value) {
    activeGroup.value = 'understanding'
  }
})
</script>
