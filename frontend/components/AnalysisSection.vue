<template>
  <section :class="compact ? 'mt-3' : 'rounded-lg border border-neutral-200 bg-white p-4'">
    <div class="mb-2 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2">
      <h5 :class="compact ? 'min-w-0 text-[15px] font-medium text-neutral-800' : 'min-w-0 text-base font-semibold text-neutral-800'">
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
        <div v-if="item.question" class="mb-1 text-sm font-medium text-neutral-700">
          {{ item.question }}
        </div>
        <p
          :class="compact ? 'analysis-markup text-sm text-neutral-600 leading-relaxed' : 'analysis-markup text-sm leading-relaxed text-neutral-700'"
          v-html="renderAnalysisMarkup(item.content)"
        ></p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { AnalysisFeedback as Feedback, AnalysisSection } from '~/types'
import { renderAnalysisMarkup } from '~/utils/analysis-markup'

const props = defineProps<{
  analysisRunId: string
  section: AnalysisSection
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'feedback-saved', section: AnalysisSection): void
}>()

const sortedItems = computed(() => [...props.section.items].sort((a, b) => a.sort_order - b.sort_order))

const handleSaved = (feedback: Feedback) => {
  props.section.feedback = feedback
  emit('feedback-saved', props.section)
}
</script>
