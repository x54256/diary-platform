<template>
  <section class="flex-1 min-h-0 overflow-y-auto px-4 py-3 pb-24">
    <div class="flex items-center justify-between mb-3">
      <div>
        <h2 class="text-base font-semibold text-neutral-800">行动</h2>
        <p class="mt-0.5 text-xs text-neutral-400">后续计划与可行动建议整理后的独立行动项</p>
      </div>
      <button
        type="button"
        class="rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        :disabled="loading || !actions.some(item => item.schedule.status !== 'synced')"
        @click="openSync"
      >同步</button>
    </div>

    <div v-if="error" class="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{{ error }}</div>
    <div v-if="loading" class="flex justify-center py-12 text-sm text-neutral-400">加载中...</div>
    <div v-else-if="actions.length === 0" class="rounded-xl border border-dashed border-neutral-300 px-4 py-10 text-center text-sm text-neutral-400">
      本篇日记没有可执行的行动项
    </div>
    <div v-else class="space-y-3">
      <div v-for="action in actions" :key="action.id" class="relative overflow-hidden rounded-xl">
        <button
          type="button"
          class="absolute inset-y-0 right-0 flex w-[76px] items-center justify-center bg-red-500 text-sm font-medium text-white"
          aria-label="删除行动"
          @click="removeAction(action); swipeOpenId = null"
        >删除</button>
        <article
          class="relative z-10 rounded-xl border border-neutral-200 bg-white p-3 shadow-sm transition-transform duration-200 touch-pan-y"
          :class="action.status === 'completed' ? 'bg-neutral-50' : ''"
          :style="{ transform: cardTransform(action.id) }"
          @touchstart="startSwipe(action.id, $event)"
          @touchmove="moveSwipe(action.id, $event)"
          @touchend="endSwipe(action.id)"
          @touchcancel="cancelSwipe"
        >
          <div class="flex items-start gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-start gap-2">
                <input
                  v-model="action.title"
                  class="min-w-0 flex-1 border-0 bg-transparent p-0 text-base font-medium text-neutral-800 focus:ring-0"
                  :class="action.status === 'completed' ? 'line-through' : ''"
                  aria-label="行动名称"
                  @blur="saveTitle(action)"
                />
                <button
                  type="button"
                  class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold"
                  :class="action.status === 'completed' ? 'border-[#007aff] text-[#007aff]' : 'border-[#ff9500] text-[#ff9500]'"
                  :disabled="savingId === action.id"
                  :aria-label="action.status === 'completed' ? '取消完成' : '标记完成'"
                  @touchstart.stop
                  @touchmove.stop
                  @touchend.stop
                  @click.stop="completeAction(action)"
                >{{ action.status === 'completed' ? '✓' : '' }}</button>
              </div>
              <div class="mt-1 text-xs text-neutral-500">
                <span v-if="action.schedule.status === 'synced'">{{ scheduleSummary(action) }}</span>
                <span class="ml-1 rounded-full px-1.5 py-0.5" :class="statusClass(action.schedule.status)">{{ statusLabel(action.schedule.status) }}</span>
              </div>
              <p v-if="action.recurrence_type !== 'NONE'" class="mt-1 text-xs text-neutral-400">循环行动：首次实例完成后视为已开始落实</p>
              <details v-if="sourceExcerpts(action).length" class="mt-2 text-xs text-neutral-500">
                <summary class="cursor-pointer select-none">查看原文摘录</summary>
                <ul class="mt-1 space-y-1 pl-4 list-disc">
                  <li v-for="(excerpt, index) in sourceExcerpts(action)" :key="`${action.id}-source-${index}`">{{ excerpt }}</li>
                </ul>
              </details>
            </div>
          </div>
        </article>
      </div>
    </div>

    <div v-if="syncOpen" class="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center">
      <section class="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl bg-white sm:rounded-2xl">
        <div class="flex shrink-0 items-center justify-between border-b border-neutral-200 px-5 py-4">
          <h3 class="text-base font-semibold text-neutral-800">同步到日程</h3>
          <button type="button" class="text-sm text-neutral-500" @click="syncOpen = false">关闭</button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div v-if="syncCandidates.length === 0" class="py-6 text-center text-sm text-neutral-400">没有待同步行动项</div>
          <template v-else>
            <button type="button" class="mb-3 flex w-full items-center justify-between rounded-xl bg-neutral-100 px-4 py-3 text-base text-neutral-700" @click="toggleSelectAll">
              <span class="flex items-center gap-3">
                <span class="flex h-5 w-5 items-center justify-center rounded border-2 text-sm" :class="allSelected ? 'border-primary-600 bg-primary-600 text-white' : someSelected ? 'border-primary-600 bg-primary-600 text-white' : 'border-neutral-300 bg-white'">{{ allSelected ? '✓' : someSelected ? '−' : '' }}</span>
                <span>全选</span>
              </span>
              <span class="text-sm text-neutral-500">已选 {{ selectedCount }} 项</span>
            </button>
            <div class="space-y-3">
              <div v-for="candidate in syncCandidates" :key="candidate.action.id" class="overflow-hidden rounded-xl border border-neutral-200">
                <button type="button" class="flex w-full items-start gap-3 p-4 text-left" @click="toggleCandidate(candidate.action.id)">
                  <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border-2 text-sm" :class="candidate.selected ? 'border-primary-600 bg-primary-600 text-white' : 'border-neutral-300 bg-white'" @click.stop="candidate.selected = !candidate.selected">{{ candidate.selected ? '✓' : '' }}</span>
                  <span class="min-w-0 flex-1">
                    <span class="block break-words text-base font-medium text-neutral-800">{{ candidate.action.title }}</span>
                    <span class="mt-1 block text-sm text-neutral-500">{{ candidate.form.start_date }} · {{ candidate.form.is_all_day ? '全天' : `${candidate.form.start_time || '--:--'}-${candidate.form.end_time || '--:--'}` }} · {{ recurrenceSummary(candidate.form) }}</span>
                  </span>
                  <span class="shrink-0 text-neutral-400">{{ expandedSyncId === candidate.action.id ? '收起 ▲' : '编辑 ▼' }}</span>
                </button>
                <div v-if="expandedSyncId === candidate.action.id" class="space-y-3 border-t border-neutral-200 px-3 py-3">
                  <label class="flex min-w-0 items-center gap-3">
                    <span class="w-16 shrink-0 text-base font-medium text-neutral-700">名称：</span>
                    <input v-model="candidate.form.title" class="box-border min-w-0 w-0 max-w-full flex-1 rounded-xl bg-neutral-100 px-3 py-2.5 text-base outline-none ring-primary-600 focus:ring-2" />
                  </label>
                  <div class="flex min-w-0 items-center gap-3">
                    <label class="flex min-w-0 flex-1 items-center gap-3">
                      <span class="w-16 shrink-0 text-base font-medium text-neutral-700">日期：</span>
                      <input v-model="candidate.form.start_date" type="date" class="box-border min-w-0 w-0 max-w-full flex-1 rounded-xl bg-neutral-100 px-3 py-2.5 text-base outline-none ring-primary-600 focus:ring-2" />
                    </label>
                    <div class="flex shrink-0 items-center gap-2">
                      <span class="text-base font-medium text-neutral-700">全天</span>
                      <button type="button" role="switch" :aria-checked="candidate.form.is_all_day" class="relative h-7 w-12 shrink-0 rounded-full transition-colors" :class="candidate.form.is_all_day ? 'bg-primary-600' : 'bg-neutral-300'" @click="candidate.form.is_all_day = !candidate.form.is_all_day">
                        <span class="absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform" :class="candidate.form.is_all_day ? 'translate-x-5' : 'translate-x-0'" />
                      </button>
                    </div>
                  </div>
                  <div v-if="!candidate.form.is_all_day" class="grid min-w-0 grid-cols-2 gap-2">
                    <label class="block min-w-0"><span class="mb-1 block text-sm font-medium text-neutral-700">开始时间：</span><input v-model="candidate.form.start_time" type="time" class="box-border min-w-0 w-full max-w-full rounded-xl bg-neutral-100 px-2 py-2.5 text-base outline-none ring-primary-600 focus:ring-2" /></label>
                    <label class="block min-w-0"><span class="mb-1 block text-sm font-medium text-neutral-700">结束时间：</span><input v-model="candidate.form.end_time" type="time" class="box-border min-w-0 w-full max-w-full rounded-xl bg-neutral-100 px-2 py-2.5 text-base outline-none ring-primary-600 focus:ring-2" /></label>
                  </div>
                  <div>
                    <span class="mb-2 block w-16 text-base font-medium text-neutral-700">重复：</span>
                    <div class="grid grid-cols-4 gap-1 rounded-xl bg-neutral-100 p-1">
                      <button v-for="option in recurrenceOptions" :key="option.value" type="button" class="min-w-0 rounded-lg px-1 py-2 text-sm font-medium" :class="isRecurrenceSelected(candidate.form, option.value) ? 'bg-white text-primary-600 shadow-sm' : 'text-neutral-500'" @click="selectRecurrence(candidate.form, option.value, candidate.action.id)">{{ option.label }}</button>
                    </div>
                    <p v-if="candidate.form.customConfigured" class="mt-2 text-sm text-neutral-500">{{ recurrenceDescription(candidate.form) }}</p>
                  </div>
                  <div v-if="candidate.form.recurrence_type !== 'NONE'" class="space-y-2">
                    <span class="block text-base font-medium text-neutral-700">结束</span>
                    <div class="grid grid-cols-2 gap-2">
                      <button type="button" class="rounded-xl border p-2.5 text-sm" :class="!candidate.form.recurrence_until ? 'border-primary-600 bg-blue-50 text-primary-600' : 'border-neutral-200'" @click="candidate.form.recurrence_until = ''; candidate.form.recurrence_count = null">永久</button>
                      <button type="button" class="rounded-xl border p-2.5 text-sm" :class="candidate.form.recurrence_until ? 'border-primary-600 bg-blue-50 text-primary-600' : 'border-neutral-200'" @click="candidate.form.recurrence_until = candidate.form.recurrence_until || dateAfter(candidate.form.start_date, 30); candidate.form.recurrence_count = null">截止日期</button>
                    </div>
                    <input v-if="candidate.form.recurrence_until" v-model="candidate.form.recurrence_until" :min="candidate.form.start_date" type="date" class="box-border min-w-0 w-full rounded-xl bg-neutral-100 px-3 py-2.5 text-base" />
                    <label v-else class="flex items-center gap-2 text-sm text-neutral-600"><span>重复次数</span><input v-model.number="candidate.form.recurrence_count" min="1" type="number" placeholder="永久" class="w-20 rounded-lg bg-neutral-100 p-2 text-base" /></label>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
        <div class="shrink-0 border-t border-neutral-200 bg-white px-5 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3">
          <p v-if="syncError" class="mb-2 text-sm text-red-500">{{ syncError }}</p>
          <button type="button" class="w-full rounded-xl bg-primary-600 py-3 text-base font-medium text-white disabled:opacity-50" :disabled="syncing || syncCandidates.length === 0" @click="submitSync">
            {{ syncing ? '同步中...' : '确认同步' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="customOpen" class="fixed inset-0 z-[60] flex items-end bg-black/35" @click.self="cancelCustom">
      <form class="max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-white pb-[calc(1rem+env(safe-area-inset-bottom))]" @submit.prevent="confirmCustom">
        <div class="flex items-center justify-between border-b border-neutral-200 px-5 py-4"><h2 class="text-lg font-semibold">自定义重复</h2><button type="button" class="text-sm text-neutral-500" @click="cancelCustom">关闭</button></div>
        <div class="space-y-3 px-4 py-4">
          <div class="rounded-2xl border border-neutral-200 bg-neutral-50">
            <div class="flex items-center justify-between border-b border-neutral-200 px-4 py-3"><span class="text-base font-medium">频率</span><select :value="customForm.recurrence_type.startsWith('MONTHLY') ? 'MONTH' : customForm.recurrence_type" class="bg-transparent text-right text-base text-neutral-500 outline-none" @change="setCustomFrequency(($event.target as HTMLSelectElement).value)"><option value="DAILY">天</option><option value="WEEKLY">周</option><option value="MONTH">月</option></select></div>
            <label class="flex items-center justify-between px-4 py-3"><span class="text-base font-medium">每</span><input v-model.number="customForm.interval" min="1" required type="number" class="w-16 rounded-lg bg-white p-2 text-center text-base shadow-sm" /></label>
          </div>
          <p class="px-1 text-sm text-neutral-500">{{ recurrenceDescription(customForm) }}</p>
          <div v-if="customForm.recurrence_type === 'WEEKLY'" class="rounded-2xl border border-neutral-200 px-4 py-3"><p class="mb-2 text-base font-medium">选择星期</p><div class="divide-y divide-neutral-100"><button v-for="day in weekDays" :key="day.value" type="button" class="flex w-full items-center justify-between py-2.5 text-left text-base" @click="toggleWeekday(customForm, day.value)"><span>星期{{ day.label }}</span><span :class="customForm.weekdays.includes(day.value) ? 'text-primary-600' : 'text-neutral-300'">{{ customForm.weekdays.includes(day.value) ? '✓' : '○' }}</span></button></div></div>
          <div v-if="customForm.recurrence_type === 'MONTHLY_DATE' || customForm.recurrence_type === 'MONTHLY_NTH_WEEKDAY'" class="space-y-3"><div class="flex rounded-xl bg-neutral-100 p-1"><button type="button" class="flex-1 rounded-lg py-2 text-sm" :class="customForm.recurrence_type === 'MONTHLY_DATE' ? 'bg-white text-primary-600 shadow-sm' : 'text-neutral-500'" @click="customForm.recurrence_type = 'MONTHLY_DATE'">按日期</button><button type="button" class="flex-1 rounded-lg py-2 text-sm" :class="customForm.recurrence_type === 'MONTHLY_NTH_WEEKDAY' ? 'bg-white text-primary-600 shadow-sm' : 'text-neutral-500'" @click="customForm.recurrence_type = 'MONTHLY_NTH_WEEKDAY'">按第几个星期几</button></div><input v-if="customForm.recurrence_type === 'MONTHLY_DATE'" v-model.number="customForm.month_day" type="number" min="1" max="31" placeholder="每月几号" class="box-border w-full rounded-xl bg-neutral-100 p-3 text-base" /><div v-else class="grid grid-cols-2 gap-2"><select v-model.number="customForm.nth_week" class="rounded-xl bg-neutral-100 p-3 text-base"><option v-for="n in [1,2,3,4,5]" :key="n" :value="n">第{{ n }}个</option></select><select v-model.number="customForm.nth_weekday" class="rounded-xl bg-neutral-100 p-3 text-base"><option v-for="day in weekDays" :key="day.value" :value="day.value">星期{{ day.label }}</option></select></div></div>
          <div class="grid grid-cols-2 gap-3"><button type="button" class="rounded-xl bg-neutral-100 py-3 text-sm font-medium" @click="cancelCustom">取消</button><button type="submit" class="rounded-xl bg-primary-600 py-3 text-sm font-medium text-white">确认</button></div>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { DiaryActionItem } from '~/types'

const props = defineProps<{ diaryId: string; visible?: boolean }>()
const { api } = useApi()
const actions = ref<DiaryActionItem[]>([])
const loading = ref(false)
const error = ref('')
const savingId = ref<string | null>(null)
const syncOpen = ref(false)
const syncing = ref(false)
const syncError = ref('')
const syncCandidates = ref<Array<{ action: DiaryActionItem; selected: boolean; form: any }>>([])
const expandedSyncId = ref<string | null>(null)
const customOpen = ref(false)
const customTargetId = ref<string | null>(null)
const customForm = ref<any>({ recurrence_type: 'DAILY', interval: 1, weekdays: [], month_day: null, nth_week: 1, nth_weekday: 0, customConfigured: true })
const swipeOpenId = ref<string | null>(null)
const swipeStart = ref({ id: '', x: 0, y: 0, offset: 0, horizontal: false })
const swipeOffset = ref(0)
const weekDays = [
  { value: 1, label: '一' }, { value: 2, label: '二' }, { value: 3, label: '三' },
  { value: 4, label: '四' }, { value: 5, label: '五' }, { value: 6, label: '六' }, { value: 0, label: '日' },
]
const recurrenceOptions = [
  { value: 'NONE', label: '不重复' }, { value: 'DAILY', label: '每天' }, { value: 'WEEKLY', label: '每周' },
  { value: 'MONTHLY_DATE', label: '每月' }, { value: 'YEARLY', label: '每年' }, { value: 'WORKDAY', label: '工作日' },
  { value: 'REST_DAY', label: '休息日' }, { value: 'CUSTOM', label: '自定义' },
] as const

const startSwipe = (id: string, event: TouchEvent) => {
  const target = event.target as HTMLElement | null
  if (target?.closest('button, input, select, textarea, summary')) {
    resetSwipe()
    return
  }
  const touch = event.touches[0]
  swipeOffset.value = swipeOpenId.value === id ? -76 : 0
  swipeStart.value = { id, x: touch.clientX, y: touch.clientY, offset: swipeOffset.value, horizontal: false }
}

const moveSwipe = (id: string, event: TouchEvent) => {
  if (swipeStart.value.id !== id) return
  const touch = event.touches[0]
  const dx = touch.clientX - swipeStart.value.x
  const dy = touch.clientY - swipeStart.value.y
  if (!swipeStart.value.horizontal) {
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 10) return
    if (Math.abs(dy) >= Math.abs(dx)) return
    swipeStart.value.horizontal = true
  }
  if (event.cancelable) event.preventDefault()
  swipeOffset.value = Math.max(-76, Math.min(0, swipeStart.value.offset + dx))
}

const endSwipe = (id: string) => {
  if (swipeStart.value.id !== id) return
  if (swipeStart.value.horizontal) {
    swipeOpenId.value = swipeOffset.value < -38 ? id : null
  }
  swipeOffset.value = swipeOpenId.value === id ? -76 : 0
  swipeStart.value = { id: '', x: 0, y: 0, offset: 0, horizontal: false }
}

const cancelSwipe = () => {
  resetSwipe()
}

const cardTransform = (id: string) => {
  if (swipeStart.value.id === id && swipeStart.value.horizontal) return `translateX(${swipeOffset.value}px)`
  return `translateX(${swipeOpenId.value === id ? -76 : 0}px)`
}

const completeAction = async (action: DiaryActionItem) => {
  resetSwipe()
  await toggleCompletion(action)
}

const resetSwipe = () => {
  swipeOpenId.value = null
  swipeOffset.value = 0
  swipeStart.value = { id: '', x: 0, y: 0, offset: 0, horizontal: false }
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    actions.value = await api<DiaryActionItem[]>(`/diaries/${props.diaryId}/actions`)
  } catch (err: any) {
    error.value = err?.data?.detail || '行动项加载失败'
  } finally {
    loading.value = false
  }
}

