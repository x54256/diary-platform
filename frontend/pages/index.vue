<template>
  <div class="min-h-screen flex flex-col">
    <!-- 顶部月份导航 -->
    <div class="sticky top-0 z-30 bg-white border-b border-neutral-200">
      <div class="flex items-center justify-between px-4 h-nav">
        <button @click="changeMonth(-1)" class="text-neutral-400 text-lg w-8 h-8 flex items-center justify-center">‹</button>
        <span class="text-base font-medium text-neutral-800">{{ currentYear }}年{{ currentMonth }}月</span>
        <button @click="changeMonth(1)" class="text-neutral-400 text-lg w-8 h-8 flex items-center justify-center">›</button>
      </div>
    </div>

    <!-- 搜索框 -->
    <div class="px-4 py-3">
      <div class="relative">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索日记..."
          @keyup.enter="handleSearch"
          class="w-full pl-10 pr-4 py-2 rounded-lg bg-neutral-100 text-sm text-neutral-800 placeholder-neutral-400"
        />
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400 text-sm">🔍</span>
      </div>
    </div>

    <!-- 搜索结果 -->
    <div v-if="searchResults !== null" class="px-4 pb-4">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs text-neutral-500">搜索结果（{{ searchResults.length }} 条）</span>
        <button @click="clearSearch" class="text-xs text-primary-600">清除</button>
      </div>
      <div v-if="searchResults.length === 0" class="text-center text-sm text-neutral-400 py-6">
        未找到相关日记
      </div>
      <div v-else class="space-y-2">
        <NuxtLink
          v-for="item in searchResults"
          :key="item.id"
          :to="`/diary/${item.id}`"
          class="block bg-white rounded-lg p-3 active:bg-neutral-50"
        >
          <div class="text-sm text-neutral-800 line-clamp-2">{{ item.original_text }}</div>
          <div class="flex items-center gap-2 mt-1">
            <span class="text-xs text-neutral-400">{{ item.diary_date }}</span>
            <span v-if="item.organized?.mood" class="text-xs text-primary-600">{{ item.organized.mood }}</span>
          </div>
        </NuxtLink>
      </div>
    </div>

    <!-- 视图切换：日历 / 时间线 -->
    <div v-if="searchResults === null" class="px-4 flex gap-2 mb-3">
      <button
        v-for="mode in viewModes"
        :key="mode.key"
        @click="viewMode = mode.key"
        :class="[
          'px-3 py-1 rounded-full text-xs',
          viewMode === mode.key
            ? 'bg-primary-600 text-white'
            : 'bg-neutral-100 text-neutral-500'
        ]"
      >
        {{ mode.label }}
      </button>
    </div>

    <!-- 日历视图 -->
    <div v-if="searchResults === null && viewMode === 'calendar'" class="flex-1 px-4 pb-20">
      <div class="bg-white rounded-lg p-4">
        <!-- 星期标题 -->
        <div class="grid grid-cols-7 gap-1 mb-2">
          <div
            v-for="day in weekDays"
            :key="day"
            class="text-center text-xs text-neutral-400 py-1"
          >
            {{ day }}
          </div>
        </div>
        <!-- 日期网格 -->
        <div class="grid grid-cols-7 gap-1">
          <div
            v-for="(cell, index) in calendarCells"
            :key="index"
            @click="cell.day && handleDateClick(cell.day)"
            :class="[
              'aspect-square flex flex-col items-center justify-center text-xs rounded',
              cell.day ? 'cursor-pointer' : '',
              cell.hasDiary
                ? 'bg-primary-50 text-primary-700 font-medium'
                : cell.day ? 'text-neutral-600 hover:bg-neutral-50' : 'text-neutral-300'
            ]"
          >
            <span>{{ cell.day || '' }}</span>
            <span v-if="cell.hasDiary" class="w-1 h-1 rounded-full bg-primary-500 mt-0.5"></span>
          </div>
        </div>
      </div>

      <!-- 当月日记数量提示 -->
      <div v-if="calendarData.length > 0" class="text-center text-xs text-neutral-400 mt-3">
        本月共 {{ calendarData.length }} 篇日记
      </div>
    </div>

    <!-- 时间线视图 -->
    <div v-if="searchResults === null && viewMode === 'timeline'" class="flex-1 px-4 pb-20">
      <div v-if="timelineLoading" class="text-center text-sm text-neutral-400 py-6">
        加载中...
      </div>
      <div v-else-if="diaries.length === 0" class="text-center text-sm text-neutral-400 py-6">
        本月暂无日记
      </div>
      <div v-else class="space-y-3">
        <NuxtLink
          v-for="item in diaries"
          :key="item.id"
          :to="`/diary/${item.id}`"
          class="block bg-white rounded-lg p-3 active:bg-neutral-50"
        >
          <!-- 日期 -->
          <div class="text-xs text-neutral-400 mb-1">{{ item.diary_date }}</div>
          <!-- 内容预览 -->
          <div class="text-sm text-neutral-800 line-clamp-2">{{ item.original_text }}</div>
          <!-- 状态标签 -->
          <div class="flex items-center gap-2 mt-2">
            <span
              :class="[
                'text-xs px-2 py-0.5 rounded',
                item.status === 'draft' ? 'bg-neutral-100 text-neutral-500' :
                item.status === 'published' ? 'bg-blue-50 text-blue-500' :
                'bg-green-50 text-green-600'
              ]"
            >
              {{ statusLabel(item.status) }}
            </span>
            <span v-if="item.organized?.mood" class="text-xs text-primary-600">{{ item.organized.mood }}</span>
            <span v-if="item.organized?.location" class="text-xs text-neutral-400">{{ item.organized.location }}</span>
          </div>
        </NuxtLink>
      </div>
    </div>

    <!-- 右下角浮动 + 按钮 -->
    <NuxtLink
      to="/diary/new"
      class="fixed bottom-20 right-4 w-12 h-12 rounded-full bg-primary-600 text-white text-2xl flex items-center justify-center shadow-lg hover:bg-primary-700 transition-colors"
    >
      +
    </NuxtLink>
  </div>
