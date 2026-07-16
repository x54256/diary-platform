<template>
  <div class="h-dvh flex flex-col overflow-hidden">
    <!-- 顶部导航栏 -->
    <NavBar title="写日记" :show-back="true" />

    <!-- 日期选择 -->
    <div class="px-4 py-3 border-b border-neutral-100">
      <div class="flex items-center gap-2">
        <span class="text-sm text-neutral-500">日期</span>
        <input
          v-model="diaryDate"
          type="date"
          class="text-sm text-neutral-800 px-2 py-1 rounded border border-neutral-200"
        />
      </div>
    </div>

    <!-- 文本输入区 -->
    <div class="flex-1 min-h-0 px-4 py-3">
      <textarea
        v-model="content"
        placeholder="今天发生了什么？写下你的日记..."
        class="w-full h-full min-h-0 text-sm text-neutral-800 placeholder-neutral-400 resize-none overflow-y-auto"
      />
    </div>

    <!-- 底部操作按钮 -->
    <div class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
      <p v-if="errorMsg" class="text-sm text-red-500 text-center pb-2">{{ errorMsg }}</p>
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

// 日记数据
const diaryDate = ref(new Date().toISOString().slice(0, 10))
const content = ref('')

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
</script>
