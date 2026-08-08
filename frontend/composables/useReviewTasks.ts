import { ref, computed } from 'vue'
import type { ReviewSummary, ReviewTask } from '~/types'
import type { FetchOptions } from 'ofetch'

// ───── 模块级单例状态 ─────
const tasks = ref<ReviewTask[]>([])
const reviews = ref<ReviewSummary[]>([])
const loading = ref(false)
const loadError = ref('')
const nextCursor = ref<string | null>(null)
const loadingMore = ref(false)

let apiFn: (<T = any>(url: string, options?: FetchOptions) => Promise<T>) | null = null

const unwrap = <T,>(response: T[] | { items: T[] }) =>
  Array.isArray(response) ? response : response.items
type TaskListResponse = ReviewTask[] | { items: ReviewTask[]; next_cursor?: string | null }

const mergeTasksInternal = (response: TaskListResponse) => {
  const incoming = unwrap(response)
  const existingById = new Map(tasks.value.map((task, index) => [task.id, index]))
  for (const task of incoming) {
    const index = existingById.get(task.id)
    if (index === undefined) tasks.value.unshift(task)
    else Object.assign(tasks.value[index], task)
  }
  nextCursor.value = Array.isArray(response) ? null : response.next_cursor || null
}

const doRefreshTasks = async () => {
  if (!apiFn) return
  try {
    mergeTasksInternal(await apiFn<TaskListResponse>('/review-tasks?limit=100'))
  } catch {
    /* 保留已展示的任务 */
  }
}

const doLoad = async () => {
  if (!apiFn) return
  loading.value = true
  loadError.value = ''
  try {
    const [taskResponse, reviewResponse] = await Promise.all([
      apiFn<TaskListResponse>('/review-tasks?limit=100'),
      apiFn<ReviewSummary[] | { items: ReviewSummary[] }>('/reviews'),
    ])
    tasks.value = unwrap(taskResponse)
    nextCursor.value = Array.isArray(taskResponse) ? null : taskResponse.next_cursor || null
    reviews.value = unwrap(reviewResponse)
  } catch (cause: any) {
    loadError.value = cause?.data?.detail || '任务加载失败'
  } finally {
    loading.value = false
  }
}

const doLoadMoreTasks = async () => {
  if (!apiFn || !nextCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const response = await apiFn<{ items: ReviewTask[]; next_cursor?: string | null }>(
      `/review-tasks?limit=100&cursor=${encodeURIComponent(nextCursor.value)}`,
    )
    const known = new Set(tasks.value.map((item) => item.id))
    tasks.value.push(...response.items.filter((item) => !known.has(item.id)))
    nextCursor.value = response.next_cursor || null
  } catch (cause: any) {
    loadError.value = cause?.data?.detail || '更多任务加载失败'
  } finally {
    loadingMore.value = false
  }
}

const activeTasksComp = computed(() =>
  tasks.value.filter((task) => ['QUEUED', 'RUNNING'].includes(task.status)),
)
const activeTaskCountComp = computed(() => activeTasksComp.value.length)
const pendingStartTasksComp = computed(() =>
  tasks.value.filter((task) => ['PENDING', 'PENDING_START'].includes(task.status)),
)
const failedTasksComp = computed(() =>
  tasks.value.filter((task) => task.status === 'FAILED'),
)
const completedTasksComp = computed(() =>
  tasks.value
    .filter((task) =>
      ['SUCCEEDED', 'COMPLETED', 'SKIPPED_NO_DATA'].includes(task.status),
    )
    .sort((a, b) =>
      (b.completed_at || b.created_at).localeCompare(a.completed_at || a.created_at),
    ),
)

export function useReviewTasks() {
  const { api } = useApi()
  apiFn = api
  return {
    tasks,
    reviews,
    loading,
    loadError,
    nextCursor,
    loadingMore,
    activeTasks: activeTasksComp,
    activeTaskCount: activeTaskCountComp,
    pendingStartTasks: pendingStartTasksComp,
    failedTasks: failedTasksComp,
    completedTasks: completedTasksComp,
    load: doLoad,
    refreshTasks: doRefreshTasks,
    loadMoreTasks: doLoadMoreTasks,
  }
}
