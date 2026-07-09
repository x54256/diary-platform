<template>
  <div
    v-if="hasContent"
    :class="compact ? 'mb-3' : 'space-y-3'"
  >
    <h4 v-if="!compact" class="sr-only">{{ title }}</h4>

    <!-- 情绪分析（understanding） -->
    <div v-if="group === 'understanding' && data.emotion_analyses?.length" :class="sectionClass">
      <h5 :class="subTitleClass">情绪分析</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.emotion_analyses" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>

    <!-- 行为与决策分析（understanding） -->
    <div v-if="group === 'understanding' && data.behavior_decision_analyses?.length" :class="sectionClass">
      <h5 :class="subTitleClass">行为与决策分析</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.behavior_decision_analyses" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>

    <!-- 关注点与需求（understanding） -->
    <div v-if="group === 'understanding' && data.self_understanding_analyses?.length" :class="sectionClass">
      <h5 :class="subTitleClass">关注点与需求</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.self_understanding_analyses" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>

    <!-- 可行动建议（understanding） -->
    <div v-if="showActionSuggestions && group === 'understanding' && data.action_suggestions?.length" :class="sectionClass">
      <h5 :class="subTitleClass">可行动建议</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.action_suggestions" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>

    <!-- 认知校准（cognition） -->
    <div v-if="group === 'cognition' && data.cognitive_calibration_analyses?.length" :class="sectionClass">
      <h5 :class="subTitleClass">认知校准</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.cognitive_calibration_analyses" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>

    <!-- 问题解答（cognition） -->
    <div v-if="group === 'cognition' && data.question_answers?.length" :class="sectionClass">
      <h5 :class="subTitleClass">问题解答</h5>
      <QuestionAnswerCard v-for="(qa, i) in data.question_answers" :key="i" :qa="qa" :compact="compact" />
    </div>

    <!-- 认知完善（cognition） -->
    <div v-if="group === 'cognition' && data.cognitive_enhancements?.length" :class="sectionClass">
      <h5 :class="subTitleClass">认知完善</h5>
      <div :class="listClass">
        <div v-for="(item, i) in data.cognitive_enhancements" :key="i" :class="itemClass">
          <p :class="textClass">{{ item }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { EventAnalysis } from '~/types'

const props = defineProps<{
  title: string
  data: EventAnalysis
  group: 'understanding' | 'cognition'
  compact?: boolean
  showActionSuggestions?: boolean
}>()

const showActionSuggestions = computed(() => props.showActionSuggestions !== false)
const sectionClass = computed(() => props.compact ? 'mt-3' : 'rounded-lg border border-neutral-200 bg-white p-4')
const subTitleClass = computed(() => props.compact
  ? 'text-[15px] font-medium text-neutral-800 mb-1'
  : 'text-base font-semibold text-neutral-800 mb-2.5'
)
const listClass = computed(() => props.compact
  ? 'space-y-2'
  : 'space-y-2'
)
const itemClass = computed(() => props.compact
  ? ''
  : 'rounded-md bg-neutral-50 px-3 py-2.5'
)
const textClass = computed(() => props.compact
  ? 'text-sm text-neutral-600 leading-relaxed'
  : 'text-sm leading-relaxed text-neutral-700'
)

const hasContent = computed(() => {
  if (props.group === 'understanding') {
    return (props.data.emotion_analyses?.length || 0) > 0 ||
           (props.data.behavior_decision_analyses?.length || 0) > 0 ||
           (props.data.self_understanding_analyses?.length || 0) > 0 ||
           (showActionSuggestions.value && (props.data.action_suggestions?.length || 0) > 0)
  }
  return (props.data.cognitive_calibration_analyses?.length || 0) > 0 ||
         (props.data.question_answers?.length || 0) > 0 ||
         (props.data.cognitive_enhancements?.length || 0) > 0
})
</script>
