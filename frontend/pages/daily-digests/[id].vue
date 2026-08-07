<template>
  <div class="min-h-dvh pb-8">
    <NavBar show-back>
      <template #title>
        <h1 class="truncate text-lg font-medium text-neutral-800">每日凝练</h1>
      </template>
    </NavBar>

    <div v-if="loading" class="py-24 text-center text-sm text-neutral-400">加载中...</div>
    <main v-else-if="digest" class="space-y-4 px-4 py-4">
      <header>
        <h2 class="text-lg font-medium text-neutral-800">{{ formatDateInAppTimeZone(digest.digest_date) }} {{ weekDayInAppTimeZone(digest.digest_date) }}</h2>
        <p class="mt-1 text-xs text-neutral-400">已有回顾版本生成的每日素材</p>
      </header>

      <section class="rounded-lg border border-neutral-200 bg-white p-4">
        <h3 class="text-sm font-medium text-neutral-800">今日概览</h3>
        <div class="mt-3">
          <div class="text-xs text-neutral-400">主要变化</div>
          <ul v-if="digest.material_document.day_overview.main_changes.length" class="mt-1 space-y-1 text-sm leading-6 text-neutral-700">
            <li v-for="item in digest.material_document.day_overview.main_changes" :key="item">· {{ item }}</li>
          </ul>
          <p v-else class="mt-1 text-sm text-neutral-400">暂无主要变化</p>
        </div>
        <div class="mt-3">
          <div class="text-xs text-neutral-400">整体状态</div>
          <div v-if="digest.material_document.day_overview.overall_state.length" class="mt-1 flex flex-wrap gap-2">
            <span v-for="item in digest.material_document.day_overview.overall_state" :key="item" class="rounded-full bg-primary-50 px-2.5 py-1 text-xs text-primary-700">{{ item }}</span>
          </div>
          <p v-else class="mt-1 text-sm text-neutral-400">暂无整体状态</p>
        </div>
      </section>

      <section>
        <h3 class="mb-3 text-sm font-medium text-neutral-800">事项</h3>
        <div class="space-y-3">
          <article v-for="matter in digest.material_document.matters" :key="matter.item_key" class="rounded-lg border border-neutral-200 bg-white p-4">
            <h4 class="text-base font-medium text-neutral-800">{{ matter.title }}</h4>
            <div v-if="matter.core_changes.length" class="mt-4"><div class="text-xs text-neutral-400">核心变化</div><div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700"><div v-for="item in matter.core_changes" :key="item">· {{ item }}</div></div></div>
            <div v-if="matter.facts_and_progress.length" class="mt-4"><div class="text-xs text-neutral-400">事实与进展</div><div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700"><div v-for="item in matter.facts_and_progress" :key="item">· {{ item }}</div></div></div>
            <div v-if="matter.emotions_and_state.length" class="mt-4"><div class="text-xs text-neutral-400">情绪与状态</div><div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700"><div v-for="item in matter.emotions_and_state" :key="item">· {{ item }}</div></div></div>
            <div v-if="matter.actions_and_results.length" class="mt-4">
              <div class="text-xs text-neutral-400">行为与结果</div>
              <div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700">
                <div v-for="item in matter.actions_and_results" :key="`${item.action}-${item.result}`">{{ item.action }} → {{ item.result }}</div>
              </div>
            </div>
            <div v-if="matter.concerns_and_expectations.length" class="mt-4">
              <div class="text-xs text-neutral-400">关注与期待</div>
              <div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700">
                <div v-for="item in matter.concerns_and_expectations" :key="`${item.kind}-${item.text}`">{{ concernLabel(item.kind) }}：{{ item.text }}</div>
              </div>
            </div>
            <div v-if="matter.reflections_and_learning.length" class="mt-4"><div class="text-xs text-neutral-400">反思与学习</div><div class="mt-1 space-y-1 text-sm leading-6 text-neutral-700"><div v-for="item in matter.reflections_and_learning" :key="item">· {{ item }}</div></div></div>
            <div v-if="normalizeKeyQuotes(matter.key_quotes).length" class="mt-4">
              <div class="text-xs text-neutral-400">关键原句</div>
              <blockquote v-for="quote in normalizeKeyQuotes(matter.key_quotes)" :key="quote" class="mt-1 border-l-2 border-neutral-200 pl-3 text-sm italic leading-6 text-neutral-600">{{ quote }}</blockquote>
            </div>
          </article>
        </div>
      </section>
    </main>
    <div v-else class="px-4 pt-4 text-center text-sm text-neutral-400">每日凝练不存在或已不属于当前版本</div>
  </div>
</template>

<script setup lang="ts">
import { formatDateInAppTimeZone, weekDayInAppTimeZone } from '~/utils/datetime'
import { normalizeKeyQuotes } from '~/utils/review-daily-material'
import type { ReviewDailyDigest } from '~/types'

definePageMeta({ layout: 'default', middleware: 'auth' })
const route = useRoute()
const { api } = useApi()
const digest = ref<ReviewDailyDigest | null>(null)
const loading = ref(true)

const concernLabel = (kind: string) => ({ ATTENTION: '关注', CONCERN: '担忧', EXPECTATION: '期待' }[kind] || kind)

onMounted(async () => {
  try {
    digest.value = await api<ReviewDailyDigest>(`/daily-digests/${route.params.id}`)
  } catch {
    digest.value = null
  } finally {
    loading.value = false
  }
})
</script>
