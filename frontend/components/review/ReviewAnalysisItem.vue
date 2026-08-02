<template>
  <article class="rounded-2xl border border-[#ebe6ed] bg-[#faf9fb] px-4 py-4">
    <div class="flex items-start justify-between gap-3">
      <h4 class="text-sm font-semibold text-neutral-800">{{ angleLabel }}</h4>
      <span v-if="savedMessage" class="shrink-0 text-xs text-emerald-600">{{ savedMessage }}</span>
    </div>
    <p class="mt-2 text-[15px] leading-7 text-neutral-700">{{ item.claim }}</p>
    <div class="mt-2 flex items-center justify-between gap-2">
      <button type="button" class="min-h-11 text-sm text-neutral-500" @click="$emit('sources', sourceIds, angleLabel)">查看依据</button>
      <div class="flex" :aria-label="`对${angleLabel}评分`">
        <button
          v-for="star in 5"
          :key="star"
          type="button"
          class="flex h-11 w-11 items-center justify-center text-xl disabled:opacity-50"
          :class="star <= rating ? 'text-amber-400' : 'text-neutral-300'"
          :disabled="saving"
          :aria-label="`${star} 星`"
          @click="selectRating(star)"
        >★</button>
      </div>
    </div>
    <p v-if="feedback?.is_inherited" class="text-xs text-amber-700">来自上一版本，请重新确认</p>
    <div v-if="expanded" class="mt-3 rounded-xl border border-[#e8e1d5] bg-white p-3">
      <textarea
        v-model="comment"
        rows="3"
        class="w-full resize-y rounded-lg border border-neutral-200 px-3 py-2 text-base leading-6 focus:border-primary-400"
        placeholder="哪里不准确？希望怎么调整？"
      />
      <div class="mt-2 flex items-center justify-between gap-3">
        <span class="text-xs text-neutral-400">1～3 星需要说明原因</span>
        <button type="button" class="min-h-11 rounded-lg bg-primary-600 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '提交' }}
        </button>
      </div>
    </div>
    <button v-else-if="rating >= 4" type="button" class="min-h-11 text-xs text-neutral-400" @click="expanded = true">补充反馈</button>
    <p v-if="error" class="mt-2 text-sm text-red-600">{{ error }}</p>
  </article>
</template>

<script setup lang="ts">
import type { ReviewAnalysisItemData, ReviewFeedback } from '~/types'

const props = defineProps<{ versionId: string; item: ReviewAnalysisItemData; feedback?: ReviewFeedback | null }>()
const emit = defineEmits<{
  (event: 'saved', feedback: ReviewFeedback): void
  (event: 'sources', ids: string[], title: string): void
}>()
const { api } = useApi()
const rating = ref(props.feedback?.rating || 0)
const comment = ref(props.feedback?.comment || '')
const expanded = ref(false)
const saving = ref(false)
const error = ref('')
const savedMessage = ref('')
const itemId = computed(() => props.item.analysis_item_id || props.item.id || props.item.analysis_key)
const sourceIds = computed(() => [...new Set([
  ...(props.item.supporting_source_ids || []),
  ...(props.item.counterevidence_source_ids || []),
  ...(props.item.context_source_ids || []),
])])

watch(() => props.feedback, value => {
  rating.value = value?.rating || 0
  comment.value = value?.comment || ''
}, { deep: true })

const labels: Record<string, string> = {
  EMOTION_REGULATION: '情绪与调节',
  BEHAVIOR_EXECUTION: '行为与执行',
  DECISION_PROBLEM_SOLVING: '决策与问题解决',
  ATTENTION_MOTIVATION_VALUES: '关注、动机与价值',
  COGNITION_LEARNING: '认知与学习',
  CAPABILITY_GROWTH: '能力与成长',
  RELATIONSHIP_SOCIAL_PSYCHOLOGY: '关系与社会心理',
}
const angleLabel = computed(() => labels[props.item.angle_code] || props.item.angle_code)

const selectRating = async (value: number) => {
  rating.value = value
  error.value = ''
  if (value <= 3) {
    expanded.value = true
    return
  }
  await save()
}
const save = async () => {
  if (rating.value <= 3 && !comment.value.trim()) {
    error.value = '请说明哪里不准确'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const response = await api<ReviewFeedback>(`/review-versions/${props.versionId}/feedback/${itemId.value}`, {
      method: 'PUT',
      body: { rating: rating.value, comment: comment.value.trim() || null },
    })
    const saved = response || { analysis_item_id: itemId.value, rating: rating.value, comment: comment.value.trim() || null }
    emit('saved', saved)
    expanded.value = false
    savedMessage.value = '已保存'
    window.setTimeout(() => { savedMessage.value = '' }, 1800)
  } catch (cause: any) {
    error.value = cause?.data?.detail || '反馈保存失败，请重试'
  } finally {
    saving.value = false
  }
}
</script>
