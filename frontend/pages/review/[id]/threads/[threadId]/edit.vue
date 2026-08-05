<template>
  <div class="min-h-dvh">
    <ReviewTopBar title="编辑我的回顾" show-back>
      <template #right>
        <button type="button" class="px-2 text-sm font-medium text-primary-600 disabled:text-neutral-300" :disabled="saving || !dirty" @click="save">保存</button>
      </template>
    </ReviewTopBar>
    <main class="mx-auto w-full max-w-md px-4 py-4">
      <div v-if="loading" class="flex justify-center py-24"><span class="text-sm text-neutral-400">加载中...</span></div>
      <ReviewStatusBanner v-else-if="error" :title="error" tone="error" action-label="重新加载" @action="load" />
      <section v-else-if="thread" class="rounded-lg border border-neutral-200 bg-white p-4">
        <p class="text-xs font-medium text-primary-700">{{ domainLabel }}</p>
        <h1 class="mt-2 text-lg font-medium text-neutral-900">{{ thread.title }}</h1>
        <textarea ref="narrativeRef" v-model="narrative" rows="1" data-auto-resize class="mt-4 min-h-64 w-full resize-none overflow-hidden rounded-lg border border-neutral-200 p-3 text-base leading-7 text-neutral-800 focus:border-primary-400 focus:outline-none" aria-label="事件主线叙事" @input="resizeNarrative" />
        <p class="mt-3 text-sm leading-6 text-neutral-500">保存后会创建新版本，不会修改原日记。当前分析会标记为“可能已过期”，需要你主动更新分析和行动。</p>
        <p v-if="saveError" class="mt-3 text-sm text-red-600">{{ saveError }}</p>
      </section>
    </main>
    <Teleport to="body">
      <div v-if="leaveConfirmOpen" class="fixed inset-0 z-[90] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="放弃未保存修改" @click.self="leaveConfirmOpen = false" @keydown.esc="leaveConfirmOpen = false">
        <section class="w-full max-w-md rounded-t-2xl bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
          <h2 class="font-medium text-neutral-900">放弃未保存的修改？</h2>
          <p class="mt-2 text-sm leading-6 text-neutral-600">离开后，本次事件叙事修改不会保留。</p>
          <div class="mt-5 grid grid-cols-2 gap-3">
            <button type="button" autofocus class="min-h-12 rounded-lg border border-neutral-300 text-sm text-neutral-700" @click="leaveConfirmOpen = false">继续编辑</button>
            <button type="button" class="min-h-12 rounded-lg bg-red-600 text-sm font-medium text-white" @click="discardAndLeave">放弃修改</button>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import type { ReviewEventThread, ReviewVersionDetail } from '~/types'
import { resizeTextarea } from '~/composables/useAutoResizeTextarea'
import { reviewDomainLabel } from '~/utils/reviewLabels'

definePageMeta({ layout: 'auth', middleware: 'auth' })
const route = useRoute()
const router = useRouter()
const { api } = useApi()
const reviewId = route.params.id as string
const threadId = decodeURIComponent(route.params.threadId as string)
const versionId = typeof route.query.version === 'string' ? route.query.version : ''
const detail = ref<ReviewVersionDetail | null>(null)
const thread = ref<ReviewEventThread | null>(null)
const narrative = ref('')
const original = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saveError = ref('')
const narrativeRef = ref<HTMLTextAreaElement | null>(null)
const leaveConfirmOpen = ref(false)
const pendingRoute = ref('')
const allowLeave = ref(false)
const dirty = computed(() => narrative.value.trim() !== original.value.trim())
const domainLabel = computed(() => (thread.value ? reviewDomainLabel(thread.value.primary_domain) : ''))
const load = async () => {
  loading.value = true; error.value = ''
  try {
    detail.value = await api<ReviewVersionDetail>(versionId ? `/reviews/${reviewId}/versions/${versionId}` : `/reviews/${reviewId}`)
    const found = detail.value.version.event_document.domains.flatMap(domain => domain.event_threads).find(item => (item.thread_id || item.id || item.thread_key) === threadId)
    if (!found) throw new Error('事件发展主线不存在')
    thread.value = found
    narrative.value = found.narrative
    original.value = found.narrative
    await nextTick()
    resizeNarrative()
  } catch (cause: any) { error.value = cause?.data?.detail || cause?.message || '事件加载失败' } finally { loading.value = false }
}
const save = async () => {
  if (!thread.value || !detail.value || !dirty.value) return
  saving.value = true; saveError.value = ''
  try {
    const result = await api<{ version_id: string }>(`/review-versions/${detail.value.version.id}/event-document`, {
      method: 'PATCH',
      body: { threads: [{ thread_id: thread.value.thread_id || thread.value.id || thread.value.thread_key, narrative: narrative.value.trim() }] },
    })
    original.value = narrative.value.trim()
    await router.replace(`/review/${reviewId}?version=${result.version_id}`)
  } catch (cause: any) { saveError.value = cause?.data?.detail || '保存失败，请重试' } finally { saving.value = false }
}
const resizeNarrative = () => { if (narrativeRef.value) resizeTextarea(narrativeRef.value) }
onBeforeRouteLeave((to) => {
  if (allowLeave.value || !dirty.value) return true
  pendingRoute.value = to.fullPath
  leaveConfirmOpen.value = true
  return false
})
const discardAndLeave = async () => {
  allowLeave.value = true
  leaveConfirmOpen.value = false
  await router.push(pendingRoute.value || `/review/${reviewId}?version=${versionId}`)
}
const beforeUnload = (event: BeforeUnloadEvent) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
