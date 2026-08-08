<template>
  <div class="min-h-dvh">
    <ReviewTopBar :title="creating ? '新建回顾任务' : '回顾任务'" show-back>
      <template #right>
        <button v-if="!creating" type="button" class="px-2 text-sm font-medium text-primary-600" @click="creating = true">新建</button>
      </template>
    </ReviewTopBar>
    <main class="w-full px-4 py-4 sm:px-6 lg:px-8">
      <ReviewTaskCreateForm v-if="creating" :reviews="reviews" :tasks="tasks" :submitting="submitting" :error="createError" @submit="createTask" />
      <template v-else>
        <p class="mb-4 text-sm leading-6 text-neutral-500">这里集中处理自动生成、补生成和重新生成的回顾任务。</p>
        <div v-if="loading" class="flex justify-center py-24"><span class="text-sm text-neutral-400">加载中...</span></div>
        <ReviewStatusBanner v-else-if="loadError" :title="loadError" action-label="重新加载" tone="error" @action="load" />
        <div v-else class="space-y-6">
          <section v-if="pendingStartTasks.length">
            <h2 class="mb-3 text-sm font-medium text-neutral-600">待启动 {{ pendingStartTasks.length }} 项</h2>
            <div class="space-y-3"><ReviewTaskCard v-for="task in pendingStartTasks" :key="task.id" :task="task" :starting="startingId === task.id" @start="startTask" /></div>
          </section>
          <section v-if="activeTasks.length">
            <h2 class="mb-3 text-sm font-medium text-neutral-600">进行中 {{ activeTasks.length }} 项</h2>
            <div class="space-y-3"><ReviewTaskCard v-for="task in activeTasks" :key="task.id" :task="task" :starting="startingId === task.id" @start="startTask" /></div>
          </section>
          <section v-if="failedTasks.length">
            <h2 class="mb-3 text-sm font-medium text-red-600">需要处理 {{ failedTasks.length }} 项</h2>
            <div class="space-y-3"><ReviewTaskCard v-for="task in failedTasks" :key="task.id" :task="task" :retrying="retryingId === task.id" @retry="retryTask" /></div>
          </section>
          <section v-if="completedTasks.length">
            <button type="button" class="flex min-h-11 w-full items-center justify-between text-sm font-medium text-neutral-600" @click="completedOpen = !completedOpen">
              <span>已完成 {{ completedTasks.length }} 项</span><span>{{ completedOpen ? '收起' : '展开' }}</span>
            </button>
            <div v-if="completedOpen" class="mt-3 space-y-3"><ReviewTaskCard v-for="task in completedTasks" :key="task.id" :task="task" /></div>
          </section>
          <section v-if="!tasks.length" class="py-16 text-center">
            <p class="text-sm text-neutral-400">还没有回顾任务</p>
            <button type="button" class="mt-5 rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-medium text-white" @click="creating = true">新建回顾任务</button>
          </section>
          <button v-if="nextCursor" type="button" class="min-h-12 w-full rounded-lg border border-neutral-300 bg-white text-sm font-medium text-neutral-700 disabled:opacity-50" :disabled="loadingMore" @click="loadMore">{{ loadingMore ? '正在加载…' : '加载更早任务' }}</button>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { ReviewTask, ReviewType } from '~/types'

definePageMeta({ layout: 'default', middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const {
  tasks, reviews, loading, loadError, nextCursor, loadingMore,
  activeTasks, activeTaskCount, pendingStartTasks, failedTasks, completedTasks,
  load, refreshTasks, loadMoreTasks: loadMore,
} = useReviewTasks()
const creating = ref(route.query.create === '1')
const createError = ref('')
const submitting = ref(false)
const retryingId = ref('')
const startingId = ref('')
const completedOpen = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null
const hasNonTerminal = computed(() => activeTasks.value.length + pendingStartTasks.value.length > 0)

onMounted(() => {
  void load()
  pollTimer = window.setInterval(() => { if (hasNonTerminal.value) void refreshTasks() }, 15000)
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })

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
