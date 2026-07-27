<template>
  <div class="min-h-dvh">
    <header class="flex items-center gap-3 bg-white px-4 py-4 border-b border-neutral-100">
      <button type="button" class="text-2xl leading-none text-neutral-500" aria-label="返回" @click="navigateTo('/profile')">‹</button>
      <h1 class="text-lg font-medium text-neutral-800">热词管理</h1>
    </header>

    <section class="px-4 py-4">
      <p class="text-sm leading-6 text-neutral-500">
        管理常用的专有词汇。人物姓名和常用名由“用户关系管理”单独维护。
      </p>
    </section>

    <section class="bg-white px-4 py-4">
      <form class="flex gap-2" @submit.prevent="saveHotWord">
        <input
          v-model="draftText"
          type="text"
          maxlength="100"
          placeholder="输入热词"
          class="min-w-0 flex-1 rounded-lg border border-neutral-200 px-3 py-2.5 text-base"
        >
        <button
          type="submit"
          class="shrink-0 rounded-lg bg-primary-500 px-4 py-2.5 text-sm text-white disabled:opacity-50"
          :disabled="pending || !draftText.trim()"
        >
          {{ editingId ? '保存' : '添加' }}
        </button>
      </form>
      <p v-if="errorMessage" class="mt-2 text-sm text-red-500">{{ errorMessage }}</p>
    </section>

    <section class="mt-3 bg-white">
      <div class="border-b border-neutral-100 px-4 py-3 text-sm font-medium text-neutral-700">我的热词</div>
      <div v-if="loading" class="px-4 py-8 text-center text-sm text-neutral-400">加载中…</div>
      <div v-else-if="!hotWords.length" class="px-4 py-8 text-center text-sm text-neutral-400">还没有添加热词</div>
      <div v-else>
        <div v-for="item in hotWords" :key="item.id" class="flex items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3 last:border-b-0">
          <span class="min-w-0 flex-1 break-all text-sm text-neutral-800">{{ item.text }}</span>
          <div class="flex shrink-0 gap-3 text-sm">
            <button type="button" class="text-primary-600" @click="startEdit(item)">编辑</button>
            <button type="button" class="text-red-500" @click="removeHotWord(item)">删除</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { HotWord } from '~/types'

definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const { api } = useApi()
const hotWords = ref<HotWord[]>([])
const draftText = ref('')
const editingId = ref<string | null>(null)
const loading = ref(true)
const pending = ref(false)
const errorMessage = ref('')

const loadHotWords = async () => {
  loading.value = true
  try {
    hotWords.value = await api<HotWord[]>('/hot-words')
  } catch (error: any) {
    errorMessage.value = error?.data?.detail || '热词加载失败'
  } finally {
    loading.value = false
  }
}

const saveHotWord = async () => {
  const text = draftText.value.trim()
  if (!text) return
  pending.value = true
  errorMessage.value = ''
  try {
    if (editingId.value) {
      const updated = await api<HotWord>(`/hot-words/${editingId.value}`, {
        method: 'PUT',
        body: { text },
      })
      const index = hotWords.value.findIndex(item => item.id === updated.id)
      if (index >= 0) hotWords.value[index] = updated
    } else {
      const created = await api<HotWord>('/hot-words', {
        method: 'POST',
        body: { text },
      })
      hotWords.value.unshift(created)
    }
    cancelEdit()
  } catch (error: any) {
    errorMessage.value = error?.data?.detail || '热词保存失败'
  } finally {
    pending.value = false
  }
}

const startEdit = (item: HotWord) => {
  editingId.value = item.id
  draftText.value = item.text
  errorMessage.value = ''
}

const cancelEdit = () => {
  editingId.value = null
  draftText.value = ''
}

const removeHotWord = async (item: HotWord) => {
  if (!window.confirm(`确认删除热词“${item.text}”吗？`)) return
  errorMessage.value = ''
  try {
    await api(`/hot-words/${item.id}`, { method: 'DELETE' })
    hotWords.value = hotWords.value.filter(value => value.id !== item.id)
    if (editingId.value === item.id) cancelEdit()
  } catch (error: any) {
    errorMessage.value = error?.data?.detail || '热词删除失败'
  }
}

await loadHotWords()
</script>
