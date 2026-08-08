<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-semibold text-neutral-900 sm:text-2xl">搜索索引重建</h1>
      <p class="mt-1 text-sm text-neutral-500">按日记日期范围，为全体用户重建关键词片段和三层语义向量。</p>
    </div>

    <section class="max-w-2xl rounded border border-neutral-200 bg-white p-5">
      <div class="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
        重建仅补齐或更新内容变化的索引；需要生成向量时会调用 embedding 模型并产生费用。
      </div>
      <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-sm text-neutral-700">开始日期</span>
          <input v-model="form.start_date" type="date" class="h-11 w-full rounded border border-neutral-300 px-3 text-base sm:text-sm">
        </label>
        <label class="block">
          <span class="mb-1 block text-sm text-neutral-700">结束日期</span>
          <input v-model="form.end_date" type="date" class="h-11 w-full rounded border border-neutral-300 px-3 text-base sm:text-sm">
        </label>
      </div>
      <p v-if="error" class="mt-3 text-sm text-red-600">{{ error }}</p>
      <button class="mt-5 h-10 rounded bg-neutral-900 px-4 text-sm text-white disabled:opacity-60" :disabled="creating || hasActiveJob" @click="createJob">
        {{ creating ? '创建中…' : hasActiveJob ? '已有任务执行中' : '开始重建' }}
      </button>
    </section>

    <section class="overflow-hidden rounded border border-neutral-200 bg-white">
      <div class="flex items-center justify-between border-b border-neutral-200 px-5 py-4">
        <h2 class="text-base font-medium text-neutral-900">重建记录</h2>
        <button class="text-sm text-neutral-500 hover:text-neutral-900" @click="loadJobs">刷新</button>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[760px] text-sm">
          <thead class="bg-neutral-50 text-neutral-500">
            <tr>
              <th class="p-3 text-left">日期范围</th>
              <th class="p-3 text-left">状态</th>
              <th class="p-3 text-right">进度</th>
              <th class="p-3 text-right">成功</th>
              <th class="p-3 text-right">失败</th>
              <th class="p-3 text-left">时间</th>
              <th class="p-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id" class="border-t border-neutral-100">
              <td class="p-3">{{ job.start_date }} ～ {{ job.end_date }}</td>
              <td class="p-3">{{ statusLabel(job.status) }}</td>
              <td class="p-3 text-right">{{ job.processed_events }} / {{ job.total_events }}</td>
              <td class="p-3 text-right text-emerald-700">{{ job.succeeded_events }}</td>
              <td class="p-3 text-right" :class="job.failed_events ? 'text-red-600' : ''">{{ job.failed_events }}</td>
              <td class="p-3">{{ formatTime(job.created_at) }}</td>
              <td class="p-3 text-right">
                <button v-if="job.status === 'queued' || job.status === 'running'" class="text-red-600" @click="cancelJob(job.id)">取消</button>
                <button v-if="job.failure_details?.length" class="ml-3 text-neutral-900 underline" @click="showFailures(job)">失败详情</button>
              </td>
            </tr>
            <tr v-if="!jobs.length"><td colspan="7" class="p-8 text-center text-neutral-500">暂无重建记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selectedFailures.length" class="rounded border border-red-200 bg-red-50 p-5">
      <div class="flex items-center justify-between"><h2 class="text-base font-medium text-red-900">失败详情</h2><button class="text-sm text-red-700" @click="selectedFailures = []">关闭</button></div>
      <ul class="mt-3 space-y-2 text-sm text-red-900"><li v-for="item in selectedFailures" :key="item.event_id"><code>{{ item.event_id }}</code>：{{ item.reason }}</li></ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { formatDateTimeInAppTimeZone } from '~/utils/datetime'

definePageMeta({ layout: 'admin', middleware: 'admin' })

type Failure = { event_id: string; reason: string }
type RebuildJob = {
  id: string; start_date: string; end_date: string; status: 'queued' | 'running' | 'completed' | 'cancelled'
  total_events: number; processed_events: number; succeeded_events: number; failed_events: number
  failure_details: Failure[]; created_at?: string
}

const { api } = useApi()
const form = reactive({ start_date: '', end_date: '' })
const jobs = ref<RebuildJob[]>([])
const creating = ref(false)
const error = ref('')
const selectedFailures = ref<Failure[]>([])
const hasActiveJob = computed(() => jobs.value.some((job) => job.status === 'queued' || job.status === 'running'))

const loadJobs = async () => { jobs.value = await api<RebuildJob[]>('/admin/search-index/rebuild-jobs') }
const createJob = async () => {
  if (!form.start_date || !form.end_date) { error.value = '请选择完整的日期范围'; return }
  if (form.start_date > form.end_date) { error.value = '开始日期不能晚于结束日期'; return }
  if (!window.confirm('确认重建该日期范围内全部用户的关键词片段和语义向量？')) return
  creating.value = true; error.value = ''
  try { await api('/admin/search-index/rebuild', { method: 'POST', body: form }); await loadJobs() }
  catch (cause: any) { error.value = cause?.data?.detail || cause?.message || '创建任务失败' }
  finally { creating.value = false }
}
const cancelJob = async (id: string) => { await api(`/admin/search-index/rebuild-jobs/${id}/cancel`, { method: 'POST' }); await loadJobs() }
const showFailures = (job: RebuildJob) => { selectedFailures.value = job.failure_details || [] }
const formatTime = (value?: string) => value ? formatDateTimeInAppTimeZone(value) || '-' : '-'
const statusLabel = (value: RebuildJob['status']) => ({ queued: '等待中', running: '执行中', completed: '已完成', cancelled: '已取消' }[value])

let poller: ReturnType<typeof setInterval> | undefined
onMounted(async () => { await loadJobs(); poller = window.setInterval(() => { if (hasActiveJob.value) void loadJobs() }, 60000) })
onBeforeUnmount(() => { if (poller) clearInterval(poller) })
</script>
