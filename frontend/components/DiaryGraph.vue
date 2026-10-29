<template>
  <div class="graph-shell relative flex min-h-0 flex-1 flex-col overflow-hidden">
    <div class="graph-toolbar shrink-0 border-b px-4 py-1.5">
      <div class="flex items-center gap-2">
        <p class="text-xs text-neutral-500">{{ focusId ? '聚焦事件' : '本篇日记' }} · {{ visibleEvents.length }} 个节点 · {{ visibleRelations.length }} 条关系</p>
        <button v-if="selectedEvent" type="button" class="hidden min-h-11 px-2 text-sm text-primary-700 lg:inline-flex lg:items-center" :disabled="expanding" @click="expandNeighbors">{{ expanding ? '正在展开…' : '展开关联' }}</button>
        <button v-if="manualPositionIds.size" type="button" class="ml-auto min-h-11 px-2 text-sm text-primary-700" @click="resetPositions">恢复默认位置</button>
      </div>
      <div v-if="availableRelationTypes.length" class="flex flex-wrap items-center gap-1" role="group" aria-label="关系筛选">
        <button v-for="type in availableRelationTypes" :key="type" type="button" class="min-h-8 rounded-full border px-2 text-[11px] transition-colors"
          :class="hiddenTypes.includes(type) ? 'border-neutral-200 text-neutral-400' : 'border-primary-200 bg-primary-50 text-primary-800'"
          :aria-pressed="!hiddenTypes.includes(type)" @click="toggleType(type)"><span class="mr-1 inline-block h-2 w-2 rounded-full align-middle" :style="{ backgroundColor: relationColorForType(type) }" />{{ type.replace('事件', '') }} {{ scopedRelations.filter(edge => edge.relation_type === type).length }}</button>
        <button v-if="focusId" type="button" class="min-h-11 px-2 text-sm text-primary-600" @click="restoreGraph">返回原图</button>
      </div>
    </div>
    <div v-if="loading && !events.length" class="flex flex-1 items-center justify-center text-sm text-neutral-500">正在读取图谱…</div>
    <div v-else-if="error && !events.length" class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-sm">
      <p role="alert">{{ error }}</p><button class="min-h-11 text-primary-600" @click="load()">重新加载</button>
    </div>
    <div v-else-if="!events.length" class="flex flex-1 items-center justify-center p-6 text-sm text-neutral-500">暂无可展示的图谱，可切回列表阅读日记</div>
    <template v-else>
      <div class="relative flex min-h-0 flex-1 flex-col">
      <div class="relative min-h-0 min-w-0 flex-1">
      <div ref="viewport" class="graph-canvas relative h-full min-h-0 touch-none overflow-hidden" aria-label="事件关系图谱"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @click.capture="guardDragClick" @click="clearSelectionOnCanvas" @wheel.prevent="wheelZoom">
        <p v-if="relations.length && !visibleRelations.length" class="pointer-events-none absolute bottom-4 left-3 right-16 z-10 text-xs text-neutral-500">当前筛选下暂无关系，可点击上方类型恢复</p>
        <div class="absolute left-0 top-0 origin-top-left" :style="{ transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})` }">
          <svg class="pointer-events-none absolute overflow-visible" width="1" height="1">
            <defs>
              <marker v-for="type in relationTypes" :id="markerIdForType(type)" :key="type" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" :fill="relationColorForType(type)" /></marker>
            </defs>
            <g v-for="edge in drawnEdges" :key="edge.relation.id">
              <path :d="edge.path" fill="none" :stroke="relationColor(edge.relation)"
                :stroke-width="selectedRelation?.id === edge.relation.id ? 3.5 : isRelated(edge.relation) ? 2.8 : 2.2"
                :opacity="selectedRelation ? (selectedRelation.id === edge.relation.id ? 1 : .12) : selectedEventId ? (isRelated(edge.relation) ? .98 : .14) : .92"
                :stroke-dasharray="edge.relation.certainty === 'SPECULATIVE' ? '6 4' : undefined"
                :marker-end="`url(#${markerIdForType(edge.relation.relation_type)})`" />
              <path :d="edge.path" fill="none" stroke="transparent" stroke-width="36" vector-effect="non-scaling-stroke" class="pointer-events-auto cursor-pointer"
                style="pointer-events: stroke" role="button" tabindex="0" data-graph-edge :aria-label="relationLabel(edge.relation)"
                @click="selectRelation(edge.relation)" @keydown.enter.prevent="selectRelation(edge.relation)" @keydown.space.prevent="selectRelation(edge.relation)" />
            </g>
          </svg>
          <button v-for="event in visibleEvents" :key="event.event_id" :data-event-id="event.event_id" type="button"
            class="graph-node absolute z-20 flex w-[152px] flex-col items-center rounded-xl text-center focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
            :class="{ 'graph-node-selected': selectedEventId === event.event_id, 'graph-node-muted': !nodeRelated(event.event_id), 'graph-node-local': event.diary_id === diaryId, 'graph-node-related': event.diary_id !== diaryId }"
            :style="{ left: `${(positions[event.event_id]?.x || 0) - 76}px`, top: `${(positions[event.event_id]?.y || 0) - 30}px` }"
            :aria-label="`${event.diary_id === diaryId ? '本篇' : '关联日记'} · ${event.diary_date} ${event.title}`" @click="handleNodeActivation(event, $event)">
            <span class="graph-node-circle flex h-[60px] w-[60px] items-center justify-center rounded-full border-[3px] text-xs font-medium shadow-sm"
              :class="event.diary_id === diaryId ? 'border-white bg-primary-500 text-white' : 'border-primary-300 bg-primary-50 text-primary-800'">{{ event.diary_id === diaryId ? '本篇' : '关联' }}</span>
            <span v-if="camera.scale >= 0.3" class="mt-2 line-clamp-2 max-w-full rounded bg-[#fbf9f4]/90 px-1 text-base font-medium leading-5 text-neutral-800">{{ event.title || '未命名事件' }}</span>
            <span v-if="camera.scale >= 0.55" class="mt-1 text-xs text-neutral-500">{{ event.diary_date }}</span>
          </button>
        </div>
      </div>
      </div>
      <section v-if="(selectedEvent || selectedRelation) && !detailsOpen" class="graph-preview max-h-[40dvh] shrink-0 overflow-y-auto border-t px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3" :aria-label="selectedRelation ? '选中关系内容' : '选中事件内容'">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <span class="preview-type"><span class="detail-dot" :style="{ backgroundColor: selectedRelation ? relationColorForType(selectedRelation.relation_type) : selectedEvent?.diary_id === diaryId ? '#e07a3c' : '#a84d28' }" />{{ selectedRelation ? selectedRelation.relation_type : selectedEvent?.diary_id === diaryId ? '本篇事件' : '关联事件' }}</span>
            <h2 v-if="selectedRelation" class="preview-title">{{ relationLabel(selectedRelation) }}</h2>
            <h2 v-if="selectedEvent" class="preview-title">{{ selectedEvent.title || '未命名事件' }}</h2>
          </div>
          <button type="button" class="preview-action min-h-11 shrink-0" @click="detailsOpen = true">查看详情 <span aria-hidden="true">›</span></button>
        </div>
        <template v-if="selectedRelation">
          <span v-if="selectedRelation.certainty === 'SPECULATIVE'" class="mt-1 inline-block text-xs text-amber-700">推测关系</span>
          <p class="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-neutral-700">{{ selectedRelation.description || '暂无关系描述' }}</p>
          <div v-for="side in evidenceSides" :key="side.label" class="mt-2">
            <p class="text-xs font-medium text-neutral-500">{{ side.label }}<span v-if="side.event?.title"> · {{ side.event.title }}</span></p>
            <ol v-if="side.points.length" class="mt-1 space-y-1 text-sm leading-6 text-neutral-700">
              <li v-for="point in side.points" :key="point.id" class="flex gap-1.5 whitespace-pre-wrap break-words">
                <span class="shrink-0 font-medium">{{ point.no }}.</span><span class="min-w-0">{{ point.summary }}</span>
              </li>
            </ol>
            <p v-else class="mt-1 text-sm text-neutral-400">暂无关联要点</p>
          </div>
        </template>
        <ol v-else-if="selectedEvent && selectedEvent.points.length" class="mt-2 space-y-1 text-sm leading-6 text-neutral-700">
          <li v-for="point in selectedEvent.points" :key="point.id" class="flex gap-1.5 whitespace-pre-wrap break-words">
            <span class="shrink-0 font-medium">{{ point.no }}.</span><span class="min-w-0">{{ point.summary }}</span>
          </li>
        </ol>
        <p v-else-if="selectedEvent" class="mt-2 text-sm text-neutral-400">暂无事件要点</p>
        <div v-if="selectedEvent" class="mt-2 flex items-center justify-between gap-3 border-t border-neutral-100 pt-2">
          <p v-if="expandMessage" role="status" class="min-w-0 text-xs text-neutral-500">{{ expandMessage }}</p>
          <span v-else class="text-xs text-neutral-400">图谱探索</span>
          <button type="button" class="min-h-11 shrink-0 px-2 text-sm text-primary-700 disabled:opacity-50" :disabled="expanding" @click="expandNeighbors">{{ expanding ? '正在展开…' : '展开关联' }}</button>
        </div>
      </section>
      <aside v-if="selectedEvent || selectedRelation" class="graph-detail fixed inset-0 z-[80] flex min-h-0 flex-col"
        :class="detailsOpen ? 'flex' : 'hidden'" :aria-label="selectedRelation ? '关系详情' : '事件详情'" style="padding-bottom: env(safe-area-inset-bottom)" @keydown.esc.prevent="detailsOpen = false">
        <div class="detail-toolbar flex shrink-0 items-center justify-between border-b px-4 py-3">
          <button type="button" class="min-h-11 text-sm font-medium text-primary-700" @click="detailsOpen = false">‹ 返回图谱</button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
          <template v-if="selectedRelation">
            <span class="detail-type"><span class="detail-dot" :style="{ backgroundColor: relationColorForType(selectedRelation.relation_type) }" />{{ selectedRelation.relation_type }}<span v-if="selectedRelation.certainty === 'SPECULATIVE'" class="status-pill">推测</span></span>
            <h3 class="detail-title">{{ relationLabel(selectedRelation) }}</h3>
            <section class="detail-block">
              <h4>关系方向</h4>
              <button type="button" class="connection" @click="selectRelationEndpoint(selectedRelation, 'source')">
                <span class="detail-dot" style="background:#e07a3c" />
                <span class="min-w-0"><strong>{{ eventMap.get(selectedRelation.source_event_id)?.title || '未命名事件' }}</strong><small>起点 · {{ eventMap.get(selectedRelation.source_event_id)?.diary_date || '日期未知' }}</small></span>
              </button>
              <div class="relation-direction">↓ {{ selectedRelation.relation_type }}<span v-if="selectedRelation.certainty === 'SPECULATIVE'"> · 推测关系</span></div>
              <button type="button" class="connection" @click="selectRelationEndpoint(selectedRelation, 'target')">
                <span class="detail-dot" style="background:#9ca3af" />
                <span class="min-w-0"><strong>{{ eventMap.get(selectedRelation.target_event_id)?.title || '未命名事件' }}</strong><small>终点 · {{ eventMap.get(selectedRelation.target_event_id)?.diary_date || '日期未知' }}</small></span>
              </button>
            </section>
            <section class="detail-block">
              <h4>关系描述</h4>
              <p class="detail-description">{{ selectedRelation.description || '暂无关系描述' }}</p>
            </section>
            <section class="detail-block">
              <h4>关系依据</h4>
              <div class="relation-evidence">
                <article v-for="side in evidenceSides" :key="`evidence-${side.label}`" class="evidence-group">
                  <h5>{{ side.label }} · {{ side.event?.title || '未命名事件' }}</h5>
                  <template v-if="side.points.length">
                    <div v-for="point in side.points" :key="point.id" class="mt-2">
                      <p class="evidence-point"><strong>{{ point.no }}.</strong> {{ point.summary }}</p>
                      <details class="mt-1">
                        <summary class="flex min-h-11 cursor-pointer items-center text-sm font-medium text-primary-700">查看原文依据</summary>
                        <p class="evidence">{{ point.detail }}</p>
                      </details>
                    </div>
                  </template>
                  <p v-else class="text-sm text-neutral-400">没有保存对应要点依据</p>
                </article>
              </div>
            </section>
          </template>
          <template v-else-if="selectedEvent">
            <span class="detail-type"><span class="detail-dot" :style="{ backgroundColor: selectedEvent.diary_id === diaryId ? '#e07a3c' : '#a84d28' }" />{{ selectedEvent.diary_id === diaryId ? '本篇事件' : '关联事件' }}</span>
            <h3 class="detail-title">{{ selectedEvent.title || '未命名事件' }}</h3>
            <section class="detail-block">
              <h4>事件要点</h4>
              <div v-if="selectedEvent.points.length" class="event-points">
                <p v-for="point in selectedEvent.points" :key="point.id" class="event-point"><strong>{{ point.no }}. {{ point.summary }}：</strong>{{ point.detail }}</p>
              </div>
              <p v-else class="panel-intro">暂无事件要点</p>
            </section>
          </template>
        </div>
      </aside>
      </div>
    </template>
    <p v-if="error && events.length" role="alert" class="absolute bottom-2 left-3 right-3 z-30 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import type { DiaryGraphResult, GraphEvent, GraphRelation } from '~/types/graph'
