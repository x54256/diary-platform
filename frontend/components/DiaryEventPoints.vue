<template>
  <section class="flex min-h-0 flex-1 flex-col bg-neutral-50" aria-label="事件要点">
    <header class="flex shrink-0 items-center justify-between border-b border-neutral-200 bg-white px-4 py-2">
      <p class="text-xs text-neutral-500">本篇日记 · {{ events.length }} 个事件 · {{ pointCount }} 条要点</p>
      <button type="button" class="min-h-11 px-2 text-sm text-primary-600 disabled:opacity-50" :disabled="loading" @click="load">刷新</button>
    </header>
    <div ref="content" class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3 pb-8">
      <p v-if="loading && !events.length" class="py-12 text-center text-sm text-neutral-400" role="status">正在读取要点…</p>
      <div v-else-if="error && !events.length" class="py-12 text-center text-sm">
        <p role="alert" class="text-red-700">{{ error }}</p>
        <button type="button" class="mt-3 min-h-11 text-primary-600" @click="load">重新加载</button>
      </div>
      <p v-else-if="!events.length" class="py-12 text-center text-sm text-neutral-400">本篇日记暂无已保存的事件要点</p>
      <div v-else>
        <article v-for="event in events" :key="`${event.run_id}:${event.event_id}`" class="mb-3 rounded-lg border border-neutral-200 bg-white">
          <header class="border-b border-neutral-100 px-4 py-3">
            <div class="flex items-start justify-between gap-3">
              <h2 class="min-w-0 flex-1 break-words text-base font-medium text-neutral-800">{{ event.title || '未命名事件' }}</h2>
              <button type="button" class="-my-2 min-h-11 shrink-0 text-sm text-primary-600" @click="emit('source', event.event_id, event.diary_id)">查看原事件</button>
            </div>
            <p class="mt-1 text-xs text-neutral-400">{{ event.diary_date }} · {{ event.points.length }} 条要点</p>
          </header>
          <div class="px-4 py-3">
            <ol class="space-y-3">
              <li v-for="point in event.points" :key="point.id" class="whitespace-pre-wrap break-words text-base leading-relaxed text-neutral-800"><strong class="font-semibold">{{ point.no }}. {{ point.summary }}：</strong>{{ point.detail }}</li>
            </ol>
          </div>
        </article>
      </div>
      <p v-if="error && events.length" role="alert" class="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{{ error }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { DiaryGraphResult, GraphEvent } from '~/types/graph'

const props = defineProps<{ diaryId: string; visible: boolean; revision: number }>()
const emit = defineEmits<{ (event: 'source', id: string, diaryId: string): void }>()
const { api } = useApi()
const events = ref<GraphEvent[]>([])
const loading = ref(false)
const error = ref('')
const content = ref<HTMLElement | null>(null)
const pointCount = computed(() => events.value.reduce((count, event) => count + event.points.length, 0))
let loaded = false
let generation = 0

const load = async () => {
  const token = ++generation
  loading.value = true
  error.value = ''
  try {
    const data = await api<DiaryGraphResult>(`/graph/diaries/${props.diaryId}`)
    if (token !== generation) return
    events.value = data.events.filter(event => event.diary_id === props.diaryId)
    loaded = true
  } catch {
    if (token === generation) error.value = '要点加载失败，请重试'
  } finally {
    if (token === generation) loading.value = false
  }
}

watch(() => [props.diaryId, props.revision], () => {
  generation++
  loaded = false
  events.value = []
  loading.value = false
  error.value = ''
  if (content.value) content.value.scrollTop = 0
  if (props.visible) load()
})
watch(() => props.visible, visible => { if (visible && !loaded && !loading.value) load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
