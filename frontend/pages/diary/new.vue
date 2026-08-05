<template>
  <div class="h-dvh flex flex-col overflow-hidden">
    <!-- 顶部导航栏 -->
    <NavBar title="写日记" :show-back="true" />

    <!-- 日期选择 -->
    <div class="px-4 py-3 border-b border-neutral-100">
      <div class="flex items-center gap-2">
        <span class="text-base text-neutral-500">日期</span>
        <input
          v-model="diaryDate"
          type="date"
          :disabled="voice.locked.value"
          class="text-base text-neutral-800 px-2 py-1 rounded border border-neutral-200"
        />
      </div>
    </div>

    <!-- 文本输入区 -->
    <div class="flex-1 min-h-0 px-4 py-3">
      <textarea
        v-model="content"
        :readonly="voice.locked.value"
        placeholder="今天发生了什么？写下你的日记..."
        class="w-full h-full min-h-0 text-base text-neutral-800 placeholder-neutral-400 resize-none overflow-y-auto"
      />
    </div>

    <p v-if="voice.locked.value" class="px-4 pb-2 text-center text-xs text-neutral-500">
      该日期正在后台生成日记，其他日期不受影响
    </p>
    <p v-if="voice.error.value && (voice.hasAudio.value || voice.locked.value)" class="px-4 pb-2 text-center text-xs text-red-500">
      {{ voice.error.value }}
    </p>

    <VoiceUploadPanel
      :items="voice.items.value"
      :batch="voice.batch.value"
      :can-start="voice.canStart.value"
      :locked="voice.locked.value"
      :busy="voice.actionLoading.value"
      @add="files => voice.addFiles(files, diaryDate)"
      @reorder="voice.reorder"
      @remove="voice.removeItem"
      @retry="voice.retry"
      @retry-all="voice.retry()"
      @cancel="handleCancelVoice"
      @start="handleStartVoice"
    />

    <!-- 底部操作按钮 -->
    <div v-if="!voice.hasAudio.value && !voice.locked.value" class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
      <p v-if="errorMsg || voice.error.value" class="text-sm text-red-500 text-center pb-2">{{ errorMsg || voice.error.value }}</p>
      <button
        @click="handleSave"
        :disabled="saving"
        class="w-full py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
      >
        {{ saving ? '保存中...' : '保存' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// 日记录入页：使用 auth 布局（无 Tab 栏，有返回按钮）
definePageMeta({
  layout: 'auth',
  middleware: 'auth',
})

const { api } = useApi()
const route = useRoute()

const todayLocalDate = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

// 日记数据
const initialDate = typeof route.query.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(route.query.date)
  ? route.query.date
  : todayLocalDate()
const diaryDate = ref(initialDate)
const content = ref('')
const voice = useVoiceTranscription()

// 加载状态和错误
const saving = ref(false)
const errorMsg = ref('')

// 保存日记
const handleSave = async () => {
  if (!content.value.trim()) return
  errorMsg.value = ''
  saving.value = true
  try {
    const created = await api<Diary>('/diaries', {
      method: 'POST',
      body: {
        original_text: content.value,
        diary_date: diaryDate.value,
        tag_ids: [],
      },
    })
    navigateTo(`/diary/${created.id}`, { replace: true })
  } catch (err: any) {
    errorMsg.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

const handleStartVoice = () => voice.start(diaryDate.value, content.value)

const handleCancelVoice = async () => {
  try {
    const restored = await voice.cancel()
    if (restored) {
      content.value = restored.base_text
      if (restored.diary_date) diaryDate.value = restored.diary_date
    }
  } catch (err: any) {
    voice.error.value = err?.data?.detail || '取消失败'
  }
}

watch(diaryDate, date => voice.loadActive(date).catch((err: any) => {
  voice.error.value = err?.data?.detail || '任务状态读取失败'
}), { immediate: true })

watch(() => voice.batch.value?.diary_id, async (diaryId) => {
  if (!diaryId) return
  try {
    const diary = await api<Diary>(`/diaries/${diaryId}`)
    content.value = diary.original_text
    await nextTick()
    navigateTo(`/diary/${diary.id}`, { replace: true })
  } catch (err: any) {
    voice.error.value = err?.data?.detail || '日记已保存，但详情读取失败'
  }
})
</script>
