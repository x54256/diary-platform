<template>
  <section :class="compact ? 'mt-3' : 'rounded-lg border border-neutral-200 bg-white p-4'">
    <div class="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2">
      <h5 class="min-w-0 text-[17px] font-semibold text-neutral-800">
        {{ section.title }}
      </h5>
      <AnalysisFeedback
        :analysis-run-id="analysisRunId"
        :scope="section.scope"
        :event-id="section.event_id"
        :analysis-type="section.analysis_type"
        :feedback="section.feedback"
        @saved="handleSaved"
      />
    </div>

    <div :class="compact ? 'space-y-2' : 'space-y-2'">
      <div
        v-for="item in sortedItems"
        :key="item.id"
        :class="compact ? '' : 'rounded-md bg-neutral-50 px-3 py-2.5'"
      >
        <div v-if="item.question" class="mb-1 text-base font-medium text-neutral-700">
          {{ item.question }}
        </div>
        <DiaryAnnotationText
          :paragraphs="[item.content]"
          target-type="ANALYSIS_ITEM"
          :analysis-item-id="item.id"
          :annotations="annotations"
          :paragraph-class="compact ? 'analysis-markup text-base text-neutral-600 leading-relaxed' : 'analysis-markup text-base leading-relaxed text-neutral-700'"
          @select="emit('annotation-select', $event)"
          @annotation-clicked="emit('annotation-clicked', $event)"
        />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { AnalysisFeedback as Feedback, AnalysisSection, DiaryAnnotation, DiaryAnnotationClick, DiaryAnnotationSelection } from '~/types'

const props = defineProps<{
  analysisRunId: string
  section: AnalysisSection
  compact?: boolean
  annotations?: DiaryAnnotation[]
}>()

const emit = defineEmits<{
  (e: 'feedback-saved', section: AnalysisSection): void
  (e: 'annotation-select', selection: DiaryAnnotationSelection): void
  (e: 'annotation-clicked', payload: DiaryAnnotationClick): void
}>()

const annotations = computed(() => props.annotations || [])

const sortedItems = computed(() => [...props.section.items].sort((a, b) => a.sort_order - b.sort_order))

const handleSaved = (feedback: Feedback) => {
  props.section.feedback = feedback
  emit('feedback-saved', props.section)
}
</script>
