<template>
  <section class="voice-panel">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-neutral-800">语音记录</h2>
        <p class="mt-0.5 text-xs text-neutral-400">首个录音上传成功后即创建日记</p>
      </div>
      <label v-if="!locked" class="voice-add">
        <input type="file" multiple accept="audio/*,video/*,.aac,.amr,.avi,.flac,.flv,.m4a,.mkv,.mov,.mp3,.mp4,.mpeg,.ogg,.opus,.wav,.webm,.wma,.wmv" class="hidden" @change="selectFiles" />
        <span class="text-lg leading-none">＋</span> 添加语音
      </label>
    </div>

    <div v-if="items.length" class="mt-3 max-h-64 space-y-2 overflow-y-auto pr-0.5">
      <article
        v-for="(item, index) in items"
        :key="item.id"
        class="voice-item"
        :class="[`voice-item--${item.status.toLowerCase()}`, { 'voice-item--dragging': draggingId === item.id }]"
        :draggable="canReorder"
        @dragstart="startDrag(item.id)"
        @dragover.prevent
        @drop="dropOn(item.id)"
        @dragend="draggingId = null"
      >
        <div class="flex min-w-0 items-start gap-3">
          <div class="voice-icon">{{ item.status === 'FAILED' ? '!' : '♪' }}</div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <p class="truncate text-sm font-medium text-neutral-700">{{ item.filename }}</p>
              <span class="shrink-0 text-xs" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
            </div>
            <div v-if="canReorder" class="mt-1 flex items-center gap-2 text-xs text-neutral-400">
              <span class="voice-drag-hint">拖拽排序</span>
              <button class="voice-order-action" :disabled="index === 0" @click="move(item.id, -1)">上移</button>
              <button class="voice-order-action" :disabled="index === items.length - 1" @click="move(item.id, 1)">下移</button>
            </div>
            <p class="mt-0.5 text-xs text-neutral-400">{{ formatSize(item.file_size) }}</p>
            <div v-if="item.status === 'UPLOADING'" class="mt-2 h-1 overflow-hidden rounded-full bg-neutral-100">
              <div class="h-full rounded-full bg-amber-500 transition-all" :style="{ width: `${item.progress || 0}%` }" />
            </div>
            <p v-if="item.error_message" class="mt-1.5 text-xs text-red-600">{{ item.error_message }}</p>
            <p v-if="item.transcript_preview" class="mt-2 line-clamp-3 rounded-md bg-white/70 px-2 py-1.5 text-xs leading-5 text-neutral-600">{{ item.transcript_preview }}</p>
          </div>
        </div>
        <div v-if="item.status === 'FAILED' || item.status === 'UPLOADED'" class="mt-2 flex justify-end gap-3 border-t border-neutral-100 pt-2">
          <button v-if="item.status === 'FAILED' && !item.local" class="voice-action" @click="$emit('retry', item)">重试</button>
          <button class="voice-action text-red-500" @click="$emit('remove', item)">删除</button>
        </div>
      </article>
    </div>

    <div v-if="batch?.status === 'PARTIAL_FAILED'" class="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5">
      <p class="text-xs font-medium text-red-700">存在识别失败的录音，尚未创建日记</p>
      <p class="mt-1 text-xs text-red-500">成功文本不会提前写入正文，失败录音保留 7 天。</p>
      <div class="mt-2 flex gap-2">
        <button class="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white" @click="$emit('retry-all')">重试失败项</button>
        <button class="rounded-md border border-red-200 bg-white px-3 py-1.5 text-xs text-red-600" @click="$emit('cancel')">取消整批</button>
      </div>
    </div>

    <button v-if="canStart" class="mt-3 w-full rounded-lg bg-neutral-900 py-2.5 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:opacity-50" :disabled="busy" @click="$emit('start')">
      {{ busy ? '正在启动...' : `开始转写（${items.length}）` }}
    </button>
    <button v-else-if="locked && batch?.status !== 'PARTIAL_FAILED'" class="mt-3 w-full rounded-lg bg-amber-50 py-2.5 text-sm font-medium text-amber-700" disabled>
      {{ batch?.status === 'FINALIZING' ? '正在保存日记...' : '正在后台识别录音...' }}
    </button>
  </section>
