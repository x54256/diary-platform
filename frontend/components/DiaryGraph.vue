<template>
  <div class="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-neutral-50">
    <div class="shrink-0 border-b border-neutral-200 bg-white px-4 py-2">
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs text-neutral-500">{{ focusId ? '聚焦事件' : '本篇日记' }} · {{ visibleEvents.length }} 个节点 · {{ visibleRelations.length }} 条关系</p>
        <button type="button" class="min-h-11 px-2 text-sm text-primary-600" @click="load(true)">刷新</button>
      </div>
      <div class="flex flex-wrap items-center gap-1" role="group" aria-label="关系筛选">
        <button v-for="type in relationTypes" :key="type" type="button" class="min-h-11 rounded-full border px-3 text-xs transition-colors"
          :class="hiddenTypes.includes(type) ? 'border-neutral-200 text-neutral-400' : 'border-primary-200 bg-primary-50 text-primary-800'"
          :aria-pressed="!hiddenTypes.includes(type)" @click="toggleType(type)">{{ type.replace('事件', '') }} {{ scopedRelations.filter(edge => edge.relation_type === type).length }}</button>
        <button v-if="focusId" type="button" class="min-h-11 px-2 text-sm text-primary-600" @click="restoreGraph">返回原图</button>
      </div>
    </div>
    <div v-if="loading && !events.length" class="flex flex-1 items-center justify-center text-sm text-neutral-500">正在读取图谱…</div>
    <div v-else-if="error && !events.length" class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-sm">
      <p role="alert">{{ error }}</p><button class="min-h-11 text-primary-600" @click="load(true)">重新加载</button>
    </div>
    <div v-else-if="!events.length" class="flex flex-1 items-center justify-center p-6 text-sm text-neutral-500">暂无可展示的图谱，可切回列表阅读日记</div>
    <template v-else>
      <div ref="viewport" class="graph-canvas relative min-h-0 flex-1 touch-none overflow-hidden" aria-label="事件关系图谱"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @click.capture="guardDragClick" @wheel.prevent="wheelZoom">
        <p class="pointer-events-none absolute left-3 top-3 z-10 rounded-lg bg-white/90 px-2 py-1 text-xs text-neutral-500">{{ relations.length ? '拖动浏览 · 点击节点或连线' : '暂无已建立的事件关系' }}</p>
        <p v-if="relations.length && !visibleRelations.length" class="pointer-events-none absolute bottom-4 left-3 right-16 z-10 text-xs text-neutral-500">当前筛选下暂无关系，可点击上方类型恢复</p>
        <div class="absolute left-0 top-0 origin-top-left" :style="{ transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})` }">
          <svg class="pointer-events-none absolute overflow-visible" width="1" height="1">
            <defs><marker :id="markerId" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#82796e" /></marker></defs>
            <g v-for="edge in drawnEdges" :key="edge.relation.id">
              <path :d="edge.path" fill="none" :stroke="relationColor(edge.relation)" :stroke-width="isRelated(edge.relation) ? 2.8 : 1.6"
                :opacity="selectedEventId || selectedRelation ? (isRelated(edge.relation) ? 1 : .22) : .65"
                :stroke-dasharray="edge.relation.certainty === 'SPECULATIVE' ? '6 4' : undefined" :marker-end="`url(#${markerId})`" />
              <path :d="edge.path" fill="none" stroke="transparent" stroke-width="24" vector-effect="non-scaling-stroke" class="pointer-events-auto cursor-pointer"
                style="pointer-events: stroke" role="button" tabindex="0" :aria-label="relationLabel(edge.relation)"
                @click="selectRelation(edge.relation)" @keydown.enter.prevent="selectRelation(edge.relation)" @keydown.space.prevent="selectRelation(edge.relation)" />
            </g>
          </svg>
          <template v-for="edge in drawnEdges" :key="`label-${edge.relation.id}`">
            <button v-if="edge.label" type="button" class="absolute z-10 min-h-9 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-white/90 px-2 text-xs shadow-sm"
              :style="{ left: `${edge.label.x}px`, top: `${edge.label.y}px`, color: relationColor(edge.relation) }"
              :aria-label="relationLabel(edge.relation)" @click="selectRelation(edge.relation)">
              {{ edge.relation.relation_type.replace('事件', '') }}<span v-if="edge.relation.certainty === 'SPECULATIVE'"> · 推测</span>
            </button>
          </template>
          <button v-for="event in visibleEvents" :key="event.event_id" type="button"
            class="graph-node absolute z-20 flex w-[152px] flex-col items-center rounded-xl text-center focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
            :class="{ 'graph-node-selected': selectedEventId === event.event_id, 'graph-node-muted': !nodeRelated(event.event_id) }"
            :style="{ left: `${(positions[event.event_id]?.x || 0) - 76}px`, top: `${(positions[event.event_id]?.y || 0) - 30}px` }"
            :aria-label="`${event.diary_id === diaryId ? '本篇' : '关联日记'} · ${event.diary_date} ${event.title}`" @click="selectEvent(event)">
            <span class="graph-node-circle flex h-[60px] w-[60px] items-center justify-center rounded-full border-[3px] text-xs font-medium shadow-sm"
              :class="event.diary_id === diaryId ? 'border-white bg-primary-500 text-white' : 'border-primary-300 bg-primary-50 text-primary-800'">{{ event.diary_id === diaryId ? '本篇' : '关联' }}</span>
            <span class="mt-2 line-clamp-2 max-w-full rounded bg-[#fbf9f4]/90 px-1 text-sm font-medium leading-5 text-neutral-800">{{ event.title || '未命名事件' }}</span>
            <span class="mt-1 text-[11px] text-neutral-500">{{ event.diary_date }}</span>
          </button>
        </div>
      </div>
      <div class="absolute right-3 bottom-4 z-20 flex flex-col rounded-xl border border-neutral-200 bg-white shadow-sm">
        <button type="button" class="h-11 min-w-11 text-xl" aria-label="放大图谱" @click="zoom(1.25)">＋</button>
        <button type="button" class="h-11 min-w-11 text-xl" aria-label="缩小图谱" @click="zoom(0.8)">−</button>
        <button type="button" class="min-h-11 px-2 text-xs" @click="fit(true)">全览</button>
        <button type="button" class="min-h-11 px-2 text-xs" @click="home">本篇</button>
      </div>
    </template>
    <p v-if="error && events.length" role="alert" class="absolute bottom-2 left-3 right-3 z-30 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
    <Teleport to="body">
      <div v-if="panelOpen" class="fixed inset-0 z-[80] flex items-end justify-center bg-black/25" @click.self="closePanel" @keydown.esc="closePanel" @keydown.tab="trapFocus">
        <section ref="panel" tabindex="-1" role="dialog" aria-modal="true" :aria-label="selectedRelation ? '关系依据' : '事件详情'"
          class="flex w-full max-w-md flex-col rounded-t-2xl bg-white shadow-xl focus:outline-none"
          :class="expanded ? 'h-[88dvh]' : 'h-[48dvh]'" style="padding-bottom: env(safe-area-inset-bottom)">
          <div class="shrink-0 border-b border-neutral-100 px-4 py-2">
            <div class="flex touch-none justify-center py-2" @pointerdown="startSheetDrag" @pointerup="sheetEnd" @pointercancel="sheetStart = null"><span class="h-1 w-10 rounded-full bg-neutral-300" /></div>
            <div class="flex items-center justify-between"><h2 class="font-medium">{{ selectedRelation ? '关系依据' : '事件详情' }}</h2><div class="flex gap-2"><button class="min-h-11 px-2 text-sm text-primary-600" @click="expanded = !expanded">{{ expanded ? '收起' : '展开' }}</button><button class="min-h-11 min-w-11 text-xl" aria-label="关闭详情" @click="closePanel">×</button></div></div>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
            <template v-if="selectedRelation">
              <p class="text-sm font-medium leading-6">{{ relationLabel(selectedRelation) }}</p>
              <span v-if="selectedRelation.certainty === 'SPECULATIVE'" class="text-sm text-amber-700">推测：保留来源中的推测程度</span>
              <p class="mt-3 whitespace-pre-wrap text-base leading-7">{{ selectedRelation.description }}</p>
              <article v-for="side in evidenceSides" :key="side.label" class="mt-4 rounded-xl border border-neutral-200 p-3">
                <p class="text-xs text-neutral-500">{{ side.label }} · 日记日期 {{ side.event?.diary_date }}</p>
                <h3 class="mt-1 text-base font-medium">{{ side.event?.title }}</h3>
                <div v-for="point in side.points" :key="point.id" class="mt-3"><p class="text-sm font-medium">{{ point.no }}. {{ point.summary }}</p><p class="mt-1 whitespace-pre-wrap text-base leading-7 text-neutral-600">{{ point.detail }}</p></div>
              </article>
            </template>
            <template v-else-if="selectedEvent">
              <p class="text-xs text-neutral-500">日记日期 {{ selectedEvent.diary_date }}<span v-if="selectedEvent.occurred_on"> · 发生日期 {{ selectedEvent.occurred_on }}</span></p>
              <h3 class="mt-2 text-lg font-medium">{{ selectedEvent.title }}</h3>
              <div class="my-3 flex flex-wrap gap-3">
                <button type="button" class="min-h-11 text-sm font-medium text-primary-600" @click="focusEvent">聚焦该事件</button>
                <button type="button" :disabled="expanding" class="min-h-11 text-sm font-medium text-primary-600 disabled:opacity-50" @click="expandNeighbors">{{ expanding ? '正在展开…' : '展开关联' }}</button>
                <NuxtLink :to="`/diary/${selectedEvent.diary_id}#event-${selectedEvent.event_id}`" class="flex min-h-11 items-center text-sm font-medium text-primary-600" @click="visitSource">查看来源日记 ›</NuxtLink>
              </div>
              <p v-if="expandMessage" role="status" class="mb-3 text-sm text-neutral-500">{{ expandMessage }}</p>
              <div v-if="connections.length" class="mb-4 border-t border-neutral-100 pt-3">
                <h4 class="mb-2 text-xs font-medium text-neutral-500">连接关系 · {{ connections.length }}</h4>
                <button v-for="connection in connections" :key="connection.edge.id" type="button" class="mb-2 flex min-h-14 w-full items-center gap-3 rounded-xl bg-primary-50 px-3 py-2 text-left" @click="selectEvent(connection.event)">
                  <span class="text-primary-700">{{ connection.outgoing ? '→' : '←' }}</span>
                  <span><span class="block text-xs text-primary-700">{{ connection.edge.relation_type }}<span v-if="connection.edge.certainty === 'SPECULATIVE'"> · 推测</span></span><span class="mt-1 block text-sm text-neutral-800">{{ connection.event.title }}</span></span>
                </button>
              </div>
              <details v-for="point in selectedEvent.points" :key="point.id" class="mb-3 rounded-lg border border-neutral-200 p-3" :open="expanded">
                <summary class="cursor-pointer text-base font-medium leading-6">{{ point.no }}. {{ point.summary }}</summary><p class="mt-2 whitespace-pre-wrap text-base leading-7 text-neutral-600">{{ point.detail }}</p>
              </details>
            </template>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import type { DiaryGraphResult, GraphEvent, GraphRelation } from '~/types/graph'
