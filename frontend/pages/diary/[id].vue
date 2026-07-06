<template>
  <div class="min-h-screen flex flex-col">
    <!-- 顶部导航栏 -->
    <NavBar :title="diaryTitle" :show-back="true" />

    <!-- 加载中 -->
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <span class="text-sm text-neutral-400">加载中...</span>
    </div>

    <!-- 未整理状态：显示原始文本 + 整理按钮 -->
    <template v-else-if="diary && diary.status !== 'organized'">
      <div class="flex-1 overflow-y-auto px-4 py-3">
        <!-- 日期 -->
        <div class="text-sm text-neutral-500 mb-3">{{ diary.diary_date }}</div>
        <!-- 原始文本 -->
        <div class="text-sm text-neutral-800 whitespace-pre-wrap leading-relaxed">
          {{ diary.original_text }}
        </div>
      </div>

      <!-- 底部整理按钮 -->
      <div class="px-4 py-3 border-t border-neutral-200 bg-white safe-area-bottom">
        <button
          @click="handleOrganize"
          :disabled="organizing"
          class="w-full py-2.5 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
        >
          {{ organizing ? (organizeStep + '...') : 'AI 整理' }}
        </button>
        <p v-if="organizeError" class="text-sm text-red-500 text-center mt-2">{{ organizeError }}</p>
      </div>
    </template>

    <!-- 已整理状态：显示整理后的内容 + 对话区 -->
    <template v-else-if="diary && diary.status === 'organized'">
      <div class="flex-1 overflow-y-auto px-4 py-3 pb-20">
        <!-- 元数据横排：心情 / 地点 / 标签 -->
        <div v-if="!editing" class="flex items-center gap-3 mb-4">
          <span class="text-xs text-neutral-400">心情</span>
          <span class="text-xs text-primary-600">{{ diary.organized?.mood || '-' }}</span>
          <span class="text-xs text-neutral-400">地点</span>
          <span class="text-xs text-primary-600">{{ diary.organized?.location || '-' }}</span>
        </div>

        <!-- 摘要 -->
        <div v-if="diary.organized?.summary && !editing" class="text-sm text-neutral-600 leading-relaxed mb-4 pb-3 border-b border-neutral-100">
          {{ diary.organized.summary }}
        </div>

        <!-- 编辑按钮（正文区上方右侧） -->
        <div v-if="!editing" class="flex justify-end mb-3">
          <button @click="startEdit" class="text-xs text-primary-600 hover:text-primary-700">编辑</button>
        </div>

        <!-- 查看模式：markdown 渲染 -->
        <div v-if="!editing" class="diary-content text-sm text-neutral-800 leading-relaxed mb-6" v-html="renderedContent"></div>

        <!-- 编辑模式 -->
        <div v-else class="mb-6 space-y-3">
          <input v-model="editForm.title" type="text" placeholder="标题" class="w-full px-3 py-2 rounded-lg border border-neutral-200 text-sm" />
          <input v-model="editForm.summary" type="text" placeholder="摘要" class="w-full px-3 py-2 rounded-lg border border-neutral-200 text-sm" />
          <div class="flex gap-3">
            <input v-model="editForm.mood" type="text" placeholder="心情" class="flex-1 px-3 py-2 rounded-lg border border-neutral-200 text-sm" />
            <input v-model="editForm.location" type="text" placeholder="地点" class="flex-1 px-3 py-2 rounded-lg border border-neutral-200 text-sm" />
          </div>
          <textarea v-model="editForm.content" rows="15" placeholder="正文（Markdown 格式）" class="w-full px-3 py-2 rounded-lg border border-neutral-200 text-sm font-mono"></textarea>
          <div class="flex gap-3">
            <button @click="saveEdit" class="px-4 py-2 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700">保存</button>
            <button @click="cancelEdit" class="px-4 py-2 rounded-lg border border-neutral-200 text-sm text-neutral-600 hover:bg-neutral-50">取消</button>
          </div>
        </div>

        <!-- 原始文本（可展开） -->
        <details class="border-t border-neutral-100 pt-3">
          <summary class="text-xs text-neutral-400 cursor-pointer">查看原始文本</summary>
          <div class="mt-2 text-xs text-neutral-500 whitespace-pre-wrap leading-relaxed">
            {{ diary.original_text }}
          </div>
        </details>
      </div>

      <!-- 底部对话区占位 -->
      <div class="fixed bottom-0 left-0 right-0 px-4 py-2 border-t border-neutral-200 bg-white safe-area-bottom">
        <div class="flex items-center gap-2 max-w-md mx-auto">
          <input
            v-model="dialogInput"
            type="text"
            placeholder="围绕这篇日记展开对话..."
            class="flex-1 px-3 py-2 rounded-full bg-neutral-100 text-sm text-neutral-800 placeholder-neutral-400"
          />
          <button class="w-8 h-8 rounded-full bg-primary-600 text-white text-sm flex items-center justify-center">
            →
          </button>
        </div>
      </div>
    </template>

    <!-- 未找到 -->
    <div v-else class="flex-1 flex items-center justify-center">
      <span class="text-sm text-neutral-400">日记不存在</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import MarkdownIt from 'markdown-it'
