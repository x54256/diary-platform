<template>
  <article class="rounded-lg border border-neutral-200 bg-white px-4 py-3">
    <div class="flex items-start justify-between gap-3">
      <h4 class="text-[17px] font-medium leading-6 text-neutral-800">{{ thread.title }}</h4>
      <NuxtLink :to="editUrl" class="shrink-0 text-sm text-primary-600">编辑</NuxtLink>
    </div>
    <div v-if="isSingleDay || statusLabel" class="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span v-if="isSingleDay" class="rounded px-2 py-0.5 text-xs" :class="SINGLE_DAY_BADGE_CLASS">单日</span>
      <span v-if="statusLabel" class="rounded px-2 py-0.5 text-xs" :class="statusBadgeClass">{{ statusLabel }}</span>
    </div>
    <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ thread.narrative }}</p>

    <div v-if="nodes.length" class="mt-3 border-t border-neutral-100 pt-1">
      <button type="button" class="flex min-h-11 items-center text-sm text-neutral-500" :aria-expanded="nodesOpen" @click="nodesOpen = !nodesOpen">
        <span class="mr-1">{{ nodesOpen ? '▾' : '▸' }}</span>时间线（{{ nodes.length }}）
      </button>
      <div v-if="nodesOpen" class="space-y-3 pb-2">
        <div v-for="node in nodes" :key="node.node_key" class="relative rounded-lg bg-neutral-50 px-3 py-2 pl-6">
          <span class="absolute left-2.5 top-3 h-2 w-2 rounded-full bg-neutral-300"></span>
          <p class="text-xs font-medium text-neutral-500">{{ shortDate(node.source_date) }} {{ weekDay(node.source_date) }}</p>
          <p class="mt-1 whitespace-pre-wrap text-sm leading-6 text-neutral-700">{{ node.fact }}</p>
          <div v-if="node.quotes?.length" class="mt-1">
            <button type="button" class="flex min-h-9 items-center text-xs text-neutral-400" :aria-expanded="quotesOpen.has(node.node_key)" @click="toggleQuotes(node.node_key)">
              <span class="mr-1">{{ quotesOpen.has(node.node_key) ? '▾' : '▸' }}</span>查看原文摘录
            </button>
            <div v-if="quotesOpen.has(node.node_key)" class="mt-1 space-y-1">
              <p v-for="(quote, idx) in node.quotes" :key="idx" class="rounded bg-neutral-100 px-2 py-1.5 text-xs leading-5 text-neutral-600">"{{ quote }}"</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { ReviewEventThread } from '~/types'
import { SINGLE_DAY_BADGE_CLASS, reviewStatusBadgeClass, reviewStatusLabel } from '~/utils/reviewLabels'

const props = defineProps<{ reviewId: string; versionId: string; thread: ReviewEventThread }>()
const nodesOpen = ref(false)
const quotesOpen = ref<Set<string>>(new Set())
const isSingleDay = computed(() => props.thread.span_type === 'SINGLE_DAY')
const nodes = computed(() => props.thread.nodes || [])
const statusLabel = computed(() => reviewStatusLabel(props.thread.current_status))
const statusBadgeClass = computed(() => reviewStatusBadgeClass(props.thread.current_status))
const shortDate = (value: string) => (value && value.length >= 10 ? `${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日` : '')
const weekDay = (value: string) => {
  if (!value || value.length < 10) return ''
  const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const d = new Date(value)
  return days[d.getDay()] || ''
}
const toggleQuotes = (nodeKey: string) => {
  const newSet = new Set(quotesOpen.value)
  if (newSet.has(nodeKey)) {
    newSet.delete(nodeKey)
  } else {
    newSet.add(nodeKey)
  }
  quotesOpen.value = newSet
}
const threadId = computed(() => props.thread.thread_id || props.thread.id || props.thread.thread_key)
const editUrl = computed(() => `/review/${props.reviewId}/threads/${encodeURIComponent(threadId.value)}/edit?version=${props.versionId}`)
</script>
