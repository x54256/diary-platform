<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] flex items-end justify-center bg-black/35" role="dialog" aria-modal="true" aria-label="回顾版本" @click.self="$emit('close')">
      <section ref="dialogRef" tabindex="-1" class="max-h-[78dvh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white pb-[calc(1.25rem+env(safe-area-inset-bottom))] focus:outline-none" @keydown.esc="$emit('close')">
        <div class="sticky top-0 border-b border-neutral-200 bg-white px-5 pb-3 pt-2">
          <div class="mx-auto mb-3 h-1 w-10 rounded-full bg-neutral-300" />
          <div class="flex items-center justify-between"><h2 class="font-medium text-neutral-900">回顾版本</h2><button type="button" class="min-h-11 min-w-11 text-xl text-neutral-500" aria-label="关闭版本列表" @click="$emit('close')">×</button></div>
        </div>
        <div class="p-5">
          <p v-if="loading" class="py-8 text-center text-sm text-neutral-400">正在读取版本…</p>
          <ReviewStatusBanner v-else-if="error" :title="error" tone="error" />
          <button v-for="version in versions" :key="version.id" type="button" class="flex min-h-16 w-full items-start gap-3 border-b border-neutral-100 py-3 text-left" @click="$emit('select', version.id)">
            <span class="mt-1.5 h-3 w-3 shrink-0 rounded-full border-2" :class="version.id === currentVersionId ? 'border-primary-600 bg-primary-600' : 'border-neutral-300'" />
            <span class="flex-1"><span class="block text-sm font-medium text-neutral-800">v{{ version.version_no }}<span v-if="version.id === currentVersionId"> · 当前</span></span><span class="mt-1 block text-xs text-neutral-500">{{ typeLabel(version.version_type) }}<template v-if="version.analysis_stale"> · 分析可能过期</template><template v-if="version.superseded_at_creation"> · 生成期间内容已更新，未设为当前版本</template> · {{ new Date(version.created_at).toLocaleString('zh-CN') }}</span></span>
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { ReviewVersion } from '~/types'
const props = defineProps<{ open: boolean; reviewId: string; currentVersionId: string }>()
defineEmits<{ (event: 'close'): void; (event: 'select', id: string): void }>()
const { api } = useApi()
const versions = ref<ReviewVersion[]>([])
const loading = ref(false)
const error = ref('')
const dialogRef = ref<HTMLElement | null>(null)
let restoreFocus: HTMLElement | null = null
const load = async () => {
  if (!props.open) return
  loading.value = true; error.value = ''
  try {
    const response = await api<ReviewVersion[] | { items: ReviewVersion[] }>(`/reviews/${props.reviewId}/versions`)
    versions.value = Array.isArray(response) ? response : response.items
  } catch (cause: any) { error.value = cause?.data?.detail || '版本加载失败' } finally { loading.value = false }
}
watch(() => props.open, load)
watch(() => props.open, async (open) => {
  if (open) {
    restoreFocus = document.activeElement as HTMLElement | null
    await nextTick()
    dialogRef.value?.focus()
  } else {
    restoreFocus?.focus()
    restoreFocus = null
  }
})
const typeLabel = (type: string) => ({ GENERATED: '自动生成', EVENT_EDITED: '你修改了事件叙事', REGENERATED: '根据最新来源重新生成', ANALYSIS_UPDATED: '根据事件修改更新分析和行动' }[type] || '回顾版本')
</script>