import { layoutGraph, graphEdges, nodeBox, type GraphPositions } from '~/utils/graph-layout'
const props = defineProps<{ diaryId: string; visible: boolean; revision: number }>()
const emit = defineEmits<{ (event: 'source', id: string, diaryId: string): void }>()
const { api } = useApi()
const auth = useAuthStore()
const viewport = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const events = ref<GraphEvent[]>([])
const relations = ref<GraphRelation[]>([])
const positions = ref<Record<string, { x: number; y: number }>>({})
const camera = ref({ x: 0, y: 0, scale: 1 })
const loading = ref(false)
const error = ref('')
const selectedEventId = ref('')
const selectedRelation = ref<GraphRelation | null>(null)
const panelOpen = ref(false)
const expanded = ref(false)
const expanding = ref(false)
const expandMessage = ref('')
const sheetStart = ref<number | null>(null)
let loaded = false
let savedView = false
let rootRunId: string | null = null
const expandedIds = new Set<string>()
let generation = 0
let restoreFocus: HTMLElement | null = null
const markerId = `graph-arrow-${props.diaryId}`
const localCount = computed(() => events.value.filter(event => event.diary_id === props.diaryId).length)
const selectedEvent = computed(() => events.value.find(event => event.event_id === selectedEventId.value))
const eventMap = computed(() => new Map(events.value.map(event => [event.event_id, event])))
const relationLabel = (r: GraphRelation) => `${eventMap.value.get(r.source_event_id)?.title || '事件'} → ${r.relation_type} → ${eventMap.value.get(r.target_event_id)?.title || '事件'}`
const isRelated = (r: GraphRelation) => r.id === selectedRelation.value?.id || [r.source_event_id, r.target_event_id].includes(selectedEventId.value)
const relationTypes: GraphRelation['relation_type'][] = ['后续事件', '提及事件', '引发事件']
const hiddenTypes = ref<GraphRelation['relation_type'][]>([])
const focusId = ref('')
type ReturnView = { positions: GraphPositions; camera: typeof camera.value; hiddenTypes: GraphRelation['relation_type'][] }
const returnView = ref<ReturnView | null>(null)
const scopedRelations = computed(() => relations.value.filter(edge => !focusId.value || [edge.source_event_id, edge.target_event_id].includes(focusId.value)))
const visibleRelations = computed(() => scopedRelations.value.filter(edge => !hiddenTypes.value.includes(edge.relation_type)))
const visibleEvents = computed(() => {
  const ids = new Set(visibleRelations.value.flatMap(edge => [edge.source_event_id, edge.target_event_id]))
  return events.value.filter(event => focusId.value ? event.event_id === focusId.value || ids.has(event.event_id) : !hiddenTypes.value.length || event.diary_id === props.diaryId || ids.has(event.event_id))
})
const connections = computed(() => relations.value.filter(edge => [edge.source_event_id, edge.target_event_id].includes(selectedEventId.value)).flatMap(edge => {
  const outgoing = edge.source_event_id === selectedEventId.value
  const event = eventMap.value.get(outgoing ? edge.target_event_id : edge.source_event_id)
  return event ? [{ edge, event, outgoing }] : []
}))
const relationColor = (edge: GraphRelation) => ({ '后续事件': '#a85d36', '提及事件': '#53796c', '引发事件': '#8c6b9e' }[edge.relation_type])
const nodeRelated = (id: string) => {
  if (selectedRelation.value) return [selectedRelation.value.source_event_id, selectedRelation.value.target_event_id].includes(id)
  return !selectedEventId.value || id === selectedEventId.value || relations.value.some(edge => [edge.source_event_id, edge.target_event_id].includes(id) && [edge.source_event_id, edge.target_event_id].includes(selectedEventId.value))
}
const drawnEdges = computed(() => graphEdges(visibleRelations.value, Object.fromEntries(visibleEvents.value.map(event => [event.event_id, positions.value[event.event_id]]).filter(([, p]) => !!p)) as GraphPositions, selectedRelation.value?.id).map(edge => ({ ...edge, relation: visibleRelations.value.find(relation => relation.id === edge.id)! })))
const relayout = (reset = false) => {
  positions.value = { ...positions.value, ...layoutGraph(visibleEvents.value, visibleRelations.value, props.diaryId, reset ? {} : positions.value, window.innerWidth <= 600 ? 2 : 4) }
}
const toggleType = async (type: GraphRelation['relation_type']) => {
  hiddenTypes.value = hiddenTypes.value.includes(type) ? hiddenTypes.value.filter(item => item !== type) : [...hiddenTypes.value, type]
  closePanel(); selectedRelation.value = null; selectedEventId.value = ''
  await nextTick(); fit(); persist()
}
const focusEvent = async () => {
  if (!selectedEvent.value) return
  if (!returnView.value) returnView.value = { positions: Object.fromEntries(Object.entries(positions.value).map(([id, point]) => [id, { x: point.x, y: point.y }])), camera: { ...camera.value }, hiddenTypes: [...hiddenTypes.value] }
  focusId.value = selectedEvent.value.event_id; hiddenTypes.value = []; closePanel()
  positions.value = layoutGraph([selectedEvent.value, ...visibleEvents.value.filter(event => event.event_id !== selectedEventId.value)], visibleRelations.value, selectedEvent.value.diary_id, {}, window.innerWidth <= 600 ? 2 : 4)
  await nextTick(); fit(); persist()
}
const restoreGraph = () => {
  focusId.value = ''; closePanel(); selectedRelation.value = null; selectedEventId.value = ''
  if (returnView.value) { positions.value = returnView.value.positions; camera.value = returnView.value.camera; hiddenTypes.value = returnView.value.hiddenTypes; returnView.value = null }
  relayout(); persist()
}
const evidenceSides = computed(() => selectedRelation.value ? (['source', 'target'] as const).map(side => {
  const r = selectedRelation.value!
  const event = eventMap.value.get(side === 'source' ? r.source_event_id : r.target_event_id)
  const ids = new Set((side === 'source' ? r.source_points : r.target_points).map(point => point.point_id))
  return { label: side === 'source' ? '起点依据' : '终点依据', event, points: event?.points.filter(point => ids.has(point.id)) || [] }
}) : [])
const cacheKey = () => `diary-graph-v2:${auth.user?.id || 'user'}:${props.diaryId}`
const persist = () => {
  try { sessionStorage.setItem(cacheKey(), JSON.stringify({ focusId: focusId.value, returnView: returnView.value, hiddenTypes: hiddenTypes.value, rootRunId, positions: positions.value, camera: camera.value, selectedEventId: selectedEventId.value, expandedIds: [...expandedIds] })) } catch { /* 存储不可用时保留当前会话内状态 */ }
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
const load = async (refresh = false) => {
  if (loading.value) return
  const token = ++generation
  loading.value = true; error.value = ''
  try {
    const data = await api<DiaryGraphResult>(`/graph/diaries/${props.diaryId}`)
    if (token !== generation) return
    events.value = []; relations.value = []; closePanel(); selectedRelation.value = null
    if (refresh || !data.run || (rootRunId && rootRunId !== data.run.id)) { positions.value = {}; expandedIds.clear(); savedView = false; selectedEventId.value = ''; focusId.value = ''; returnView.value = null; hiddenTypes.value = [] }
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
const home = () => {
  if (focusId.value) restoreGraph()
  const first = events.value.find(event => event.diary_id === props.diaryId) || events.value[0]
  if (!first || !viewport.value) return
  const position = positions.value[first.event_id]
  camera.value = { x: viewport.value.clientWidth / 2 - position.x, y: 100 - position.y, scale: 1 }
}
const fit = (overview = false) => {
  if (!viewport.value || !visibleEvents.value.length) return
  const boxes = [...visibleEvents.value.map(event => nodeBox(positions.value[event.event_id])),
    ...drawnEdges.value.map(edge => edge.bounds),
    ...drawnEdges.value.flatMap(edge => edge.label ? [{ x: edge.label.x - 52, y: edge.label.y - 20, width: 104, height: 40 }] : [])]
  const minX = Math.min(...boxes.map(p => p.x)), minY = Math.min(...boxes.map(p => p.y))
  const width = Math.max(...boxes.map(p => p.x + p.width)) - minX, height = Math.max(...boxes.map(p => p.y + p.height)) - minY
  const scale = Math.max(overview ? .08 : .55, Math.min(1, (viewport.value.clientWidth - 40) / width, (viewport.value.clientHeight - 100) / height))
  camera.value = { x: viewport.value.clientWidth / 2 - (minX + width / 2) * scale, y: 55 - minY * scale, scale }

}
const zoom = (factor: number, x = (viewport.value?.clientWidth || 0) / 2, y = (viewport.value?.clientHeight || 0) / 2) => {
  const previous = camera.value, scale = Math.min(2, Math.max(0.08, previous.scale * factor)), ratio = scale / previous.scale
  camera.value = { x: x - (x - previous.x) * ratio, y: y - (y - previous.y) * ratio, scale }
}
const pointers = new Map<number, { x: number; y: number }>()
let dragging = false
const guardDragClick = (event: MouseEvent) => { if (dragging) { event.preventDefault(); event.stopPropagation(); dragging = false } }
const pointerDown = (e: PointerEvent) => {
  if (e.button !== 0) return
  if (!pointers.size) dragging = false
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
}
const pointerMove = (e: PointerEvent) => {
  const previous = pointers.get(e.pointerId)
  if (!previous) return
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
const pointerUp = (e: PointerEvent) => { pointers.delete(e.pointerId); persist() }
const wheelZoom = (e: WheelEvent) => { const rect = viewport.value!.getBoundingClientRect(); zoom(Math.exp(-e.deltaY * 0.002), e.clientX - rect.left, e.clientY - rect.top) }
const openPanel = async () => { if (!panelOpen.value) restoreFocus = document.activeElement as HTMLElement; expanded.value = false; panelOpen.value = true; await nextTick(); panel.value?.focus() }
const trapFocus = (event: KeyboardEvent) => {
  const elements = panel.value?.querySelectorAll<HTMLElement>('button, a, summary, [tabindex="0"]')
  if (!elements?.length) return
  const first = elements[0], last = elements[elements.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
const closePanel = () => { panelOpen.value = false; restoreFocus?.focus(); restoreFocus = null }
const selectEvent = (event: GraphEvent) => {
  if (!visibleEvents.value.some(node => node.event_id === event.event_id)) { restoreGraph(); hiddenTypes.value = []; relayout() }
  if (!positions.value[event.event_id]) relayout()
  selectedEventId.value = event.event_id; selectedRelation.value = null; expandMessage.value = ''
  const position = positions.value[event.event_id]
  camera.value = { x: (viewport.value?.clientWidth || 0) / 2 - position.x, y: 100 - position.y, scale: 1 }
  void openPanel(); persist()
}
const selectRelation = (relation: GraphRelation) => { selectedRelation.value = relation; selectedEventId.value = ''; void openPanel() }
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
const startSheetDrag = (e: PointerEvent) => { sheetStart.value = e.clientY; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId) }
const sheetEnd = (e: PointerEvent) => { if (sheetStart.value !== null) { const delta = e.clientY - sheetStart.value; if (delta < -30) expanded.value = true; if (delta > 30) { if (expanded.value) expanded.value = false; else closePanel() } } sheetStart.value = null }
const visitSource = () => { persist(); closePanel(); if (selectedEvent.value) emit('source', selectedEvent.value.event_id, selectedEvent.value.diary_id) }
watch(() => props.visible, async visible => {
  if (!visible) { closePanel(); persist(); return }
  if (!loaded) await load()
})
watch(() => props.revision, () => { if (loaded) void load(true) })
onMounted(async () => {
  try {
    const cached = JSON.parse(sessionStorage.getItem(cacheKey()) || 'null')
    if (cached?.camera && cached?.positions) { focusId.value = cached.focusId || ''; returnView.value = cached.returnView || null; hiddenTypes.value = (cached.hiddenTypes || []).filter((type: GraphRelation['relation_type']) => relationTypes.includes(type)); rootRunId = cached.rootRunId || null; positions.value = cached.positions; camera.value = cached.camera; selectedEventId.value = cached.selectedEventId || ''; for (const id of cached.expandedIds || []) expandedIds.add(id); savedView = true }
  } catch { /* 无缓存时正常加载 */ }
  if (props.visible && !loaded) await load()
})
onBeforeUnmount(() => { generation++; persist() })
</script>

<style scoped>
.graph-canvas {
  background-color: #f7f5ef;
  background-image: radial-gradient(#b7ad982b 1px, transparent 1px);
  background-size: 22px 22px;
}
.graph-node { transition: opacity .15s; }
.graph-node-selected .graph-node-circle { outline: 2px solid #a84d28; outline-offset: 4px; }
.graph-node-muted { opacity: .35; }
@media (prefers-reduced-motion: reduce) { .graph-node { transition: none; } }
</style>