const toggleCompletion = async (action: DiaryActionItem) => {
  savingId.value = action.id
  try {
    const updated = await api<DiaryActionItem>(`/diary-actions/${action.id}/completion`, {
      method: 'PUT',
      body: { completed: action.status !== 'completed' },
    })
    Object.assign(action, updated)
  } catch (err: any) {
    error.value = err?.data?.detail || '更新完成状态失败'
  } finally {
    savingId.value = null
  }
}

const saveTitle = async (action: DiaryActionItem) => {
  const title = action.title.trim()
  if (!title) return
  try {
    const updated = await api<DiaryActionItem>(`/diary-actions/${action.id}`, { method: 'PUT', body: { title } })
    Object.assign(action, updated)
  } catch (err: any) {
    error.value = err?.data?.detail || '保存行动名称失败'
  }
}

const removeAction = async (action: DiaryActionItem) => {
  if (!window.confirm('删除行动项？已同步的日程会保留。')) return
  try {
    await api(`/diary-actions/${action.id}`, { method: 'DELETE' })
    actions.value = actions.value.filter(item => item.id !== action.id)
  } catch (err: any) {
    error.value = err?.data?.detail || '删除行动项失败'
  }
}

const openSync = () => {
  syncError.value = ''
  syncCandidates.value = actions.value
    .filter(action => action.schedule.status !== 'synced')
    .map(action => ({
      action,
      selected: action.schedule.status === 'schedule_deleted' ? false : true,
      form: {
        title: action.title,
        is_all_day: action.is_all_day,
        start_date: action.start_date,
        start_time: action.start_time || '',
        end_time: action.end_time || '',
        recurrence_type: action.recurrence_type,
        interval: action.interval || 1,
        weekdays: action.weekdays || [],
        month_day: action.month_day,
        recurrence_month: action.recurrence_month,
        nth_week: action.nth_week,
        nth_weekday: action.nth_weekday,
        recurrence_until: action.recurrence_until,
        recurrence_count: action.recurrence_count,
        customConfigured: action.recurrence_type === 'MONTHLY_NTH_WEEKDAY' || (action.interval || 1) > 1 || (action.recurrence_type === 'WEEKLY' && (action.weekdays || []).length > 1),
      },
    }))
  expandedSyncId.value = null
  syncOpen.value = true
}

