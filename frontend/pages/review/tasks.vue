<template>
  <div class="min-h-dvh bg-[#f6f4ee]">
    <ReviewTopBar :title="creating ? '新建回顾任务' : '回顾任务'" eyebrow="生活编年" show-back>
      <template #right>
        <button v-if="!creating" type="button" class="min-h-11 rounded-full px-3 text-sm font-semibold text-primary-700 transition hover:bg-primary-50" @click="creating = true">新建</button>
      </template>
    </ReviewTopBar>
    <main class="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <ReviewTaskCreateForm v-if="creating" class="max-w-2xl" :reviews="reviews" :tasks="tasks" :submitting="submitting" :error="createError" @submit="createTask" />
      <template v-else>
        <p class="mb-6 text-sm leading-6 text-neutral-500">这里集中处理自动生成、补生成和重新生成的回顾任务。</p>
        <div v-if="loading" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><div v-for="index in 3" :key="index" class="h-36 animate-pulse rounded-3xl bg-white" /></div>
        <ReviewStatusBanner v-else-if="loadError" :title="loadError" action-label="重新加载" tone="error" @action="load" />
        <div v-else class="space-y-8">
          <section v-if="pendingStartTasks.length">
            <h2 class="mb-4 flex items-center gap-3 text-sm font-semibold text-neutral-600"><span class="h-px w-6 bg-primary-400" />待启动 {{ pendingStartTasks.length }} 项</h2>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><ReviewTaskCard v-for="task in pendingStartTasks" :key="task.id" :task="task" :starting="startingId === task.id" @start="startTask" /></div>
          </section>
          <section v-if="activeTasks.length">
            <h2 class="mb-4 flex items-center gap-3 text-sm font-semibold text-neutral-600"><span class="h-px w-6 bg-primary-400" />进行中 {{ activeTasks.length }} 项</h2>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><ReviewTaskCard v-for="task in activeTasks" :key="task.id" :task="task" :starting="startingId === task.id" @start="startTask" /></div>
          </section>
          <section v-if="failedTasks.length">
            <h2 class="mb-4 flex items-center gap-3 text-sm font-semibold text-red-600"><span class="h-px w-6 bg-red-400" />需要处理 {{ failedTasks.length }} 项</h2>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><ReviewTaskCard v-for="task in failedTasks" :key="task.id" :task="task" :retrying="retryingId === task.id" @retry="retryTask" /></div>
          </section>
          <section v-if="completedTasks.length">
            <button type="button" class="flex min-h-11 w-full items-center justify-between text-sm font-semibold text-neutral-600" @click="completedOpen = !completedOpen">
              <span>已完成 {{ completedTasks.length }} 项</span><span>{{ completedOpen ? '收起' : '展开' }}</span>
            </button>
            <div v-if="completedOpen" class="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3"><ReviewTaskCard v-for="task in completedTasks" :key="task.id" :task="task" /></div>
          </section>
          <section v-if="!tasks.length" class="py-16 text-center">
            <p class="text-sm text-neutral-500">还没有回顾任务</p>
            <button type="button" class="mt-5 min-h-11 rounded-xl bg-primary-600 px-5 text-sm font-semibold text-white" @click="creating = true">新建回顾任务</button>
          </section>
          <button v-if="nextCursor" type="button" class="min-h-12 w-full rounded-xl bg-white text-sm font-semibold text-primary-700 disabled:opacity-50" :disabled="loadingMore" @click="loadMore">{{ loadingMore ? '正在加载…' : '加载更早任务' }}</button>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { ReviewSummary, ReviewTask, ReviewType } from '~/types'

