<template>
  <div class="min-h-dvh flex flex-col">
    <!-- 顶部导航栏 -->
    <NavBar :title="pageTitle" :show-back="true" />

    <!-- 加载中 -->
    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <span class="text-sm text-neutral-400">加载中...</span>
    </div>

    <!-- 无日记 -->
    <div v-else-if="diaries.length === 0" class="flex-1 flex items-center justify-center">
      <span class="text-sm text-neutral-400">当天暂无已分析日记</span>
    </div>

    <!-- 日记列表 -->
    <div v-else class="flex-1 px-4 py-3 space-y-3">
      <NuxtLink
        v-for="item in diaries"
        :key="item.id"
        :to="`/diary/${item.id}`"
        class="block bg-white rounded-lg p-3 active:bg-neutral-50 cursor-pointer"
      >
        <!-- 时间 HH:MM -->
        <div class="flex items-center gap-2 mb-1">
          <span class="text-xs text-neutral-400">{{ formatTime(item.created_at) }}</span>
        </div>
        <!-- 标题+摘要 -->
        <div class="text-sm font-medium text-neutral-800">{{ item.organized?.title || '无标题' }}</div>
        <div v-if="item.organized?.summary" class="text-xs text-neutral-500 mt-1 line-clamp-2">{{ item.organized.summary }}</div>
        <!-- 状态标签 -->
        <div class="flex items-center gap-2 mt-2">
          <span class="text-xs px-2 py-0.5 rounded bg-purple-50 text-purple-600">已分析</span>
          <span v-if="item.organized?.mood" class="text-xs text-primary-600">{{ item.organized.mood }}</span>
          <span v-if="item.organized?.location" class="text-xs text-neutral-400">{{ item.organized.location }}</span>
        </div>
        <!-- 标签 -->
        <div v-if="item.tags && item.tags.length > 0" class="flex flex-wrap mt-2">
          <TagBadge v-for="tag in sortedDiaryTags(item.tags).slice(0, 5)" :key="tag.id" :tag="tag" />
          <span v-if="item.tags.length > 5" class="text-xs text-neutral-400 ml-1">+{{ item.tags.length - 5 }}</span>
        </div>
      </NuxtLink>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const route = useRoute()
const { api } = useApi()

const dateParam = computed(() => route.params.date as string)

// 页面标题：YYYY年M月D日 日记
const pageTitle = computed(() => {
  const d = dateParam.value
  if (!d) return '日记列表'
  const [y, m, day] = d.split('-')
  return `${y}年${parseInt(m)}月${parseInt(day)}日 日记`
})

const loading = ref(false)
const diaries = ref<Diary[]>([])

// 加载当天已分析的日记
const loadDiaries = async () => {
  const date = dateParam.value
  if (!date) return
  loading.value = true
  try {
    const data = await api<Diary[]>('/diaries', {
      params: { start_date: date, end_date: date },
    })
    // 仅保留已分析的日记，按 created_at 降序（最新在上）
    diaries.value = data
      .filter(d => d.status === 'analyzed')
      .sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0
        return tb - ta
      })
  } catch (err) {
    console.error('加载日期日记失败', err)
    diaries.value = []
  } finally {
    loading.value = false
  }
}

// 时间格式化（HH:MM）
const formatTime = (dateStr?: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 标签按类别排序：领域 → 主题 → 人物/对象 → 心理 → 知识点
const TAG_TYPE_ORDER: Record<string, number> = {
  domain: 0,
  topic: 1,
  person_object: 2,
  psychological: 3,
  knowledge: 4,
}

const sortedDiaryTags = (tags: any[]) => {
  return [...tags].sort((a, b) => {
    const orderA = TAG_TYPE_ORDER[a.type] ?? 99
    const orderB = TAG_TYPE_ORDER[b.type] ?? 99
    return orderA - orderB
  })
}

onMounted(() => {
  loadDiaries()
})
</script>