const selectedCount = computed(() => syncCandidates.value.filter(item => item.selected).length)
const allSelected = computed(() => syncCandidates.value.length > 0 && selectedCount.value === syncCandidates.value.length)
const someSelected = computed(() => selectedCount.value > 0 && !allSelected.value)
const toggleSelectAll = () => {
  const nextSelected = !allSelected.value
  syncCandidates.value.forEach(item => { item.selected = nextSelected })
}
const toggleCandidate = (id: string) => {
  expandedSyncId.value = expandedSyncId.value === id ? null : id
}
const isRecurrenceSelected = (form: any, type: string) => type === 'CUSTOM' ? form.customConfigured : !form.customConfigured && form.recurrence_type === type
const selectRecurrence = (form: any, type: string, candidateId: string) => {
  if (type === 'CUSTOM') {
    customTargetId.value = candidateId
    customForm.value = { recurrence_type: form.recurrence_type === 'MONTHLY_NTH_WEEKDAY' || form.customConfigured ? form.recurrence_type : 'DAILY', interval: form.interval || 1, weekdays: [...(form.weekdays || [])], month_day: form.month_day, nth_week: form.nth_week || 1, nth_weekday: form.nth_weekday ?? 0, customConfigured: true }
    customOpen.value = true
    return
  }
  form.customConfigured = false
  form.recurrence_type = type
  if (type === 'NONE') { form.recurrence_until = ''; form.recurrence_count = null }
}
const cancelCustom = () => { customOpen.value = false; customTargetId.value = null }
const setCustomFrequency = (value: string) => { customForm.value.recurrence_type = value === 'MONTH' ? 'MONTHLY_DATE' : value }
const toggleWeekday = (form: any, value: number) => { form.weekdays = form.weekdays.includes(value) ? form.weekdays.filter((item: number) => item !== value) : [...form.weekdays, value].sort((a: number, b: number) => a - b) }
const confirmCustom = () => {
  if (customForm.value.interval < 1 || !customTargetId.value) return
  if (customForm.value.recurrence_type === 'WEEKLY' && !customForm.value.weekdays.length) customForm.value.weekdays = [new Date(`${syncCandidates.value.find(item => item.action.id === customTargetId.value)?.form.start_date || new Date().toISOString().slice(0, 10)}T12:00:00`).getDay()]
  if (customForm.value.recurrence_type === 'MONTHLY_DATE' && !customForm.value.month_day) customForm.value.month_day = Number((syncCandidates.value.find(item => item.action.id === customTargetId.value)?.form.start_date || new Date().toISOString().slice(0, 10)).slice(8, 10))
  const target = syncCandidates.value.find(item => item.action.id === customTargetId.value)
  if (target) Object.assign(target.form, customForm.value, { customConfigured: true })
  cancelCustom()
}
const dateAfter = (value: string, days: number) => { const date = new Date(`${value}T12:00:00`); date.setDate(date.getDate() + days); return date.toISOString().slice(0, 10) }
const recurrenceDescription = (form: any) => {
  const count = Number(form.interval || 1); const number = count === 1 ? '一' : count === 2 ? '两' : String(count)
  if (form.recurrence_type === 'DAILY') return `每${number}天重复一次。`
  if (form.recurrence_type === 'YEARLY') return `每${number}年重复一次。`
  if (form.recurrence_type === 'WEEKLY') return `每${number}周的${(form.weekdays || []).map((value: number) => `星期${weekDays.find(day => day.value === value)?.label}`).join('、') || '指定星期'}重复。`
  if (form.recurrence_type === 'MONTHLY_DATE') return `每${number}个月的${form.month_day || ''}号重复。`
  if (form.recurrence_type === 'MONTHLY_NTH_WEEKDAY') return `每${number}个月的第${form.nth_week || 1}个星期${weekDays.find(day => day.value === form.nth_weekday)?.label || ''}重复。`
  return form.recurrence_type === 'WORKDAY' ? '工作日' : form.recurrence_type === 'REST_DAY' ? '休息日' : '不重复'
}
const recurrenceSummary = (form: any) => {
  const count = Number(form.interval || 1)
  const number = count === 1 ? '一' : count === 2 ? '两' : String(count)
  if (form.recurrence_type === 'NONE') return '不重复'
  if (form.recurrence_type === 'DAILY') return count === 1 ? '每天' : `每${number}天`
  if (form.recurrence_type === 'WEEKLY') {
    const labels = (form.weekdays || []).map((value: number) => weekDays.find(day => day.value === value)?.label).filter(Boolean)
    return labels.length ? `每${number}周（${labels.join('、')}）` : `每${number}周`
  }
  if (form.recurrence_type === 'MONTHLY_DATE') return `每${number}个月${form.month_day || ''}日`
  if (form.recurrence_type === 'MONTHLY_NTH_WEEKDAY') return `每${number}个月第${form.nth_week || 1}个星期${weekDays.find(day => day.value === form.nth_weekday)?.label || ''}`
  if (form.recurrence_type === 'YEARLY') return `每${number}年${form.recurrence_month || ''}月${form.month_day || ''}日`
  if (form.recurrence_type === 'WORKDAY') return '工作日'
  if (form.recurrence_type === 'REST_DAY') return '休息日'
  return '不重复'
}

