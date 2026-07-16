<template>
  <div class="flex flex-col items-end gap-1 justify-self-end">
    <div class="flex items-center gap-0.5">
      <button
        v-for="star in 5"
        :key="star"
        type="button"
        class="h-8 w-8 text-xl leading-none transition-colors"
        :class="star <= currentRating ? 'text-amber-400' : 'text-neutral-300 hover:text-amber-300'"
        :disabled="saving"
        @click="selectRating(star)"
      >
        ★
      </button>
    </div>
    <button
      v-if="currentRating"
      type="button"
      class="text-xs text-neutral-400 hover:text-primary-600"
      @click="expanded = !expanded"
    >
      {{ feedbackStatusText }}
    </button>
    <span v-if="saveMessage" class="text-xs text-primary-600">{{ saveMessage }}</span>
    <span v-if="error" class="text-xs text-red-500">{{ error }}</span>
  </div>

  <div v-if="expanded" class="col-span-2 w-full rounded-md border border-neutral-200 bg-white p-3">
    <textarea
      v-model="comment"
      rows="4"
      class="min-h-28 w-full resize-y rounded border border-neutral-200 px-3 py-2 text-sm leading-relaxed text-neutral-700 outline-none focus:border-primary-400"
      placeholder="哪里不准确？希望怎么调整？"
    />
    <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
      <span class="text-xs leading-relaxed text-neutral-400">1-3 星必须填写反馈意见</span>
      <button
        type="button"
        class="min-h-9 rounded-md bg-primary-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        :disabled="saving"
        @click="submit"
      >
        {{ saving ? '保存中' : '提交' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { AnalysisFeedback, AnalysisScope, AnalysisType } from '~/types'

const props = defineProps<{
  analysisRunId: string
  scope: AnalysisScope
  eventId: string | null
  analysisType: AnalysisType
  feedback: AnalysisFeedback | null
}>()

const emit = defineEmits<{
  (e: 'saved', feedback: AnalysisFeedback): void
}>()

const { api } = useApi()
const currentRating = ref(props.feedback?.rating || 0)
const comment = ref(props.feedback?.comment || '')
const expanded = ref(false)
const saving = ref(false)
const error = ref('')
const saveMessage = ref('')
const feedbackStatusText = computed(() => props.feedback?.is_inherited ? '已修改 · 重新评分' : '已反馈 · 修改')

watch(() => props.feedback, (feedback) => {
  currentRating.value = feedback?.rating || 0
  comment.value = feedback?.comment || ''
}, { deep: true })

const saveFeedback = async () => {
  saving.value = true
  error.value = ''
  saveMessage.value = ''
  try {
    const saved = await api<AnalysisFeedback>('/diaries/analysis-feedback', {
      method: 'PUT',
      body: {
        analysis_run_id: props.analysisRunId,
        scope: props.scope,
        event_id: props.eventId,
        analysis_type: props.analysisType,
        rating: currentRating.value,
        comment: comment.value || null,
      },
    })
    emit('saved', saved)
    saveMessage.value = '已保存'
    setTimeout(() => { saveMessage.value = '' }, 1800)
    expanded.value = false
  } catch (err: any) {
    error.value = err?.data?.detail || '反馈保存失败，请重试'
  } finally {
    saving.value = false
  }
}

const selectRating = async (rating: number) => {
  currentRating.value = rating
  error.value = ''
  if (rating <= 3) {
    expanded.value = true
    return
  }
  await saveFeedback()
}

const submit = async () => {
  if (currentRating.value <= 3 && !comment.value.trim()) {
    error.value = '请填写反馈意见'
    return
  }
  await saveFeedback()
}
</script>
