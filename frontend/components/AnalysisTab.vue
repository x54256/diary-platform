<template>
  <div class="p-4 pb-24">
    <!-- 今日心情 -->
    <div v-if="analysis?.mood" class="text-center mb-5">
      <span class="text-2xl font-bold text-neutral-800">{{ analysis.mood }}</span>
      <p class="text-xs text-neutral-400 mt-1">今日心情</p>
    </div>

    <div v-if="!hasAnyContent" class="text-center text-neutral-400 py-8">
      暂无分析数据
    </div>

    <template v-else>
      <section v-if="actionSection" class="mb-5">
        <AnalysisSection
          :analysis-run-id="analysis!.id"
          :section="actionSection"
        />
      </section>

      <div
        v-if="understandingSections.length && cognitionSections.length"
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

      <div v-if="activeGroup === 'understanding'" class="space-y-3">
        <AnalysisSection
          v-for="section in understandingSections"
          :key="section.analysis_type"
          :analysis-run-id="analysis!.id"
          :section="section"
        />
      </div>

      <div v-if="activeGroup === 'cognition'" class="space-y-3">
        <AnalysisSection
          v-for="section in cognitionSections"
          :key="section.analysis_type"
          :analysis-run-id="analysis!.id"
          :section="section"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { AnalysisRun, AnalysisSection, AnalysisType } from '~/types'

const props = defineProps<{
  analysis: AnalysisRun | null
}>()

const activeGroup = ref<'understanding' | 'cognition'>('understanding')

const sectionOrder: AnalysisType[] = [
  'EMOTION',
  'BEHAVIOR_DECISION',
  'SELF_UNDERSTANDING',
  'ACTION_SUGGESTION',
  'COGNITIVE_CALIBRATION',
  'QUESTION_ANSWER',
  'COGNITIVE_ENHANCEMENT',
]

const sortedSections = computed<AnalysisSection[]>(() => {
  const sections = props.analysis?.sections || []
  return [...sections].sort((a, b) => sectionOrder.indexOf(a.analysis_type) - sectionOrder.indexOf(b.analysis_type))
})

const actionSection = computed(() => sortedSections.value.find(section => section.analysis_type === 'ACTION_SUGGESTION') || null)
const understandingSections = computed(() => sortedSections.value.filter(section =>
  ['EMOTION', 'BEHAVIOR_DECISION', 'SELF_UNDERSTANDING'].includes(section.analysis_type)
))
const cognitionSections = computed(() => sortedSections.value.filter(section =>
  ['COGNITIVE_CALIBRATION', 'QUESTION_ANSWER', 'COGNITIVE_ENHANCEMENT'].includes(section.analysis_type)
))
const hasAnyContent = computed(() => sortedSections.value.length > 0)

watchEffect(() => {
  if (!understandingSections.value.length && cognitionSections.value.length) {
    activeGroup.value = 'cognition'
  } else if (understandingSections.value.length && !cognitionSections.value.length) {
    activeGroup.value = 'understanding'
  }
})
</script>
