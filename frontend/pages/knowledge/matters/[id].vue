<template>
  <div class="min-h-dvh bg-neutral-50">
    <NavBar title="事项详情" :show-back="true" />
    <main class="w-full px-4 py-5">
      <div v-if="loading" class="py-16 text-center text-sm text-neutral-400">加载中...</div>
      <div v-else-if="error" class="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>
      <article v-else-if="matter" class="space-y-6">
        <header>
          <div class="flex items-center justify-between gap-3">
            <h1 class="min-w-0 text-xl font-semibold text-neutral-900">{{ matter.name }}</h1>
            <span
              class="shrink-0 rounded-full px-2 py-0.5 text-xs"
              :class="statusClass(matter.status)"
            >{{ statusLabel(matter.status) }}</span>
          </div>
          <div class="mt-2 text-sm text-neutral-400">
            {{ formatDateInAppTimeZone(matter.started_on) }} 开始 · {{ matter.event_count }} 个事件
          </div>
        </header>

        <section>
          <h2 class="text-sm font-medium text-neutral-500">全览</h2>
          <p class="mt-2 whitespace-pre-wrap rounded-xl bg-white p-4 text-base leading-7 text-neutral-700 shadow-sm">{{ matter.overview }}</p>
        </section>

        <section>
          <h2 class="text-sm font-medium text-neutral-500">发展时间线</h2>
          <div class="mt-2 space-y-3">
            <NuxtLink
              v-for="event in matter.events"
              :key="event.id"
              :to="`/knowledge/events/${event.id}`"
              class="block rounded-xl border border-neutral-100 bg-white p-4 shadow-sm active:bg-neutral-50"
            >
              <div class="flex items-start justify-between gap-3">
                <h3 class="min-w-0 truncate text-sm font-medium text-neutral-700">{{ event.title }}</h3>
                <time class="shrink-0 text-xs text-neutral-400">{{ formatKnowledgeDateTime(event.occurred_on, event.occurred_time) }}</time>
              </div>
              <p class="mt-2 line-clamp-2 whitespace-pre-wrap text-sm leading-6 text-neutral-600">{{ event.first_paragraph }}</p>
            </NuxtLink>
          </div>
        </section>
      </article>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { KnowledgeMatterDetail, KnowledgeMatterStatus } from '~/types/knowledge'
import { formatDateInAppTimeZone } from '~/utils/datetime'
import { formatKnowledgeDateTime } from '~/utils/knowledgeText'

definePageMeta({ middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const matter = ref<KnowledgeMatterDetail | null>(null)
const loading = ref(true)
const error = ref('')

const statusLabel = (status: KnowledgeMatterStatus) => (
  status === 'ONGOING' ? '进行中' : status === 'ENDED' ? '已结束' : '搁置'
)
const statusClass = (status: KnowledgeMatterStatus) => (
  status === 'ONGOING'
    ? 'bg-primary-50 text-primary-600'
    : status === 'ENDED'
      ? 'bg-neutral-100 text-neutral-500'
      : 'bg-amber-50 text-amber-600'
)

onMounted(async () => {
  try {
    matter.value = await api<KnowledgeMatterDetail>(`/knowledge/matters/${route.params.id}`)
  } catch (exception: any) {
    error.value = exception?.data?.detail?.message || exception?.data?.detail || '事项加载失败'
  } finally {
    loading.value = false
  }
})
</script>
