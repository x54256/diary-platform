<template>
  <section :id="`review-domain-${domainCode}`" class="scroll-mt-[88px]">
    <header>
      <h2 class="text-base font-medium text-neutral-800">{{ domainLabel }}</h2>
    </header>

    <div v-if="relatedEntries.length" class="mt-3 rounded-lg border border-neutral-200 bg-white px-4 py-3">
      <p class="text-xs font-medium text-neutral-500">相关领域引用</p>
      <button
        v-for="entry in relatedEntries"
        :key="entry.key"
        type="button"
        class="flex min-h-11 w-full items-center justify-between border-b border-neutral-100 text-left text-sm text-neutral-700 last:border-b-0"
        @click="$emit('related-select', entry.primaryDomain)"
      >
        <span>{{ entry.label }}</span><span class="text-primary-600">查看原领域 ›</span>
      </button>
    </div>

    <div v-if="eventDomain?.event_threads?.length" class="mt-3 space-y-3">
      <ReviewEventThread v-for="thread in eventDomain.event_threads" :key="thread.thread_key" :review-id="reviewId" :version-id="versionId" :thread="thread" />
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ReviewDomainCode, ReviewEventDomain } from '~/types'
import { reviewDomainLabel } from '~/utils/reviewLabels'

const props = defineProps<{
  reviewId: string
  versionId: string
  domainCode: ReviewDomainCode
  eventDomain?: ReviewEventDomain
  relatedEntries: Array<{ key: string; label: string; primaryDomain: ReviewDomainCode }>
}>()
const emit = defineEmits<{
  (event: 'related-select', code: ReviewDomainCode): void
}>()
const domainLabel = computed(() => reviewDomainLabel(props.domainCode))
</script>
