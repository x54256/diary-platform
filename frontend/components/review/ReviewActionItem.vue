<template>
  <article v-if="action.status !== 'IGNORED' || showIgnored" class="rounded-lg border border-neutral-200 bg-white p-4">
    <div class="flex items-start gap-3">
      <span class="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 text-[10px]" :class="action.status === 'CONFIRMED' ? 'border-emerald-500 bg-emerald-500 text-white' : 'border-primary-300'">
        {{ action.status === 'CONFIRMED' ? '●' : '' }}
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium leading-6 text-neutral-800">{{ visibleContent }}</p>
        <p v-if="action.rationale" class="mt-1 text-xs leading-5 text-neutral-500">依据：{{ action.rationale }}</p>
        <p v-if="action.verification_rule?.success_condition" class="mt-1 text-xs leading-5 text-neutral-500">下期可检查：{{ action.verification_rule.success_condition }}</p>
        <span v-if="action.status === 'CONFIRMED'" class="mt-2 inline-block text-xs font-medium text-emerald-600">已确认</span>
        <span v-if="action.status === 'IGNORED'" class="mt-2 inline-block text-xs text-neutral-400">已忽略</span>
      </div>
    </div>
    <div class="mt-3 flex flex-wrap items-center gap-2 pl-8">
      <button v-if="action.status === 'CANDIDATE'" type="button" class="min-h-11 rounded-lg bg-primary-600 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="saving" @click="update({ status: 'CONFIRMED' })">确认</button>
      <button v-if="action.status !== 'IGNORED'" type="button" class="min-h-11 px-3 text-sm text-neutral-500" :disabled="saving" @click="startEdit">编辑</button>
      <button v-if="action.status === 'CANDIDATE'" type="button" class="min-h-11 px-3 text-sm text-neutral-500" :disabled="saving" @click="update({ status: 'IGNORED' })">忽略</button>
      <button v-if="action.status === 'CONFIRMED'" type="button" class="min-h-11 px-3 text-sm text-neutral-500" :disabled="saving" @click="cancelConfirm">取消确认</button>
      <button v-if="action.status === 'IGNORED'" type="button" class="min-h-11 px-3 text-sm text-primary-600" :disabled="saving" @click="update({ status: 'CANDIDATE' })">撤销忽略</button>
      <button v-if="action.basis_source_ids?.length" type="button" class="min-h-11 px-3 text-sm text-neutral-500" @click="$emit('sources', action.basis_source_ids, '行动依据')">查看依据</button>
    </div>
    <p v-if="error" class="mt-2 text-sm text-red-600">{{ error }}</p>
  </article>
  <Teleport to="body">
    <div v-if="editing" class="fixed inset-0 z-[90] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="编辑行动" @click.self="cancelEdit" @keydown.esc="cancelEdit">
      <section class="w-full max-w-md rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
        <h2 class="font-medium text-neutral-900">编辑行动</h2>
        <textarea v-model="draft" autofocus rows="4" class="mt-4 w-full resize-y rounded-lg border border-neutral-200 p-3 text-base leading-6 focus:border-primary-400" />
        <p v-if="error" class="mt-2 text-sm text-red-600">{{ error }}</p>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <button type="button" class="min-h-12 rounded-lg border border-neutral-300 text-sm text-neutral-700" @click="cancelEdit">取消</button>
          <button type="button" class="min-h-12 rounded-lg bg-primary-600 text-sm font-medium text-white disabled:opacity-50" :disabled="!draft.trim() || saving" @click="update({ edited_content: draft.trim() })">保存</button>
        </div>
      </section>
    </div>
  </Teleport>
  <Teleport to="body">
    <div v-if="cancelConfirmOpen" class="fixed inset-0 z-[90] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="取消确认行动" @click.self="cancelConfirmOpen = false" @keydown.esc="cancelConfirmOpen = false">
      <section class="w-full max-w-md rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
        <h2 class="font-medium text-neutral-900">取消确认这项行动？</h2>
        <p class="mt-2 text-sm leading-6 text-neutral-600">取消后，下一同级周期将不再自动核查这项行动。</p>
        <div class="mt-4 grid grid-cols-2 gap-3">
          <button type="button" autofocus class="min-h-12 rounded-lg border border-neutral-300 text-sm text-neutral-700" @click="cancelConfirmOpen = false">保留确认</button>
          <button type="button" class="min-h-12 rounded-lg bg-primary-600 text-sm font-medium text-white" @click="confirmCancellation">取消确认</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { ReviewAction, ReviewActionStatus } from '~/types'

const props = withDefaults(defineProps<{ versionId: string; action: ReviewAction; showIgnored?: boolean }>(), { showIgnored: false })
const emit = defineEmits<{
  (event: 'updated', action: ReviewAction): void
  (event: 'sources', ids: string[], title: string): void
  (event: 'ignored', action: ReviewAction): void
}>()
const { api } = useApi()
const saving = ref(false)
const editing = ref(false)
const draft = ref('')
const error = ref('')
const cancelConfirmOpen = ref(false)
const visibleContent = computed(() => props.action.edited_content || props.action.content)
const startEdit = () => { draft.value = visibleContent.value; editing.value = true }
const cancelEdit = () => { editing.value = false; draft.value = '' }

const update = async (body: { status?: ReviewActionStatus; edited_content?: string }) => {
  saving.value = true
  error.value = ''
  try {
    const response = await api<ReviewAction>(`/review-versions/${props.versionId}/actions/${props.action.id}`, { method: 'PATCH', body })
    const saved = response || ({ ...props.action, ...body } as ReviewAction)
    emit('updated', saved)
    if (body.status === 'IGNORED') emit('ignored', saved)
    editing.value = false
  } catch (cause: any) {
    error.value = cause?.data?.detail || '行动更新失败，请重试'
  } finally {
    saving.value = false
  }
}
const cancelConfirm = () => {
  cancelConfirmOpen.value = true
}
const confirmCancellation = () => { cancelConfirmOpen.value = false; void update({ status: 'CANDIDATE' }) }
</script>
