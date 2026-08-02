<template>
  <article class="rounded-3xl border border-[#e8e1d5] bg-[#fffdf8] p-5">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-neutral-800">{{ typeLabel }}<span v-if="periodLabel"> · {{ periodLabel }}</span></h3>
        <p class="mt-1 text-xs text-neutral-400">{{ triggerLabel }}</p>
      </div>
      <span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="statusClass">{{ statusLabel }}</span>
    </div>
    <div v-if="isRunning" class="mt-4">
      <div class="h-1.5 overflow-hidden rounded-full bg-neutral-100"><div class="h-full rounded-full bg-primary-500 transition-all" :style="{ width: `${progress}%` }" /></div>
      <p class="mt-2 text-sm text-neutral-600">{{ stepLabel }}</p>
    </div>
    <p v-if="task.status === 'FAILED'" class="mt-3 text-sm leading-6 text-red-600">{{ task.error_message || '本次生成没有完成，可以重试。' }}</p>
    <p v-if="task.status === 'SKIPPED_NO_DATA'" class="mt-3 text-sm leading-6 text-neutral-500">这个周期没有可用于回顾的记录。</p>
    <div v-if="task.status === 'PENDING_START' || task.status === 'FAILED' || canOpen" class="mt-3 flex justify-end gap-2">
      <button v-if="task.status === 'PENDING_START'" type="button" class="min-h-11 rounded-xl bg-primary-600 px-4 text-sm font-semibold text-white disabled:opacity-50" :disabled="starting" @click="$emit('start', task)">
        {{ starting ? '启动中…' : '开始生成' }}
      </button>
      <button v-if="task.status === 'FAILED'" type="button" class="min-h-11 rounded-xl bg-primary-50 px-4 text-sm font-semibold text-primary-700 disabled:opacity-50" :disabled="retrying" @click="$emit('retry', task)">
        {{ retrying ? '重试中…' : '重试' }}
      </button>
      <NuxtLink v-if="canOpen" :to="detailUrl" class="flex min-h-11 items-center px-3 text-sm font-medium text-primary-700">查看回顾 ›</NuxtLink>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { ReviewTask } from '~/types'

const props = withDefaults(defineProps<{ task: ReviewTask; retrying?: boolean; starting?: boolean }>(), { retrying: false, starting: false })
defineEmits<{ (event: 'retry', task: ReviewTask): void; (event: 'start', task: ReviewTask): void }>()
const isActive = computed(() => ['QUEUED', 'RUNNING'].includes(props.task.status))
const isRunning = computed(() => props.task.status === 'RUNNING')
const canOpen = computed(() => !!props.task.review_id && !!props.task.result_version_id && ['SUCCEEDED', 'COMPLETED'].includes(props.task.status))
const detailUrl = computed(() => `/review/${props.task.review_id}?version=${props.task.result_version_id}`)
const typeLabel = computed(() => props.task.review_type === 'MONTH' ? '月回顾' : props.task.review_type === 'WEEK' ? '周回顾' : '回顾任务')
const periodLabel = computed(() => {
  if (!props.task.period_start) return ''
  if (props.task.review_type === 'MONTH') return `${props.task.period_start.slice(0, 4)} 年 ${Number(props.task.period_start.slice(5, 7))} 月`
  if (!props.task.period_end) return props.task.period_start
  const short = (value: string) => `${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日`
  return `${short(props.task.period_start)}－${short(props.task.period_end)}`
})
const triggerLabel = computed(() => ({ AUTO: '到期自动创建', MANUAL: '手动创建', REGENERATE: '手动重新生成' }[props.task.trigger_type] || (props.task.generation_mode === 'ANALYSIS_ONLY' ? '更新分析和行动' : '手动创建')))
const statusLabel = computed(() => ({ PENDING: '等待处理', PENDING_START: '待启动', QUEUED: '等待处理', RUNNING: '进行中', SUCCEEDED: '已完成', COMPLETED: '已完成', FAILED: '需要处理', SKIPPED_NO_DATA: '无可用记录' }[props.task.status]))
const statusClass = computed(() => isActive.value ? 'bg-primary-50 text-primary-700' : props.task.status === 'FAILED' ? 'bg-red-50 text-red-600' : 'bg-neutral-100 text-neutral-500')
const steps = ['FREEZE_SOURCES', 'LOAD_BASE_EVENT', 'EVENT_ORGANIZE', 'ANALYSIS_ACTION', 'PERSIST_VERSION']
const progress = computed(() => {
  if (props.task.status !== 'RUNNING') return 12
  const index = steps.indexOf(props.task.current_step || '')
  return index < 0 ? 30 : Math.round(((index + 1) / steps.length) * 100)
})
const stepLabel = computed(() => ({
  FREEZE_SOURCES: '正在整理来源', EVENT_ORGANIZE: '正在梳理主要事件', LOAD_BASE_EVENT: '正在读取修改后的事件',
  ANALYSIS_ACTION: '正在形成分析与行动', PERSIST_VERSION: '正在保存',
}[props.task.current_step || ''] || (props.task.status === 'RUNNING' ? '正在生成回顾' : '等待处理')))
</script>