</template>

<script setup lang="ts">
import type { TranscriptionBatch, TranscriptionItem, TranscriptionItemStatus } from '~/types'

const props = defineProps<{ items: TranscriptionItem[]; batch: TranscriptionBatch | null; canStart: boolean; locked: boolean; busy: boolean }>()
const emit = defineEmits<{
  add: [files: File[]]; remove: [item: TranscriptionItem]; retry: [item: TranscriptionItem]
  reorder: [itemIds: string[]]; 'retry-all': []; cancel: []; start: []
}>()

const draggingId = ref<string | null>(null)
const canReorder = computed(() => props.batch?.status === 'COLLECTING' && props.items.every(item => !item.local))

const reorder = (fromId: string, toId: string) => {
  const from = props.items.findIndex(item => item.id === fromId)
  const to = props.items.findIndex(item => item.id === toId)
  if (!canReorder.value || from < 0 || to < 0 || from === to) return
  const ordered = [...props.items]
  const [item] = ordered.splice(from, 1)
  ordered.splice(to, 0, item)
  emit('reorder', ordered.map(value => value.id))
}

const startDrag = (itemId: string) => {
  if (canReorder.value) draggingId.value = itemId
}
const dropOn = (itemId: string) => {
  if (draggingId.value) reorder(draggingId.value, itemId)
  draggingId.value = null
}
const move = (itemId: string, direction: number) => {
  const index = props.items.findIndex(item => item.id === itemId)
  const target = index + direction
  if (target >= 0 && target < props.items.length) reorder(itemId, props.items[target].id)
}

const selectFiles = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files?.length) emit('add', Array.from(input.files))
  input.value = ''
}
const formatSize = (size: number) => size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`
const statusText = (status: TranscriptionItemStatus) => ({
  UPLOADING: '上传中', UPLOADED: '待开始', QUEUED: '排队中', SUBMITTING: '提交中',
  SUBMITTED: '已提交', RUNNING: '识别中', SUCCEEDED: '已完成', FAILED: '失败', DELETED: '已删除',
}[status])
const statusClass = (status: TranscriptionItemStatus) => status === 'FAILED' ? 'text-red-600' : status === 'SUCCEEDED' ? 'text-emerald-600' : 'text-amber-600'
</script>

<style scoped>
.voice-panel { @apply mx-4 mb-3 rounded-xl border border-neutral-200 bg-white p-3 shadow-sm; }
.voice-add { @apply flex cursor-pointer items-center gap-1 rounded-lg border border-neutral-200 bg-neutral-50 px-2.5 py-1.5 text-xs font-medium text-neutral-700 transition hover:border-amber-300 hover:bg-amber-50; }
.voice-item { @apply rounded-lg border border-neutral-100 bg-neutral-50/80 p-2.5; }
.voice-item--failed { @apply border-red-100 bg-red-50/60; }
.voice-item--succeeded { @apply border-emerald-100 bg-emerald-50/50; }
.voice-item--dragging { @apply opacity-50 ring-2 ring-amber-300; }
.voice-icon { @apply flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-100 text-sm font-semibold text-amber-700; }
.voice-item--failed .voice-icon { @apply bg-red-100 text-red-600; }
.voice-item--succeeded .voice-icon { @apply bg-emerald-100 text-emerald-600; }
.voice-action { @apply text-xs font-medium text-neutral-600; }
.voice-order-action { @apply text-neutral-500 underline decoration-dotted underline-offset-2 disabled:cursor-not-allowed disabled:opacity-30; }
.voice-drag-hint { @apply cursor-grab; }
</style>