const md = new MarkdownIt({ html: false })  // 禁用原始 HTML，防 XSS
const renderedContent = computed(() => md.render(diary.value?.organized?.content || ''))

// 日记详情页：使用 auth 布局（无 Tab 栏，有返回按钮）
definePageMeta({
  layout: 'auth',
  middleware: 'auth',
})

const route = useRoute()
const { api } = useApi()
const diaryId = computed(() => route.params.id as string)

// 日记数据
const diary = ref<Diary | null>(null)
const loading = ref(true)

// AI 整理状态
const organizing = ref(false)
const organizeError = ref('')
const organizeStep = ref('')  // 当前步骤文本

const STEP_LABELS: Record<string, string> = {
  text_cleaning: '轻度清洗中',
  deep_cleaning: '深度内容重组中',
  event_organizing: '事件识别与归类中',
  template_filling: '事件内容整理中',
  content_checking: '内容检查与修正中',
  metadata_generating: '元数据生成中',
}
const STEP_KEYS = Object.keys(STEP_LABELS)

const formatStep = (stepKey: string) => {
  const idx = STEP_KEYS.indexOf(stepKey)
  const label = STEP_LABELS[stepKey] || stepKey
  if (idx === -1) return label
  return `${idx + 1}/${STEP_KEYS.length} ${label}`
}

// 编辑模式
const editing = ref(false)
const editForm = reactive({
  title: '',
  summary: '',
  content: '',
  mood: '',
  location: '',
})

const startEdit = () => {
  if (!diary.value?.organized) return
  editForm.title = diary.value.organized.title || ''
  editForm.summary = diary.value.organized.summary || ''
  editForm.content = diary.value.organized.content || ''
  editForm.mood = diary.value.organized.mood || ''
  editForm.location = diary.value.organized.location || ''
  editing.value = true
}

const cancelEdit = () => {
  editing.value = false
}

const saveEdit = async () => {
  try {
    await api(`/diaries/${diaryId.value}/organized`, {
      method: 'PUT',
      body: { ...editForm },
    })
    editing.value = false
    await loadDiary()
  } catch (err: any) {
    alert(err?.data?.detail || '保存失败，请重试')
  }
}

// 对话输入
const dialogInput = ref('')

// 标题
const diaryTitle = computed(() => {
  if (!diary.value) return '日记详情'
  if (diary.value.organized?.title) return diary.value.organized.title
  return diary.value.diary_date
})

// 加载日记数据
const loadDiary = async () => {
  loading.value = true
  try {
    diary.value = await api<Diary>(`/diaries/${diaryId.value}`)
  } catch (err) {
    console.error('加载日记失败', err)
    diary.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadDiary()
  // 加载完成后检查是否有未完成的整理任务
  if (diary.value && diary.value.status !== 'organized') {
    checkOrganizeStatus()
  }
})

// 触发 AI 整理（异步任务+轮询）
const handleOrganize = async () => {
  organizing.value = true
  organizeError.value = ''
  organizeStep.value = formatStep('text_cleaning')
  try {
    await api(`/diaries/${diaryId.value}/organize`, { method: 'POST' })
    await pollOrganizeStatus()
  } catch (err: any) {
    organizeError.value = err?.data?.detail || '整理启动失败'
    organizing.value = false
  }
}

const pollOrganizeStatus = async () => {
  const maxAttempts = 200  // 200次×3秒=10分钟
  let consecutiveErrors = 0
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(resolve => setTimeout(resolve, 3000))
    try {
      const task = await api<{status: string; current_step?: string; error_message?: string}>(
        `/diaries/${diaryId.value}/organize/status`
      )
      consecutiveErrors = 0  // 成功则重置
      if (task.current_step) {
        organizeStep.value = formatStep(task.current_step)
      }
      if (task.status === 'completed') {
        await loadDiary()
        organizing.value = false
        return
      }
      if (task.status === 'failed') {
        organizeError.value = task.error_message || 'AI 整理失败，请重试'
        organizing.value = false
        return
      }
    } catch {
      consecutiveErrors++
      if (consecutiveErrors >= 5) {
        organizeError.value = '网络异常，请检查连接后重试'
        organizing.value = false
        return
      }
    }
  }
  organizeError.value = '整理超时，请稍后重试'
  organizing.value = false
}

// 页面加载时检查是否有未完成的整理任务
const checkOrganizeStatus = async () => {
  try {
    const task = await api<{status: string; current_step?: string}>(
      `/diaries/${diaryId.value}/organize/status`
    )
    if (task.status === 'running') {
      organizing.value = true
      if (task.current_step) {
        organizeStep.value = formatStep(task.current_step)
      }
      pollOrganizeStatus()
    }
  } catch { /* 无任务，忽略 */ }
}
</script>
