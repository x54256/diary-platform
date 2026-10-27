<template>
  <section class="flex min-h-0 flex-1 flex-col bg-neutral-50" aria-label="事件要点">
    <header class="flex shrink-0 items-center justify-between border-b border-neutral-200 bg-white px-4 py-2">
      <p class="text-xs text-neutral-500">本篇日记 · {{ events.length }} 个事件 · {{ pointCount }} 条要点</p>
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
            <section v-if="eventRelations(event.event_id).length" class="mt-5 border-t border-neutral-100 pt-4" :aria-label="`${event.title}的连接关系`">
              <h3 class="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-700">
                <span class="h-1.5 w-1.5 rounded-full bg-primary-500" aria-hidden="true" />
                关联事件 <span class="text-xs font-normal text-neutral-400">{{ eventRelations(event.event_id).length }}</span>
              </h3>
              <article v-for="relation in eventRelations(event.event_id)" :key="relation.id" class="mb-2 rounded-xl border border-neutral-200 bg-neutral-50/70 p-3 last:mb-0">
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                    <span class="shrink-0 text-sm font-medium text-primary-700" aria-hidden="true">{{ relation.source_event_id === event.event_id ? '→' : '←' }}</span>
                    <span class="shrink-0 rounded-full bg-primary-100 px-2 py-0.5 text-xs font-medium text-primary-800">{{ relation.relation_type.replace('事件', '') }}</span>
                    <span v-if="relation.certainty === 'SPECULATIVE'" class="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">推测</span>
                    <span class="min-w-0 break-words text-sm font-medium leading-5 text-neutral-800">{{ relatedEvent(relation, event.event_id)?.title || '关联事件' }}</span>
                    <span v-if="relatedEvent(relation, event.event_id)?.diary_date" class="shrink-0 text-xs text-neutral-400">{{ relatedEvent(relation, event.event_id)?.diary_date }}</span>
                  </div>
                  <div>
                    <p v-if="relation.description" class="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-neutral-600">{{ relation.description }}</p>
                    <details class="group mt-2 border-t border-neutral-200 pt-2">
                      <summary class="min-h-8 cursor-pointer list-none text-xs font-medium text-primary-700 marker:hidden">
                        <span>查看关系依据 · {{ relationEvidenceCount(relation) }} 条</span><span class="ml-1 inline-block transition-transform group-open:rotate-90" aria-hidden="true">›</span>
                      </summary>
                      <div class="space-y-3 pb-1 pt-2">
                        <section v-for="side in relationEvidenceSides(relation)" :key="side.key">
                          <h4 class="mb-1.5 text-xs font-semibold leading-relaxed text-neutral-500">{{ side.label }}要点 · {{ side.event?.title || '关联事件' }}</h4>
                          <div v-if="side.points.length" class="space-y-2">
                            <div v-for="point in side.points" :key="point.id" class="rounded-xl border border-neutral-200 bg-white px-3 py-3">
                              <p class="text-sm leading-relaxed text-neutral-700"><strong class="font-semibold text-neutral-800">{{ point.no }}. </strong>{{ point.summary }}</p>
                            </div>
                          </div>
                          <p v-else class="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-400">暂无对应要点</p>
                        </section>
                      </div>
                    </details>
                  </div>
                </div>
              </article>
            </section>
          </div>
        </article>
      </div>
      <p v-if="error && events.length" role="alert" class="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{{ error }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { DiaryGraphResult, GraphEvent, GraphRelation } from '~/types/graph'

const props = defineProps<{ diaryId: string; visible: boolean; revision: number }>()
const emit = defineEmits<{ (event: 'source', id: string, diaryId: string): void }>()
const { api } = useApi()
const events = ref<GraphEvent[]>([])
const graphEvents = ref<GraphEvent[]>([])
const relations = ref<GraphRelation[]>([])
const loading = ref(false)
const error = ref('')
const content = ref<HTMLElement | null>(null)
const pointCount = computed(() => events.value.reduce((count, event) => count + event.points.length, 0))
const eventRelations = (eventId: string) => relations.value.filter(relation => relation.source_event_id === eventId || relation.target_event_id === eventId)
const eventById = (eventId: string) => graphEvents.value.find(event => event.event_id === eventId)
const relatedEvent = (relation: GraphRelation, eventId: string) => eventById(relation.source_event_id === eventId ? relation.target_event_id : relation.source_event_id)
const relationEvidenceSides = (relation: GraphRelation) => {
  const source = eventById(relation.source_event_id)
  const target = eventById(relation.target_event_id)
  const sourceIds = new Set(relation.source_points.map(point => point.point_id))
  const targetIds = new Set(relation.target_points.map(point => point.point_id))
  return [
    { key: 'source', label: '源事件', event: source, points: source?.points.filter(point => sourceIds.has(point.id)) || [] },
    { key: 'target', label: '目标事件', event: target, points: target?.points.filter(point => targetIds.has(point.id)) || [] },
  ]
}
const relationEvidenceCount = (relation: GraphRelation) => relation.source_points.length + relation.target_points.length
let loaded = false
let generation = 0

const load = async () => {
  const token = ++generation
  loading.value = true
  error.value = ''
  try {
    const data = await api<DiaryGraphResult>(`/graph/diaries/${props.diaryId}`)
    if (token !== generation) return
    graphEvents.value = data.events
    events.value = data.events.filter(event => event.diary_id === props.diaryId)
    relations.value = data.relations
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
  graphEvents.value = []
  relations.value = []
  loading.value = false
  error.value = ''
  if (content.value) content.value.scrollTop = 0
  if (props.visible) load()
})
watch(() => props.visible, visible => { if (visible && !loaded && !loading.value) load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
