<template>
  <div class="min-h-dvh bg-neutral-50">
    <NavBar title="事件知识" :show-back="true" />
    <main class="w-full px-4 py-5">
      <div v-if="loading" class="py-16 text-center text-sm text-neutral-400">加载中...</div>
      <div v-else-if="error" class="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>
      <article v-else-if="event" class="space-y-6">
        <header>
          <time class="text-sm text-neutral-400">{{ formatKnowledgeDateTime(event.occurred_on, event.occurred_time) }}</time>
          <h1 class="mt-2 text-xl font-semibold text-neutral-900">{{ event.title }}</h1>
        </header>
        <section>
          <h2 class="text-sm font-medium text-neutral-500">事件内容</h2>
          <p class="mt-2 whitespace-pre-wrap rounded-xl bg-white p-4 text-base leading-7 text-neutral-700 shadow-sm">{{ knowledgePlainText(event.content) }}</p>
        </section>
        <NuxtLink v-if="event.matter" :to="`/knowledge/matters/${event.matter.id}`" class="flex items-center justify-between rounded-xl bg-white p-4 shadow-sm active:bg-neutral-50">
          <div class="min-w-0">
            <div class="text-xs text-neutral-400">所属事项</div>
            <div class="mt-1 break-words text-sm leading-6 text-neutral-700">{{ event.matter.name }}</div>
          </div>
          <span class="text-neutral-400">›</span>
        </NuxtLink>
        <NuxtLink :to="`/diary/${event.diary_id}#event-${event.source_diary_event_id}`" class="flex items-center justify-between rounded-xl bg-white p-4 shadow-sm active:bg-neutral-50">
          <div class="min-w-0">
            <div class="text-xs text-neutral-400">来源</div>
            <div class="mt-1 break-words text-sm leading-6 text-neutral-700">
              {{ formatDateInAppTimeZone(event.source_diary_date) }} ·《{{ event.source_diary_title || '未命名日记' }}》· {{ event.source_event_title || '未命名事件' }}
            </div>
          </div>
          <span class="text-neutral-400">›</span>
        </NuxtLink>
      </article>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { KnowledgeEvent } from '~/types/knowledge'
import { formatDateInAppTimeZone } from '~/utils/datetime'
import { formatKnowledgeDateTime, knowledgePlainText } from '~/utils/knowledgeText'

definePageMeta({ middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const event = ref<KnowledgeEvent | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    event.value = await api<KnowledgeEvent>(`/knowledge/events/${route.params.id}`)
  } catch (exception: any) {
    error.value = exception?.data?.detail?.message || exception?.data?.detail || '事件知识加载失败'
  } finally {
    loading.value = false
  }
})
</script>
