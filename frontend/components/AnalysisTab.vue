<template>
  <div class="space-y-4">
    <!-- 心情醒目展示 -->
    <div v-if="analysis.mood" class="bg-primary-50 rounded-xl p-4 text-center">
      <div class="text-2xl font-semibold text-primary-700">{{ analysis.mood }}</div>
      <div class="text-xs text-primary-500 mt-1">今日心情</div>
    </div>

    <!-- 情绪分析 -->
    <AnalysisSection title="情绪分析" :content="analysis.emotion_analysis" />

    <!-- 行为与决策分析 -->
    <AnalysisSection title="行为与决策分析" :content="analysis.behavior_analysis" />

    <!-- 关注点、需求与自我理解 -->
    <AnalysisSection title="关注点、需求与自我理解" :content="analysis.focus_analysis" />

    <!-- 认知校准 -->
    <AnalysisSection title="认知校准" :content="analysis.cognitive_calibration" />

    <!-- 可行动建议 -->
    <AnalysisSection title="可行动建议" :content="analysis.actionable_suggestions" />
  </div>
</template>

<script setup lang="ts">
// 分析 Tab 内容组件

defineProps<{
  analysis: DiaryAnalysis
}>()

// 分析区块子组件（内联）
const AnalysisSection = defineComponent({
  props: {
    title: { type: String, required: true },
    content: { type: String, default: null },
  },
  setup(props) {
    return () => {
      if (!props.content) return null
      return h('div', { class: 'bg-white border border-neutral-200 rounded-lg p-4' }, [
        h('div', { class: 'text-sm font-medium text-neutral-800 mb-2' }, props.title),
        h('div', {
          class: 'text-sm text-neutral-600 leading-relaxed whitespace-pre-line',
        }, props.content),
      ])
    }
  },
})
</script>
