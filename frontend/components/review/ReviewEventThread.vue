<template>
  <article class="py-4 first:pt-0">
    <h4 class="text-base font-semibold text-neutral-800">{{ thread.title }}</h4>
    <p class="mt-2 whitespace-pre-wrap text-[15px] leading-7 text-neutral-700">{{ thread.narrative }}</p>
    <div class="mt-3 flex items-center justify-between gap-2 text-sm">
      <button
        type="button"
        class="min-h-11 text-neutral-500"
        :disabled="!sourceIds.length"
        @click="$emit('sources', sourceIds, thread.title)"
      >
        {{ sourceIds.length ? `${sourceIds.length} 条依据` : '暂无可查看依据' }}
      </button>
      <NuxtLink :to="editUrl" class="flex min-h-11 items-center font-medium text-primary-700">编辑 ›</NuxtLink>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { ReviewEventThread } from '~/types'

const props = defineProps<{ reviewId: string; versionId: string; thread: ReviewEventThread }>()
defineEmits<{ (event: 'sources', ids: string[], title: string): void }>()
const sourceIds = computed(() => [...new Set([
  ...(props.thread.nodes || []).flatMap(node => node.source_ids || []),
  ...(props.thread.prior_context_source_ids || []),
  ...(props.thread.narrative_correction_source_id ? [props.thread.narrative_correction_source_id] : []),
])])
const threadId = computed(() => props.thread.thread_id || props.thread.id || props.thread.thread_key)
const editUrl = computed(() => `/review/${props.reviewId}/threads/${encodeURIComponent(threadId.value)}/edit?version=${props.versionId}`)
</script>