definePageMeta({ layout: 'auth', middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const creating = ref(route.query.create === '1')
const loading = ref(true)
const loadError = ref('')
const createError = ref('')
const submitting = ref(false)
const retryingId = ref('')
const startingId = ref('')
const completedOpen = ref(false)
const nextCursor = ref<string | null>(null)
const loadingMore = ref(false)
const tasks = ref<ReviewTask[]>([])
const reviews = ref<ReviewSummary[]>([])
let timer: ReturnType<typeof setInterval> | null = null
const unwrap = <T,>(response: T[] | { items: T[] }) => Array.isArray(response) ? response : response.items
type TaskListResponse = ReviewTask[] | { items: ReviewTask[]; next_cursor?: string | null }

const mergeTasks = (response: TaskListResponse) => {
  const incoming = unwrap(response)
  const existingById = new Map(tasks.value.map((task, index) => [task.id, index]))
  for (const task of incoming) {
    const index = existingById.get(task.id)
    if (index === undefined) tasks.value.unshift(task)
    else Object.assign(tasks.value[index], task)
  }
  nextCursor.value = Array.isArray(response) ? null : response.next_cursor || null
}

const load = async () => {
  loading.value = true; loadError.value = ''
  try {
    const [taskResponse, reviewResponse] = await Promise.all([
      api<TaskListResponse>('/review-tasks?limit=100'), api<ReviewSummary[] | { items: ReviewSummary[] }>('/reviews'),
    ])
    tasks.value = unwrap(taskResponse)
    nextCursor.value = Array.isArray(taskResponse) ? null : taskResponse.next_cursor || null
    reviews.value = unwrap(reviewResponse)
  } catch (cause: any) { loadError.value = cause?.data?.detail || '任务加载失败' } finally { loading.value = false }
}
const refreshTasks = async () => {
  try {
    mergeTasks(await api<TaskListResponse>('/review-tasks?limit=100'))
  } catch {
    // 保留已展示的任务，下一次轮询会自动重试。
  }
}
const loadMore = async () => {
  if (!nextCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const response = await api<{ items: ReviewTask[]; next_cursor?: string | null }>(`/review-tasks?limit=100&cursor=${encodeURIComponent(nextCursor.value)}`)
    const known = new Set(tasks.value.map(item => item.id))
    tasks.value.push(...response.items.filter(item => !known.has(item.id)))
    nextCursor.value = response.next_cursor || null
  } catch (cause: any) { loadError.value = cause?.data?.detail || '更多任务加载失败' } finally { loadingMore.value = false }
}
onMounted(() => {
  void load()
  timer = window.setInterval(() => { if (activeTasks.value.length) void refreshTasks() }, 7000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const pendingStartTasks = computed(() => tasks.value.filter(task => ['PENDING', 'PENDING_START'].includes(task.status)))
const activeTasks = computed(() => tasks.value.filter(task => ['QUEUED', 'RUNNING'].includes(task.status)))
const failedTasks = computed(() => tasks.value.filter(task => task.status === 'FAILED'))
const completedTasks = computed(() => tasks.value.filter(task => ['SUCCEEDED', 'COMPLETED', 'SKIPPED_NO_DATA'].includes(task.status)).sort((a, b) => (b.completed_at || b.created_at).localeCompare(a.completed_at || a.created_at)))
const createTask = async (payload: { review_type: ReviewType; period_start: string }) => {
  submitting.value = true; createError.value = ''
  try {
    const task = await api<ReviewTask>('/review-tasks', { method: 'POST', body: payload })
    tasks.value.unshift(task)
    creating.value = false
  } catch (cause: any) { createError.value = cause?.data?.detail || '任务创建失败，请重试' } finally { submitting.value = false }
}
const retryTask = async (task: ReviewTask) => {
  retryingId.value = task.id
  try {
    const created = await api<ReviewTask>(`/review-tasks/${task.id}/retry`, { method: 'POST' })
    tasks.value.unshift(created)
  } catch (cause: any) { loadError.value = cause?.data?.detail || '重试任务创建失败' } finally { retryingId.value = '' }
}
const startTask = async (task: ReviewTask) => {
  startingId.value = task.id
  try {
    const started = await api<ReviewTask>(`/review-tasks/${task.id}/start`, { method: 'POST' })
    const index = tasks.value.findIndex(item => item.id === task.id)
    if (index >= 0) tasks.value[index] = started
  } catch (cause: any) { loadError.value = cause?.data?.detail || '启动任务失败' } finally { startingId.value = '' }
}
</script>