import { layoutGraph, graphEdges, nodeBox, type GraphPositions } from '~/utils/graph-layout'
const props = defineProps<{ diaryId: string; visible: boolean; revision: number }>()
const { api } = useApi()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const viewport = ref<HTMLElement | null>(null)
const events = ref<GraphEvent[]>([])
const relations = ref<GraphRelation[]>([])
const positions = ref<Record<string, { x: number; y: number }>>({})
const camera = ref({ x: 0, y: 0, scale: 1 })
const loading = ref(false)
const error = ref('')
const selectedEventId = ref('')
const selectedRelation = ref<GraphRelation | null>(null)
const detailsOpen = ref(false)
const expanding = ref(false)
const expandMessage = ref('')
let loaded = false
let savedView = false
let rootRunId: string | null = null
const expandedIds = new Set<string>()
const manualPositionIds = reactive(new Set<string>())
let generation = 0
const markerId = `graph-arrow-${props.diaryId}`
const localCount = computed(() => events.value.filter(event => event.diary_id === props.diaryId).length)
const selectedEvent = computed(() => events.value.find(event => event.event_id === selectedEventId.value))
const eventMap = computed(() => new Map(events.value.map(event => [event.event_id, event])))
const relationLabel = (r: GraphRelation) => `${eventMap.value.get(r.source_event_id)?.title || '事件'} → ${r.relation_type} → ${eventMap.value.get(r.target_event_id)?.title || '事件'}`
const isRelated = (r: GraphRelation) => r.id === selectedRelation.value?.id || [r.source_event_id, r.target_event_id].includes(selectedEventId.value)
const relationTypes: GraphRelation['relation_type'][] = ['后续事件', '提及事件', '引发事件']
const relationTypeColors: Record<GraphRelation['relation_type'], string> = { '后续事件': '#0072b2', '提及事件': '#009e73', '引发事件': '#7b2cbf' }
const relationTypeMarkerIds: Record<GraphRelation['relation_type'], string> = { '后续事件': 'follow-up', '提及事件': 'mention', '引发事件': 'trigger' }
const hiddenTypes = ref<GraphRelation['relation_type'][]>([])
const focusId = ref('')
type ReturnView = { positions: GraphPositions; camera: typeof camera.value; hiddenTypes: GraphRelation['relation_type'][] }
const returnView = ref<ReturnView | null>(null)
const scopedRelations = computed(() => relations.value.filter(edge => !focusId.value || [edge.source_event_id, edge.target_event_id].includes(focusId.value)))
const availableRelationTypes = computed(() => relationTypes.filter(type => scopedRelations.value.some(edge => edge.relation_type === type)))
const visibleRelations = computed(() => scopedRelations.value.filter(edge => !hiddenTypes.value.includes(edge.relation_type)))
const visibleEvents = computed(() => {
  const ids = new Set(visibleRelations.value.flatMap(edge => [edge.source_event_id, edge.target_event_id]))
  return events.value.filter(event => focusId.value ? event.event_id === focusId.value || ids.has(event.event_id) : !hiddenTypes.value.length || event.diary_id === props.diaryId || ids.has(event.event_id))
})
const relationColorForType = (type: GraphRelation['relation_type']) => relationTypeColors[type]
const relationColor = (edge: GraphRelation) => relationColorForType(edge.relation_type)
const markerIdForType = (type: GraphRelation['relation_type']) => `${markerId}-${relationTypeMarkerIds[type]}`
const nodeRelated = (id: string) => {
  if (selectedRelation.value) return [selectedRelation.value.source_event_id, selectedRelation.value.target_event_id].includes(id)
  return !selectedEventId.value || id === selectedEventId.value || relations.value.some(edge => [edge.source_event_id, edge.target_event_id].includes(id) && [edge.source_event_id, edge.target_event_id].includes(selectedEventId.value))
}
const drawnEdges = computed(() => graphEdges(visibleRelations.value, Object.fromEntries(visibleEvents.value.map(event => [event.event_id, positions.value[event.event_id]]).filter(([, p]) => !!p)) as GraphPositions, selectedRelation.value?.id).map(edge => ({ ...edge, relation: visibleRelations.value.find(relation => relation.id === edge.id)! })))
const relayout = (reset = false) => {
  const previous = positions.value
  const next = layoutGraph(visibleEvents.value, visibleRelations.value, props.diaryId, reset ? {} : previous)
  if (!reset) for (const id of manualPositionIds) if (previous[id] && next[id]) next[id] = previous[id]
  positions.value = { ...previous, ...next }
}
const resetPositions = async () => {
  manualPositionIds.clear()
  positions.value = layoutGraph(events.value, relations.value, props.diaryId)
  await nextTick(); fit(); persist()
}
const toggleType = async (type: GraphRelation['relation_type']) => {
  hiddenTypes.value = hiddenTypes.value.includes(type) ? hiddenTypes.value.filter(item => item !== type) : [...hiddenTypes.value, type]
  detailsOpen.value = false; selectedRelation.value = null; selectedEventId.value = ''
  await nextTick(); fit(); persist()
}
const focusEvent = async () => {
  if (!selectedEvent.value) return
  if (!returnView.value) returnView.value = { positions: Object.fromEntries(Object.entries(positions.value).map(([id, point]) => [id, { x: point.x, y: point.y }])), camera: { ...camera.value }, hiddenTypes: [...hiddenTypes.value] }
  focusId.value = selectedEvent.value.event_id; hiddenTypes.value = []; detailsOpen.value = false
  const focused = layoutGraph([selectedEvent.value, ...visibleEvents.value.filter(event => event.event_id !== selectedEventId.value)], visibleRelations.value, selectedEvent.value.diary_id)
  for (const id of manualPositionIds) if (positions.value[id] && focused[id]) focused[id] = positions.value[id]
  positions.value = { ...positions.value, ...focused }
  await nextTick(); fit(); persist()
}
const restoreGraph = () => {
  focusId.value = ''; detailsOpen.value = false; selectedRelation.value = null; selectedEventId.value = ''
  if (returnView.value) { positions.value = returnView.value.positions; camera.value = returnView.value.camera; hiddenTypes.value = returnView.value.hiddenTypes; returnView.value = null }
  relayout(); persist()
}
const evidenceSides = computed(() => selectedRelation.value ? (['source', 'target'] as const).map(side => {
  const r = selectedRelation.value!
  const event = eventMap.value.get(side === 'source' ? r.source_event_id : r.target_event_id)
  const ids = new Set((side === 'source' ? r.source_points : r.target_points).map(point => point.point_id))
  return { label: side === 'source' ? '起点依据' : '终点依据', event, points: event?.points.filter(point => ids.has(point.id)) || [] }
}) : [])
const cacheKey = () => `diary-graph-v18-size-aware-layout:${auth.user?.id || 'user'}:${props.diaryId}`
const persist = () => {
  try { sessionStorage.setItem(cacheKey(), JSON.stringify({ focusId: focusId.value, returnView: returnView.value, hiddenTypes: hiddenTypes.value, rootRunId, positions: positions.value, camera: camera.value, expandedIds: [...expandedIds], manualPositionIds: [...manualPositionIds] })) } catch { /* 存储不可用时保留当前会话内状态 */ }
}
const merge = (data: DiaryGraphResult) => {
  const nodes = new Map(events.value.map(event => [event.event_id, event]))
  data.events.forEach(event => nodes.set(event.event_id, event))
  events.value = [...nodes.values()]
  const edges = new Map(relations.value.map(edge => [edge.id, edge]))
  data.relations.forEach(edge => edges.set(edge.id, edge))
  relations.value = [...edges.values()]
  relayout()
}
const load = async () => {
  if (loading.value) return
  const token = ++generation
  loading.value = true; error.value = ''
  try {
    const data = await api<DiaryGraphResult>(`/graph/diaries/${props.diaryId}`)
    if (token !== generation) return
    events.value = []; relations.value = []; detailsOpen.value = false; selectedRelation.value = null
    if (!data.run || (rootRunId && rootRunId !== data.run.id)) { positions.value = {}; expandedIds.clear(); manualPositionIds.clear(); savedView = false; selectedEventId.value = ''; focusId.value = ''; returnView.value = null; hiddenTypes.value = [] }
    rootRunId = data.run?.id || null
    merge(data)
    const neighbors = await Promise.allSettled([...expandedIds].map(id => api<DiaryGraphResult>(`/graph/events/${id}/neighbors`)))
    if (token !== generation) return
    neighbors.forEach(result => { if (result.status === 'fulfilled') merge(result.value) })
    positions.value = Object.fromEntries(Object.entries(positions.value).filter(([id]) => events.value.some(event => event.event_id === id)))
    loaded = true
    await nextTick(); if (!savedView) fit(); savedView = false; persist()
  } catch { error.value = '图谱加载失败，请重试' } finally { if (token === generation) loading.value = false }
}
const fit = () => {
  if (!viewport.value || !visibleEvents.value.length) return
  const boxes = [...visibleEvents.value.map(event => nodeBox(positions.value[event.event_id])), ...drawnEdges.value.map(edge => edge.bounds)]
  const minX = Math.min(...boxes.map(p => p.x)), minY = Math.min(...boxes.map(p => p.y))
  const width = Math.max(...boxes.map(p => p.x + p.width)) - minX, height = Math.max(...boxes.map(p => p.y + p.height)) - minY
  const scale = Math.max(.08, Math.min(1, (viewport.value.clientWidth - 40) / width, (viewport.value.clientHeight - 100) / height))
  camera.value = { x: viewport.value.clientWidth / 2 - (minX + width / 2) * scale, y: 55 - minY * scale, scale }

}
const zoom = (factor: number, x = (viewport.value?.clientWidth || 0) / 2, y = (viewport.value?.clientHeight || 0) / 2) => {
  const previous = camera.value, scale = Math.min(2, Math.max(0.08, previous.scale * factor)), ratio = scale / previous.scale
  camera.value = { x: x - (x - previous.x) * ratio, y: y - (y - previous.y) * ratio, scale }
}
const pointers = new Map<number, { x: number; y: number }>()
let nodeDrag: { id: string; pointerId: number; startX: number; startY: number; origin: { x: number; y: number }; moved: boolean } | null = null
let dragging = false
const guardDragClick = (event: MouseEvent) => { if (dragging) { event.preventDefault(); event.stopPropagation(); dragging = false } }
const clearSelectionAndFit = async () => {
  selectedEventId.value = ''; selectedRelation.value = null
  detailsOpen.value = false
  await nextTick()
  fit(); persist()
}
const clearSelectionOnCanvas = (event: MouseEvent) => {
  if ((event.target as Element).closest('.graph-node, [data-graph-edge]')) return
  clearSelectionAndFit()
}
const pointerDown = (e: PointerEvent) => {
  if (e.button !== 0) return
  if (!pointers.size) dragging = false
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pointers.size === 1) {
    const node = (e.target as Element).closest<HTMLElement>('.graph-node')
    const id = node?.dataset.eventId || ''
    if (id && positions.value[id]) nodeDrag = { id, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, origin: { ...positions.value[id] }, moved: false }
  } else nodeDrag = null
}
const pointerMove = (e: PointerEvent) => {
  const previous = pointers.get(e.pointerId)
  if (!previous) return
  if (pointers.size === 1 && nodeDrag?.pointerId === e.pointerId) {
    const totalX = e.clientX - nodeDrag.startX, totalY = e.clientY - nodeDrag.startY
    if (!nodeDrag.moved && Math.hypot(totalX, totalY) < 6) return
    nodeDrag.moved = true; dragging = true
    positions.value = { ...positions.value, [nodeDrag.id]: { x: nodeDrag.origin.x + totalX / camera.value.scale, y: nodeDrag.origin.y + totalY / camera.value.scale } }
    try { viewport.value?.setPointerCapture(e.pointerId) } catch { /* 已结束的触点无需捕获 */ }
    return
  }
  if (!dragging && pointers.size === 1 && Math.hypot(e.clientX - previous.x, e.clientY - previous.y) < 5) return
  dragging = true
  try { viewport.value?.setPointerCapture(e.pointerId) } catch { /* 已结束的触点无需捕获 */ }
  const before = [...pointers.values()]
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  const after = [...pointers.values()]
  if (before.length === 2) {
    const distance = (points: typeof before) => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y)
    const rect = viewport.value!.getBoundingClientRect()
    const bx = (before[0].x + before[1].x) / 2, by = (before[0].y + before[1].y) / 2
    zoom(distance(after) / (distance(before) || 1), bx - rect.left, by - rect.top)
    camera.value.x += (after[0].x + after[1].x) / 2 - bx; camera.value.y += (after[0].y + after[1].y) / 2 - by
  } else { camera.value.x += e.clientX - previous.x; camera.value.y += e.clientY - previous.y }
}
const pointerUp = (e: PointerEvent) => {
  pointers.delete(e.pointerId)
  if (nodeDrag?.pointerId === e.pointerId) {
    if (nodeDrag.moved) manualPositionIds.add(nodeDrag.id)
    nodeDrag = null
  }
  persist()
}
const wheelZoom = (e: WheelEvent) => { const rect = viewport.value!.getBoundingClientRect(); zoom(Math.exp(-e.deltaY * 0.002), e.clientX - rect.left, e.clientY - rect.top) }
const selectEvent = (event: GraphEvent) => {
  if (!visibleEvents.value.some(node => node.event_id === event.event_id)) { restoreGraph(); hiddenTypes.value = []; relayout() }
  if (!positions.value[event.event_id]) relayout()
  selectedEventId.value = event.event_id; selectedRelation.value = null; expandMessage.value = ''; detailsOpen.value = false
  persist()
}
let pendingNodeTap: { eventId: string; event: GraphEvent; timer: ReturnType<typeof setTimeout>; at: number } | null = null
const handleNodeActivation = (event: GraphEvent, click: MouseEvent) => {
  if (click.detail === 0) { selectEvent(event); return }
  const now = Date.now()
  if (pendingNodeTap?.eventId === event.event_id && now - pendingNodeTap.at < 320) {
    clearTimeout(pendingNodeTap.timer)
    pendingNodeTap = null
    if (event.diary_id === props.diaryId) {
      selectedEventId.value = event.event_id
      selectedRelation.value = null
      void focusEvent()
    } else {
      persist()
      detailsOpen.value = false
      void router.push({ path: `/diary/${event.diary_id}`, query: { view: 'graph', focus: event.event_id } })
    }
    return
  }
  if (pendingNodeTap) {
    clearTimeout(pendingNodeTap.timer)
    selectEvent(pendingNodeTap.event)
  }
  const tap = { eventId: event.event_id, event, at: now, timer: setTimeout(() => {
    if (pendingNodeTap?.eventId !== event.event_id) return
    pendingNodeTap = null
    selectEvent(event)
  }, 320) }
  pendingNodeTap = tap
}
const selectRelation = (relation: GraphRelation) => { selectedRelation.value = relation; selectedEventId.value = ''; detailsOpen.value = false; persist() }
const selectRelationEndpoint = (relation: GraphRelation, side: 'source' | 'target') => {
  const eventId = side === 'source' ? relation.source_event_id : relation.target_event_id
  const event = eventMap.value.get(eventId)
  if (event) selectEvent(event)
}
const expandNeighbors = async () => {
  const id = selectedEventId.value
  const token = generation
  if (!id || expanding.value) return
  expanding.value = true; expandMessage.value = ''
  try {
    const data = await api<DiaryGraphResult>(`/graph/events/${id}/neighbors`)
    if (token !== generation) return
    const count = events.value.length; merge(data); expandedIds.add(id); persist()
    expandMessage.value = events.value.length > count ? `新增 ${events.value.length - count} 个关联事件，关闭面板查看` : '已展示该事件的全部直接关联'
  } catch { expandMessage.value = '关联加载失败，请重试' } finally { expanding.value = false }
}
const applyRouteFocus = async () => {
  const eventId = typeof route.query.focus === 'string' ? route.query.focus : ''
  if (!eventId || !events.value.some(event => event.event_id === eventId)) return
  selectedEventId.value = eventId
  await focusEvent()
  persist()
}
watch(() => props.visible, async visible => {
  if (!visible) { detailsOpen.value = false; selectedEventId.value = ''; selectedRelation.value = null; persist(); return }
  if (!loaded) await load()
})
watch(() => props.revision, () => { if (loaded) void load(true) })
onMounted(async () => {
  try {
    const cached = JSON.parse(sessionStorage.getItem(cacheKey()) || 'null')
    if (cached?.camera && cached?.positions) { focusId.value = cached.focusId || ''; returnView.value = cached.returnView || null; hiddenTypes.value = (cached.hiddenTypes || []).filter((type: GraphRelation['relation_type']) => relationTypes.includes(type)); rootRunId = cached.rootRunId || null; positions.value = cached.positions; camera.value = cached.camera; for (const id of cached.expandedIds || []) expandedIds.add(id); for (const id of cached.manualPositionIds || []) manualPositionIds.add(id); savedView = true }
  } catch { /* 无缓存时正常加载 */ }
  if (props.visible && !loaded) await load()
  await applyRouteFocus()
})
onBeforeUnmount(() => { generation++; if (pendingNodeTap) clearTimeout(pendingNodeTap.timer); persist() })
</script>

