<template>
  <div class="min-h-screen flex flex-col">
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
    <div class="flex-1 px-4 py-3">
      <textarea
        v-model="content"
        placeholder="今天发生了什么？写下你的日记..."
        class="w-full h-full min-h-[400px] text-sm text-neutral-800 placeholder-neutral-400 resize-none"
      ></textarea>
    </div>

    <!-- 底部操作按钮 -->
    <div class="flex gap-3 px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
      <button
        @click="handleSaveDraft"
        :disabled="saving"
        class="flex-1 py-2.5 rounded-lg border border-neutral-300 text-neutral-600 text-sm font-medium hover:bg-neutral-50 disabled:opacity-50"
      >
        {{ saving ? '保存中...' : '保存草稿' }}
      </button>
      <button
        @click="handlePublish"
        :disabled="saving"
        class="flex-1 py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
      >
        {{ saving ? '发布中...' : '发布' }}
      </button>
    </div>

    <!-- 错误提示 -->
    <p v-if="errorMsg" class="text-sm text-red-500 text-center px-4 pb-3">{{ errorMsg }}</p>
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

// 保存草稿
const handleSaveDraft = async () => {
  if (!content.value.trim()) return
  errorMsg.value = ''
  saving.value = true
  try {
    await api<Diary>('/diaries', {
      method: 'POST',
      body: {
        original_text: content.value,
        diary_date: diaryDate.value,
        tag_ids: [],
      },
    })
    navigateTo('/')
  } catch (err: any) {
    errorMsg.value = err?.data?.detail || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

// 发布日记
const handlePublish = async () => {
  if (!content.value.trim()) return
  errorMsg.value = ''
  saving.value = true
  try {
    // 先创建草稿
    const created = await api<Diary>('/diaries', {
      method: 'POST',
      body: {
        original_text: content.value,
        diary_date: diaryDate.value,
        tag_ids: [],
      },
    })
    // 再发布
    await api(`/diaries/${created.id}/publish`, { method: 'PUT' })
    navigateTo('/')
  } catch (err: any) {
    errorMsg.value = err?.data?.detail || '发布失败，请稍后重试'
  } finally {
    saving.value = false
  }
}
</script>
