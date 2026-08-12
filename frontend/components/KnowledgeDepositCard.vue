<template>
  <section class="mb-3 rounded-xl border border-neutral-100 bg-white p-4 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h2 class="text-base font-medium text-neutral-800">知识沉淀</h2>
        <p class="mt-1 text-xs leading-5 text-neutral-500">将这篇日记拆分为可独立理解的原子事件。</p>
      </div>
      <span v-if="status?.state === 'DEPOSITED'" class="shrink-0 rounded-full bg-green-50 px-2 py-1 text-xs text-green-700">已沉淀</span>
    </div>

    <div v-if="loading && !status" class="mt-4 text-sm text-neutral-400">状态加载中...</div>
    <template v-else-if="status">
      <p v-if="status.unavailable_reason && status.state !== 'PROCESSING' && status.state !== 'DEPOSITED'" class="mt-3 text-sm text-amber-700">{{ status.unavailable_reason }}</p>
      <p v-if="status.state === 'PROCESSING'" class="mt-3 inline-flex items-center gap-2 text-sm text-primary-600">
        <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-200 border-t-primary-600" />
        正在沉淀原子事件...
      </p>
      <p v-else-if="status.state === 'FAILED'" class="mt-3 text-sm text-red-600">{{ status.task?.error_message || '知识沉淀失败' }}</p>
      <p v-else-if="status.state === 'DEPOSITED'" class="mt-3 text-sm text-neutral-500">已生成 {{ status.atomic_event_count }} 条原子事件。</p>

      <div class="mt-4">
        <NuxtLink v-if="status.state === 'DEPOSITED'" to="/knowledge" class="inline-flex h-11 items-center rounded-lg bg-primary-600 px-4 text-sm font-medium text-white">查看知识</NuxtLink>
        <button v-else-if="status.state === 'FAILED'" type="button" class="h-11 rounded-lg bg-primary-600 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="submitting || !status.available" @click="retry">{{ submitting ? '提交中...' : '重试' }}</button>
        <button v-else-if="status.state === 'NOT_DEPOSITED'" type="button" class="h-11 rounded-lg bg-primary-600 px-4 text-sm font-medium text-white disabled:opacity-50" :disabled="submitting || !status.available" @click="deposit">{{ submitting ? '提交中...' : '沉淀到知识库' }}</button>
      </div>
      <p v-if="error" class="mt-2 text-sm text-red-600">{{ error }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import type { DiaryKnowledgeStatus, KnowledgeTask } from '~/types/knowledge'

const props = defineProps<{ diaryId: string }>()
const { api } = useApi()
const status = ref<DiaryKnowledgeStatus | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
let pollTimer: ReturnType<typeof setTimeout> | null = null

const messageOf = (exception: any) => exception?.data?.detail?.message || exception?.data?.detail || '操作失败，请稍后重试'
const schedulePoll = () => {
  if (pollTimer) clearTimeout(pollTimer)
  if (status.value?.state === 'PROCESSING') pollTimer = setTimeout(load, 2000)
}
const load = async () => {
  loading.value = true
  try {
    status.value = await api<DiaryKnowledgeStatus>(`/diaries/${props.diaryId}/knowledge-status`)
    error.value = ''
  } catch (exception: any) {
    error.value = messageOf(exception)
  } finally {
    loading.value = false
    schedulePoll()
  }
}
const deposit = async () => {
  submitting.value = true
  error.value = ''
  try {
    const task = await api<KnowledgeTask>(`/diaries/${props.diaryId}/knowledge-deposit`, { method: 'POST' })
    status.value = { ...(status.value as DiaryKnowledgeStatus), state: 'PROCESSING', task }
    schedulePoll()
  } catch (exception: any) {
    error.value = messageOf(exception)
    await load()
  } finally {
    submitting.value = false
  }
}
const retry = async () => {
  if (!status.value?.task) return
  submitting.value = true
  error.value = ''
  try {
    const task = await api<KnowledgeTask>(`/knowledge-tasks/${status.value.task.id}/retry`, { method: 'POST' })
    status.value = { ...status.value, state: 'PROCESSING', task }
    schedulePoll()
  } catch (exception: any) {
    error.value = messageOf(exception)
    await load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => { if (pollTimer) clearTimeout(pollTimer) })
</script>