<style scoped>
.graph-shell {
  --graph-bg: #f9fafb;
  --graph-surface: #fff;
  --graph-ink: #1f2937;
  --graph-muted: #6b7280;
  --graph-line: #e5e7eb;
  --graph-accent: #cc6230;
  color: var(--graph-ink);
  background: var(--graph-bg);
}
.graph-toolbar, .graph-preview, .graph-detail { background: var(--graph-surface); }
.graph-toolbar { border-color: var(--graph-line); }
.graph-toolbar p { color: var(--graph-muted); }
.graph-toolbar button.text-primary-700, .graph-toolbar button.text-primary-600 { color: var(--graph-accent); }
.graph-toolbar button[aria-pressed="true"] { border-color: #f6d9b8; background: #fdf8f3; color: #a84d28; }
.graph-toolbar button[aria-pressed="false"] { border-color: var(--graph-line); background: transparent; color: var(--graph-muted); }
.graph-preview { border-color: var(--graph-line); box-shadow: 0 -4px 14px rgba(31, 41, 55, .06); }
.preview-type { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 999px; background: #fdf8f3; color: #a84d28; font-size: 11px; font-weight: 600; }
.preview-type .detail-dot { width: 8px; height: 8px; }
.preview-title { margin: 7px 0 0; overflow-wrap: anywhere; color: var(--graph-ink); font-size: 16px; font-weight: 600; line-height: 1.5; }
.preview-action { padding: 0 4px 0 8px; color: var(--graph-accent); font-size: 13px; font-weight: 600; white-space: nowrap; }
.graph-detail { color: var(--graph-ink); background: var(--graph-surface); }
.detail-toolbar { border-color: var(--graph-line); background: #fff; }
.detail-toolbar h2 { color: var(--graph-ink); }
.detail-toolbar button { color: var(--graph-accent); }
.graph-detail .detail-block { border-color: var(--graph-line); }
.graph-detail .detail-block h4 { color: var(--graph-muted); }
.graph-detail .detail-title { color: var(--graph-ink); }
.graph-detail .detail-description { color: #4b5563; font-size: 14px; line-height: 1.75; }
.graph-detail .detail-type { color: #a84d28; background: #fdf8f3; }
.graph-detail .evidence-group { border-color: var(--graph-line); background: #f9fafb; }
.graph-detail .evidence-group h5 { color: var(--graph-muted); }
.graph-canvas {
  background-color: #f9fafb;
  background-image: radial-gradient(rgba(107, 114, 128, .2) .8px, transparent .8px);
  background-size: 22px 22px;
}
.detail-type { display: inline-flex; align-items: center; gap: 7px; padding: 5px 9px; border-radius: 999px; background: #fdf8f3; color: #a84d28; font-size: 12px; }
.detail-dot { width: 10px; height: 10px; flex: 0 0 auto; border-radius: 50%; }
.status-pill { padding: 2px 7px; border-radius: 999px; background: #efe6cf; color: #75531c; font-size: 11px; }
.detail-title { margin: 12px 0 7px; overflow-wrap: anywhere; font-size: 18px; font-weight: 600; line-height: 1.5; color: #1f2937; }
.detail-block { margin-top: 18px; padding-top: 14px; border-top: 1px solid #e5e7eb; }
.detail-block h4 { margin: 0 0 9px; color: #6b7280; font-size: 12px; font-weight: 600; }
.event-points { display: grid; gap: 12px; }
.event-point { margin: 0; color: #374151; font-size: 14px; line-height: 1.75; }
.event-point strong { color: #1f2937; font-weight: 600; }
.relation-direction { padding: 8px 18px; color: #6b7280; font-size: 13px; }
.relation-evidence { display: grid; gap: 12px; }
.evidence-group { padding: 12px; border: 1px solid #e5e7eb; border-radius: 12px; background: #f9fafb; }
.evidence-group h5 { margin: 0 0 9px; color: #6b7280; font-size: 12px; font-weight: 600; line-height: 1.5; }
.evidence-point { margin: 0; color: #374151; font-size: 14px; line-height: 1.65; }
.evidence-point strong { color: #1f2937; }
.evidence { padding: 12px; border-left: 3px solid #cc6230; border-radius: 4px 10px 10px 4px; background: #fdf8f3; color: #374151; font-size: 14px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.connection { width: 100%; min-height: 52px; display: flex; align-items: center; gap: 9px; padding: 8px 10px; border: 0; border-radius: 9px; background: #f3f4f6; cursor: pointer; text-align: left; }
.connection:hover { background: #e5e7eb; }
.connection strong { display: block; color: #1f2937; font-size: 14px; line-height: 1.4; }
.connection small { display: block; margin-top: 2px; color: #6b7280; font-size: 12px; line-height: 1.4; }
.graph-node { transition: opacity .15s; }
.graph-node-local .graph-node-circle { border-color: #fff; background: #e07a3c; color: #fff; }
.graph-node-related .graph-node-circle { border-color: #efbc88; background: #fdf8f3; color: #853e27; }
.graph-node-selected .graph-node-circle { outline: 2px solid #a84d28; outline-offset: 4px; }
.graph-node-muted { opacity: .35; }
@media (prefers-reduced-motion: reduce) { .graph-node { transition: none; } }
</style>