</template>

<script setup lang="ts">
// 日记浏览页（主页）：使用 default 布局（带 Tab 栏）
definePageMeta({
  layout: 'default',
  middleware: 'auth',
})

const { api } = useApi()

// 当前年月
const now = new Date()
const currentYear = ref(now.getFullYear())
const currentMonth = ref(now.getMonth() + 1)

// 搜索关键词
const searchQuery = ref('')
const searchResults = ref<Diary[] | null>(null)

// 视图模式
const viewMode = ref<'calendar' | 'timeline'>('calendar')
const viewModes = [
  { key: 'calendar' as const, label: '日历' },
  { key: 'timeline' as const, label: '时间线' },
]

// 星期标题
const weekDays = ['日', '一', '二', '三', '四', '五', '六']

// 日历数据
const calendarData = ref<DiaryCalendarItem[]>([])

// 时间线日记列表
const diaries = ref<Diary[]>([])
const timelineLoading = ref(false)

// 日历单元格
const calendarCells = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value
  // 该月第一天是星期几（0=周日）
  const firstDay = new Date(year, month - 1, 1).getDay()
  // 该月天数
  const daysInMonth = new Date(year, month, 0).getDate()

  // 有日记的日期集合
  const diaryDates = new Set(calendarData.value.map(item => item.diary_date))

  const cells: { day: number | null; hasDiary: boolean }[] = []

  // 前置空白
  for (let i = 0; i < firstDay; i++) {
    cells.push({ day: null, hasDiary: false })
  }

  // 日期
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, hasDiary: diaryDates.has(dateStr) })
  }

  return cells
})

// 切换月份
const changeMonth = (delta: number) => {
  let m = currentMonth.value + delta
  let y = currentYear.value
  if (m < 1) {
    m = 12
    y--
  } else if (m > 12) {
    m = 1
    y++
  }
  currentMonth.value = m
  currentYear.value = y
  loadCalendar()
  if (viewMode.value === 'timeline') {
    loadTimeline()
  }
}

// 加载日历数据
const loadCalendar = async () => {
  try {
    calendarData.value = await api<DiaryCalendarItem[]>('/diaries/calendar', {
      params: { year: currentYear.value, month: currentMonth.value },
    })
  } catch (err) {
    console.error('加载日历失败', err)
    calendarData.value = []
  }
}

// 加载时间线数据
const loadTimeline = async () => {
  const year = currentYear.value
  const month = currentMonth.value
  // 构造当月起止日期
  const startDate = `${year}-${String(month).padStart(2, '0')}-01`
  const lastDay = new Date(year, month, 0).getDate()
  const endDate = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`

  timelineLoading.value = true
  try {
    diaries.value = await api<Diary[]>('/diaries', {
      params: { start_date: startDate, end_date: endDate },
    })
  } catch (err) {
    console.error('加载日记列表失败', err)
    diaries.value = []
  } finally {
    timelineLoading.value = false
  }
}

// 点击日期
const handleDateClick = async (day: number) => {
  const year = currentYear.value
  const month = currentMonth.value
  const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  try {
    const dayDiaries = await api<Diary[]>('/diaries', {
      params: { start_date: dateStr, end_date: dateStr },
    })
    if (dayDiaries.length > 0) {
      navigateTo(`/diary/${dayDiaries[0].id}`)
    }
  } catch (err) {
    console.error('查询日期日记失败', err)
  }
}

// 搜索
const handleSearch = async () => {
  if (!searchQuery.value.trim()) return
  try {
    searchResults.value = await api<Diary[]>('/diaries/search', {
      params: { q: searchQuery.value.trim() },
    })
  } catch (err) {
    console.error('搜索失败', err)
    searchResults.value = []
  }
}

// 清除搜索
const clearSearch = () => {
  searchQuery.value = ''
  searchResults.value = null
}

// 状态标签
const statusLabel = (status: string) => {
  switch (status) {
    case 'draft': return '草稿'
    case 'published': return '已发布'
    case 'organized': return '已整理'
    default: return status
  }
}

// 监听视图模式切换
watch(viewMode, (newMode) => {
  if (newMode === 'timeline' && diaries.value.length === 0) {
    loadTimeline()
  }
})

// 初始化加载日历
onMounted(() => {
  loadCalendar()
})
</script>
