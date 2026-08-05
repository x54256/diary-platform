<template>
  <div class="flex min-h-dvh flex-col">
    <ReviewTopBar title="与这份回顾对话" show-back>
      <template #right><NuxtLink :to="`/review/${reviewId}?version=${versionId}`" class="flex min-h-11 items-center px-2 text-sm font-medium text-primary-600">详情</NuxtLink></template>
    </ReviewTopBar>
    <main class="mx-auto flex w-full max-w-md flex-1 flex-col px-4 pb-28 pt-4">
      <p class="mb-4 rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm leading-6 text-neutral-500">基于固定版本 v{{ versionNo }}。本次对话不会混入其他版本的内容。</p>
      <div v-if="loading" class="py-10 text-center text-sm text-neutral-400">正在读取对话…</div>
      <div v-else class="space-y-3">
        <article v-for="message in messages" :key="message.id" class="rounded-lg px-4 py-3 text-base leading-7" :class="message.role === 'user' ? 'ml-8 bg-primary-100 text-neutral-900' : 'mr-8 border border-neutral-200 bg-white text-neutral-800'">
          {{ message.content }}
        </article>
        <div v-if="!messages.length" class="rounded-lg border border-neutral-200 bg-white px-4 py-4 text-sm leading-6 text-neutral-500">
          <p>你可以从这份回顾出发继续反思：</p>
          <button v-for="question in starterQuestions" :key="question" type="button" class="mt-2 flex min-h-11 w-full items-center rounded-lg bg-neutral-50 px-3 text-left text-sm text-primary-600" @click="draft = question">{{ question }}</button>
        </div>
      </div>
    </main>
    <form class="fixed inset-x-0 bottom-0 border-t border-neutral-200 bg-white pb-[env(safe-area-inset-bottom)]" @submit.prevent="send">
      <div class="mx-auto flex max-w-md items-end gap-2 px-4 py-3">
        <textarea v-model="draft" rows="1" class="max-h-32 min-h-12 flex-1 resize-y rounded-lg border border-neutral-200 p-3 text-base leading-6 focus:border-primary-400 focus:outline-none" placeholder="围绕这份回顾继续聊……" aria-label="回顾对话输入" :disabled="sending" />
        <button type="submit" class="min-h-12 min-w-12 rounded-lg bg-primary-600 px-3 text-sm font-medium text-white disabled:opacity-50" :disabled="sending || !draft.trim()">{{ sending ? '…' : '发送' }}</button>
      </div>
      <p v-if="error" class="mx-auto max-w-md px-4 pb-2 text-sm text-red-600">{{ error }}</p>
    </form>
  </div>
</template>

<script setup lang="ts">
type Message = { id: string; dialog_id: string; role: string; content: string; created_at: string }
type Dialog = { id: string; source_id: string; messages?: Message[] }

definePageMeta({ layout: 'auth', middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const reviewId = route.params.id as string
const versionId = (typeof route.query.version === 'string' && route.query.version) || ''
const messages = ref<Message[]>([])
const dialogId = ref('')
const versionNo = ref('?')
const draft = ref('')
const loading = ref(true)
const sending = ref(false)
const error = ref('')
const starterQuestions = [
  '这个周期最值得保留的做法是什么？',
  '哪些事情仍然没有真正解决？',
  '下一周期最值得验证的一步是什么？',
]

const load = async () => {
  if (!versionId) { error.value = '缺少回顾版本'; loading.value = false; return }
  try {
    const detail = await api<any>(`/reviews/${reviewId}/versions/${versionId}`)
    versionNo.value = String(detail.version.version_no)
    const dialog = await api<Dialog>('/dialogs', { method: 'POST', body: { source_type: 'review', source_id: versionId } })
    dialogId.value = dialog.id
    messages.value = dialog.messages || await api<Message[]>(`/dialogs/${dialog.id}/messages`)
  } catch (cause: any) { error.value = cause?.data?.detail || '对话加载失败' } finally { loading.value = false }
}
const send = async () => {
  const content = draft.value.trim()
  if (!content || !dialogId.value || sending.value) return
  sending.value = true; error.value = ''
  try {
    const response = await api<Message>(`/dialogs/${dialogId.value}/messages`, { method: 'POST', body: { content } })
    messages.value.push({ id: `user-${Date.now()}`, dialog_id: dialogId.value, role: 'user', content, created_at: new Date().toISOString() }, response)
    draft.value = ''
  } catch (cause: any) { error.value = cause?.data?.detail || '发送失败，请重试' } finally { sending.value = false }
}
onMounted(() => { void load() })
</script>
