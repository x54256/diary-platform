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
      <article
        v-for="action in actions"
        :key="action.id"
        class="rounded-xl border border-neutral-200 bg-white p-3 shadow-sm"
      >
        <div class="flex items-start gap-3">
          <input
            type="checkbox"
            class="mt-1 h-5 w-5 shrink-0 accent-primary-600"
            :checked="action.status === 'completed'"
            :disabled="savingId === action.id"
            @change="toggleCompletion(action)"
          />
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-2">
              <input
                v-model="action.title"
                class="min-w-0 flex-1 border-0 bg-transparent p-0 text-[15px] font-medium text-neutral-800 focus:ring-0"
                aria-label="行动名称"
                @blur="saveTitle(action)"
              />
              <button type="button" class="shrink-0 text-xs text-red-500" @click="removeAction(action)">删除</button>
            </div>
            <div class="mt-1 text-xs text-neutral-500">
              {{ scheduleSummary(action) }}
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

    <div v-if="syncOpen" class="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center">
      <section class="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-4 sm:rounded-2xl">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-base font-semibold text-neutral-800">同步到日程</h3>
          <button type="button" class="text-sm text-neutral-500" @click="syncOpen = false">关闭</button>
        </div>
        <div v-if="syncCandidates.length === 0" class="py-6 text-center text-sm text-neutral-400">没有待同步行动项</div>
        <div v-else class="space-y-4">
          <div v-for="candidate in syncCandidates" :key="candidate.action.id" class="rounded-xl border border-neutral-200 p-3">
            <label class="flex items-center gap-2 text-sm text-neutral-800">
              <input v-model="candidate.selected" type="checkbox" class="h-4 w-4 accent-primary-600" />
              {{ candidate.action.title }}
            </label>
            <div v-if="candidate.selected" class="mt-3 grid grid-cols-2 gap-2">
              <label class="col-span-2 text-xs text-neutral-500">日程名称
                <input v-model="candidate.form.title" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
              </label>
              <label class="text-xs text-neutral-500">开始日期
                <input v-model="candidate.form.start_date" type="date" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
              </label>
              <label class="flex items-end gap-2 pb-2 text-xs text-neutral-600">
                <input v-model="candidate.form.is_all_day" type="checkbox" class="h-4 w-4 accent-primary-600" /> 全天
              </label>
              <label v-if="!candidate.form.is_all_day" class="text-xs text-neutral-500">开始时间
                <input v-model="candidate.form.start_time" type="time" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
              </label>
              <label v-if="!candidate.form.is_all_day" class="text-xs text-neutral-500">结束时间
                <input v-model="candidate.form.end_time" type="time" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
              </label>
              <label class="col-span-2 text-xs text-neutral-500">循环规则
                <select v-model="candidate.form.recurrence_type" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm">
                  <option value="NONE">不循环</option>
                  <option value="DAILY">每天</option>
                  <option value="WEEKLY">每周</option>
                  <option value="MONTHLY_DATE">每月指定日期</option>
                  <option value="MONTHLY_NTH_WEEKDAY">每月第 N 个星期几</option>
                  <option value="YEARLY">每年</option>
                  <option value="WORKDAY">工作日</option>
                  <option value="REST_DAY">休息日</option>
                </select>
              </label>
              <div v-if="candidate.form.recurrence_type === 'WEEKLY'" class="col-span-2">
                <span class="text-xs text-neutral-500">每周日期</span>
                <div class="mt-1 flex flex-wrap gap-2">
                  <label v-for="day in weekDays" :key="day.value" class="flex items-center gap-1 text-xs text-neutral-600">
                    <input v-model="candidate.form.weekdays" :value="day.value" type="checkbox" class="h-4 w-4 accent-primary-600" />{{ day.label }}
                  </label>
                </div>
              </div>
              <label v-if="candidate.form.recurrence_type === 'MONTHLY_DATE'" class="col-span-2 text-xs text-neutral-500">每月日期
                <input v-model.number="candidate.form.month_day" type="number" min="1" max="31" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
              </label>
              <div v-if="candidate.form.recurrence_type === 'YEARLY'" class="col-span-2 grid grid-cols-2 gap-2">
                <label class="text-xs text-neutral-500">月份
                  <input v-model.number="candidate.form.recurrence_month" type="number" min="1" max="12" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
                </label>
                <label class="text-xs text-neutral-500">日期
                  <input v-model.number="candidate.form.month_day" type="number" min="1" max="31" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
                </label>
              </div>
              <div v-if="candidate.form.recurrence_type === 'MONTHLY_NTH_WEEKDAY'" class="col-span-2 grid grid-cols-2 gap-2">
                <label class="text-xs text-neutral-500">第几周
                  <input v-model.number="candidate.form.nth_week" type="number" min="1" max="5" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
                </label>
                <label class="text-xs text-neutral-500">星期几（0=周日）
                  <input v-model.number="candidate.form.nth_weekday" type="number" min="0" max="6" class="mt-1 w-full rounded-lg border border-neutral-300 px-2 py-2 text-sm" />
                </label>
              </div>
            </div>
          </div>
          <p v-if="syncError" class="text-sm text-red-500">{{ syncError }}</p>
          <button type="button" class="w-full rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white disabled:opacity-50" :disabled="syncing" @click="submitSync">
            {{ syncing ? '同步中...' : '确认同步' }}
          </button>
        </div>
      </section>
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
const weekDays = [
  { value: 1, label: '一' }, { value: 2, label: '二' }, { value: 3, label: '三' },
  { value: 4, label: '四' }, { value: 5, label: '五' }, { value: 6, label: '六' }, { value: 0, label: '日' },
]

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
      },
    }))
  syncOpen.value = true
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
      body: { items: selected.map(item => ({ action_id: item.action.id, schedule: item.form })) },
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