const submitSync = async () => {
  const selected = syncCandidates.value.filter(item => item.selected)
  if (!selected.length) {
    syncError.value = '请至少选择一个行动项'
    return
  }
  syncing.value = true
  syncError.value = ''
  try {
    await api(`/diaries/${props.diaryId}/actions/sync`, {
      method: 'POST',
      body: { items: selected.map(item => ({
        action_id: item.action.id,
        schedule: {
          title: item.form.title,
          is_all_day: item.form.is_all_day,
          start_date: item.form.start_date,
          start_time: item.form.is_all_day ? null : (item.form.start_time || null),
          end_time: item.form.is_all_day ? null : (item.form.end_time || null),
          recurrence_type: item.form.recurrence_type,
          interval: item.form.interval || 1,
          weekdays: item.form.weekdays || [],
          month_day: item.form.month_day ?? null,
          recurrence_month: item.form.recurrence_month ?? null,
          nth_week: item.form.nth_week ?? null,
          nth_weekday: item.form.nth_weekday ?? null,
          recurrence_until: item.form.recurrence_type === 'NONE' ? null : (item.form.recurrence_until || null),
          recurrence_count: item.form.recurrence_type === 'NONE' ? null : (item.form.recurrence_count || null),
        },
      })) },
    })
    syncOpen.value = false
    await load()
  } catch (err: any) {
    syncError.value = err?.data?.detail || '同步失败，请检查日程填写'
  } finally {
    syncing.value = false
  }
}

const scheduleSummary = (action: DiaryActionItem) => {
  const time = action.is_all_day ? '全天' : `${action.start_time || '--:--'}-${action.end_time || '--:--'}`
  return `${action.start_date} ${time}`
}
const sourceExcerpts = (action: DiaryActionItem) => {
  const refs = action.source_refs || {}
  const values = [
    ...(Array.isArray(refs.plans) ? refs.plans : []),
    ...(Array.isArray(refs.analysis_sources) ? refs.analysis_sources : []),
  ]
  return values
    .map((item: any) => typeof item === 'string' ? item : item?.text)
    .filter((text: any): text is string => typeof text === 'string' && text.trim())
}
const statusLabel = (status: DiaryActionItem['schedule']['status']) => ({ unsynced: '未同步', synced: '已同步', schedule_deleted: '日程已删除' }[status])
const statusClass = (status: DiaryActionItem['schedule']['status']) => ({
  unsynced: 'bg-neutral-100 text-neutral-500',
  synced: 'bg-green-50 text-green-600',
  schedule_deleted: 'bg-amber-50 text-amber-600',
}[status])

onMounted(load)
watch(() => props.diaryId, load)
watch(() => props.visible, (visible) => {
  if (visible) load()
})
</script>
