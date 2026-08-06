<template>
  <div class="min-h-dvh flex flex-col">
    <!-- 顶部月份导航 -->
    <div class="sticky top-0 z-30 bg-white border-b border-neutral-200">
      <div class="flex items-center justify-between px-4 h-nav">
        <button v-if="viewMode === 'calendar'" @click="changeMonth(-1)" class="text-neutral-400 text-lg w-8 h-8 flex items-center justify-center">‹</button>
        <span v-else class="w-8 h-8" aria-hidden="true" />
        <span class="text-base font-medium text-neutral-800">{{ viewMode === 'favorites' ? '我的收藏' : viewMode === 'timeline' ? '全部日记' : `${currentYear}年${currentMonth}月` }}</span>
        <button v-if="viewMode === 'calendar'" @click="changeMonth(1)" class="text-neutral-400 text-lg w-8 h-8 flex items-center justify-center">›</button>
        <span v-else class="w-8 h-8" aria-hidden="true" />
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

    <!-- 视图切换：日历 / 时间线 / 收藏 -->
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

    <!-- 收藏视图 -->
    <div v-if="searchResults === null && viewMode === 'favorites'" class="flex-1 px-4 pb-20">
      <div class="flex gap-2 mb-3">
        <button
          v-for="filter in favoriteFilters"
          :key="filter.key"
          type="button"
          class="px-3 py-1 rounded-full text-xs"
          :class="favoriteFilter === filter.key ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-500'"
          @click="favoriteFilter = filter.key"
        >
          {{ filter.label }}
        </button>
      </div>
      <div v-if="favoritesLoading" class="text-center text-sm text-neutral-400 py-6">加载中...</div>
      <div v-else-if="filteredFavorites.length === 0" class="text-center text-sm text-neutral-400 py-10">
        还没有收藏的日记或事件
      </div>
      <div v-else class="space-y-3">
        <NuxtLink
          v-for="item in filteredFavorites"
          :key="item.id"
          :to="favoriteLink(item)"
          class="block bg-white rounded-lg p-3 active:bg-neutral-50"
        >
          <template v-if="item.favorite_type === 'diary'">
            <div class="flex items-center justify-between gap-3">
              <span class="text-xs font-medium text-amber-600">★ 日记</span>
              <span class="text-xs text-neutral-400">{{ item.diary.diary_date }}</span>
            </div>
            <div class="mt-1 text-sm font-medium text-neutral-800">{{ item.diary.organized?.title || '无标题日记' }}</div>
            <div v-if="item.diary.organized?.summary" class="mt-1 text-xs text-neutral-500 line-clamp-2">
              {{ item.diary.organized.summary }}
            </div>
            <div v-else class="mt-1 text-xs text-neutral-500 line-clamp-2">{{ item.diary.original_text }}</div>
          </template>
          <template v-else-if="item.event">
            <div class="flex items-center justify-between gap-3">
              <span class="text-xs font-medium text-amber-600">★ 事件</span>
              <span class="text-xs text-neutral-400">{{ item.diary.diary_date }}</span>
            </div>
            <div class="mt-1 text-sm font-medium text-neutral-800">{{ item.event.event_title || '未命名事件' }}</div>
            <div class="mt-1 text-xs text-neutral-500 line-clamp-2">{{ eventPreview(item.event) }}</div>
            <div class="mt-2 text-xs text-neutral-400">来自《{{ item.diary.organized?.title || '无标题日记' }}》</div>
          </template>
        </NuxtLink>
      </div>
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
            <span v-if="cell.diaryCount === 1" class="w-1 h-1 rounded-full bg-primary-500 mt-0.5"></span>
            <span v-else-if="cell.diaryCount > 1" class="text-[10px] text-primary-600 mt-0.5 leading-none">{{ cell.diaryCount }}篇</span>
          </div>
        </div>
      </div>

      <!-- 当月日记数量提示 -->
      <div v-if="totalMonthCount > 0" class="text-center text-xs text-neutral-400 mt-3">
        本月共 {{ totalMonthCount }} 篇日记
      </div>
    </div>

    <!-- 时间线视图 -->
    <div v-if="searchResults === null && viewMode === 'timeline'" class="flex-1 px-4 pb-20">
      <div v-if="timelineLoading" class="text-center text-sm text-neutral-400 py-6">
        加载中...
      </div>
      <div v-else-if="diaries.length === 0" class="text-center text-sm text-neutral-400 py-6">
        暂无日记
      </div>
      <div v-else class="space-y-3">
        <NuxtLink
          v-for="(item, index) in diaries"
          :key="item.id"
          :to="`/diary/${item.id}`"
          class="block bg-white rounded-lg p-3 active:bg-neutral-50"
        >
          <div v-if="index === 0 || diaries[index - 1].diary_date !== item.diary_date" class="-mt-1 mb-2 border-b border-neutral-100 pb-2 text-sm font-medium text-neutral-700">
            {{ formatDiaryDate(item.diary_date) }}
          </div>
          <!-- 创建时间 YYYY-MM-DD HH:mm -->
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs text-neutral-400">{{ formatTime(item.created_at) }}</span>
          </div>
          <!-- 已整理/已分析：显示标题+摘要 -->
          <template v-if="item.organized">
            <div class="text-sm font-medium text-neutral-800">{{ item.organized.title || '无标题' }}</div>
            <div v-if="item.organized.summary" class="text-xs text-neutral-500 mt-1 line-clamp-2">{{ item.organized.summary }}</div>
          </template>
          <!-- 已保存：显示原文预览 -->
          <template v-else>
            <p class="text-sm text-neutral-600 line-clamp-2">{{ item.original_text }}</p>
          </template>
          <!-- 状态标签 -->
          <div class="flex items-center gap-2 mt-2">
            <span
              :class="[
                'text-xs px-2 py-0.5 rounded',
                item.status === 'saved' ? 'bg-blue-50 text-blue-500' :
                item.status === 'analyzed' ? 'bg-purple-50 text-purple-600' :
                'bg-green-50 text-green-600'
              ]"
            >
              {{ statusLabel(item.status) }}
            </span>
            <span v-if="item.organized?.mood" class="text-xs text-primary-600">{{ item.organized.mood }}</span>
            <span v-if="item.organized?.location" class="text-xs text-neutral-400">{{ item.organized.location }}</span>
          </div>
          <!-- 已分析卡片标签 -->
          <div v-if="item.status === 'analyzed' && topicDiaryTags(item.tags).length > 0" class="flex flex-wrap mt-2">
            <TagBadge v-for="tag in topicDiaryTags(item.tags).slice(0, 5)" :key="tag.id" :tag="tag" />
            <span v-if="topicDiaryTags(item.tags).length > 5" class="text-xs text-neutral-400 ml-1">+{{ topicDiaryTags(item.tags).length - 5 }}</span>
          </div>
        </NuxtLink>
        <div ref="timelineSentinel" class="h-8 text-center text-xs text-neutral-400">
          {{ timelineLoadingMore ? '加载中...' : timelineHasMore ? '继续下滑加载更多' : '已显示全部日记' }}
        </div>
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
import { addDaysToDateKey, dateKeyInAppTimeZone, formatDateTimeInAppTimeZone } from '~/utils/datetime'
definePageMeta({
  layout: 'default',
  middleware: 'auth',
  keepalive: true,
})

const { api } = useApi()

// 当前年月
const todayParts = dateKeyInAppTimeZone().split('-').map(Number)
const currentYear = ref(todayParts[0])
const currentMonth = ref(todayParts[1])

// 搜索关键词
const searchQuery = ref('')
const searchResults = ref<Diary[] | null>(null)

// 视图模式
const viewMode = ref<'calendar' | 'timeline' | 'favorites'>('calendar')
const viewModes = [
  { key: 'calendar' as const, label: '日历' },
  { key: 'timeline' as const, label: '时间线' },
  { key: 'favorites' as const, label: '★ 收藏' },
]

// 星期标题
const weekDays = ['日', '一', '二', '三', '四', '五', '六']

// 日历数据：dateStr → Diary[]（同一天可能多条，存完整 Diary 以显示标题/摘要）
const calendarData = ref<Map<string, Diary[]>>(new Map())

// 当月日记总数
const totalMonthCount = computed(() => {
  let total = 0
  for (const items of calendarData.value.values()) {
    total += items.length
  }
  return total
})

// 时间线日记列表
const diaries = ref<Diary[]>([])
const timelineLoading = ref(false)
const timelineLoadingMore = ref(false)
const timelineHasMore = ref(true)
const timelineOffset = ref(0)
const timelinePageSize = 20
const timelineSentinel = ref<HTMLElement | null>(null)
let timelineObserver: IntersectionObserver | null = null
const pageStateKey = 'diary-platform:diary-index-state'
const browseCache = useState<{
  calendarKey: string | null
  calendarItems: Diary[]
  calendarLoaded: boolean
  timelineItems: Diary[]
  timelineLoaded: boolean
  timelineHasMore: boolean
  timelineOffset: number
}>('diary-browse-cache', () => ({
  calendarKey: null,
  calendarItems: [],
  calendarLoaded: false,
  timelineItems: [],
  timelineLoaded: false,
  timelineHasMore: true,
  timelineOffset: 0,
}))
const favorites = ref<FavoriteItem[]>([])
const favoritesLoading = ref(false)
const favoriteFilter = ref<'all' | 'diary' | 'event'>('all')
const favoriteFilters = [
  { key: 'all' as const, label: '全部' },
  { key: 'diary' as const, label: '日记' },
  { key: 'event' as const, label: '事件' },
]
const filteredFavorites = computed(() => favoriteFilter.value === 'all'
  ? favorites.value
  : favorites.value.filter(item => item.favorite_type === favoriteFilter.value))

// 日历单元格
const calendarCells = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value
  // 该月第一天是星期几（0=周日）
  const firstDay = new Date(year, month - 1, 1).getDay()
  // 该月天数
  const daysInMonth = new Date(year, month, 0).getDate()

  const cells: { day: number | null; hasDiary: boolean; diaryCount: number }[] = []

  // 前置空白
  for (let i = 0; i < firstDay; i++) {
    cells.push({ day: null, hasDiary: false, diaryCount: 0 })
  }

  // 日期
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const items = calendarData.value.get(dateStr) || []
    cells.push({ day: d, hasDiary: items.length > 0, diaryCount: items.length })
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
}

// 加载日历数据（获取完整 Diary 对象以显示标题/摘要）
const loadCalendar = async () => {
  const year = currentYear.value
  const month = currentMonth.value
  const startDate = `${year}-${String(month).padStart(2, '0')}-01`
  const lastDay = new Date(year, month, 0).getDate()
  const endDate = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  const cacheKey = `${startDate}:${endDate}`

  if (browseCache.value.calendarLoaded && browseCache.value.calendarKey === cacheKey) {
    calendarData.value = groupDiariesByDate(browseCache.value.calendarItems)
    return
  }

  try {
    const items = await api<Diary[]>('/diaries', {
      params: { start_date: startDate, end_date: endDate },
    })
    browseCache.value.calendarKey = cacheKey
    browseCache.value.calendarItems = items
    browseCache.value.calendarLoaded = true
    calendarData.value = groupDiariesByDate(items)
  } catch (err) {
    console.error('加载日历失败', err)
    calendarData.value = new Map()
  }
}

// 加载时间线数据
const loadTimeline = async () => {
  if (browseCache.value.timelineLoaded) {
    diaries.value = [...browseCache.value.timelineItems]
    timelineOffset.value = browseCache.value.timelineOffset
    timelineHasMore.value = browseCache.value.timelineHasMore
    return
  }
  timelineLoading.value = true
  timelineOffset.value = 0
  timelineHasMore.value = true
  try {
    diaries.value = await api<Diary[]>('/diaries', {
      params: { limit: timelinePageSize, offset: 0 },
    })
    timelineOffset.value = diaries.value.length
    timelineHasMore.value = diaries.value.length === timelinePageSize
    browseCache.value.timelineItems = [...diaries.value]
    browseCache.value.timelineOffset = timelineOffset.value
    browseCache.value.timelineHasMore = timelineHasMore.value
    browseCache.value.timelineLoaded = true
  } catch (err) {
    console.error('加载日记列表失败', err)
    diaries.value = []
  } finally {
    timelineLoading.value = false
  }
}

const loadMoreTimeline = async () => {
  if (timelineLoading.value || timelineLoadingMore.value || !timelineHasMore.value) return
  timelineLoadingMore.value = true
  try {
    const items = await api<Diary[]>('/diaries', {
      params: { limit: timelinePageSize, offset: timelineOffset.value },
    })
    diaries.value.push(...items)
    timelineOffset.value += items.length
    timelineHasMore.value = items.length === timelinePageSize
    browseCache.value.timelineItems = [...diaries.value]
    browseCache.value.timelineOffset = timelineOffset.value
    browseCache.value.timelineHasMore = timelineHasMore.value
  } catch (err) {
    console.error('加载更多日记失败', err)
  } finally {
    timelineLoadingMore.value = false
  }
}

const loadFavorites = async () => {
  favoritesLoading.value = true
  try {
    favorites.value = await api<FavoriteItem[]>('/diaries/favorites')
  } catch (err) {
    console.error('加载收藏失败', err)
    favorites.value = []
  } finally {
    favoritesLoading.value = false
  }
}

const eventPreview = (event: DiaryEvent) => event.body?.join(' ') || event.feeling?.join(' ') || '暂无事件正文'

const groupDiariesByDate = (items: Diary[]) => {
  const map = new Map<string, Diary[]>()
  for (const item of items) {
    const list = map.get(item.diary_date)
    if (list) list.push(item)
    else map.set(item.diary_date, [item])
  }
  return map
}

const favoriteLink = (item: FavoriteItem) => item.favorite_type === 'event' && item.event
  ? `/diary/${item.diary.id}?event=${item.event.id}`
  : `/diary/${item.diary.id}`

const dateStringForDay = (day: number) => {
  return `${currentYear.value}-${String(currentMonth.value).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// 点击日期：无日记跳新增，1 条跳详情，多条跳日期列表页
const handleDateClick = (day: number) => {
  const dateStr = dateStringForDay(day)

  const cached = calendarData.value.get(dateStr)
  if (!cached || cached.length === 0) {
    navigateTo(`/diary/new?date=${dateStr}`)
    return
  }

  if (cached.length === 1) {
    navigateTo(`/diary/${cached[0].id}`)
  } else {
    navigateTo(`/diary/date/${dateStr}`)
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

// ── 快捷日期筛选 ──
type FilterKey = 'today' | 'yesterday' | 'week' | 'last7' | 'month'

const filters: { key: FilterKey; label: string }[] = [
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
  { key: 'week', label: '本周' },
  { key: 'last7', label: '近7天' },
  { key: 'month', label: '本月' },
]

const activeFilter = ref<FilterKey | null>(null)
const filterResults = ref<Diary[]>([])
const filterLoading = ref(false)

const activeFilterLabel = computed(() => {
  return filters.find(f => f.key === activeFilter.value)?.label || ''
})

// 根据 filterKey 计算起止日期
const getFilterRange = (key: FilterKey): { start: string; end: string } => {
  const today = dateKeyInAppTimeZone()

  switch (key) {
    case 'today':
      return { start: today, end: today }
    case 'yesterday': {
      const yesterday = addDaysToDateKey(today, -1)
      return { start: yesterday, end: yesterday }
    }
    case 'week': {
      const [year, month, day] = today.split('-').map(Number)
      const weekday = new Date(Date.UTC(year, month - 1, day, 12)).getUTCDay()
      const monday = addDaysToDateKey(today, -(weekday === 0 ? 6 : weekday - 1))
      return { start: monday, end: today }
    }
    case 'last7': {
      return { start: addDaysToDateKey(today, -6), end: today }
    }
    case 'month': {
      return { start: `${today.slice(0, 7)}-01`, end: today }
    }
  }
}

const toggleFilter = async (key: FilterKey) => {
  try {
    const { start, end } = getFilterRange(key)
    const data = await api<Diary[]>('/diaries', {
      params: { start_date: start, end_date: end },
    })
    const analyzed = data.filter(d => d.status === 'analyzed')
    if (analyzed.length === 0) return

    if (analyzed.length === 1) {
      navigateTo(`/diary/${analyzed[0].id}`)
    } else if (start === end) {
      // 单日多条 → 日期列表页
      navigateTo(`/diary/date/${start}`)
    } else {
      // 多日多条 → 跳到最新一条的日期列表
      analyzed.sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0
        return tb - ta
      })
      navigateTo(`/diary/date/${analyzed[0].diary_date}`)
    }
  } catch (err) {
    console.error('筛选日记失败', err)
  }
}

const clearFilter = () => {
  activeFilter.value = null
}

// 日期格式化：M月D日
const formatDateShort = (dateStr: string) => {
  if (!dateStr) return ''
  const [, m, d] = dateStr.split('-')
  return `${parseInt(m)}月${parseInt(d)}日`
}

const formatDiaryDate = (dateStr: string) => {
  const [year, month, day] = dateStr.split('-')
  return `${year}年${parseInt(month)}月${parseInt(day)}日`
}

// 时间格式化（YYYY-MM-DD HH:mm）
const formatTime = (dateStr?: string) => {
  return formatDateTimeInAppTimeZone(dateStr)
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

const topicDiaryTags = (tags?: any[]) => {
  return sortedDiaryTags(tags || []).filter(tag => tag.type === 'topic')
}

// 状态标签
const statusLabel = (status: string) => {
  switch (status) {
    case 'saved': return '已保存'
    case 'organized': return '已整理'
    case 'analyzed': return '已分析'
    default: return status
  }
}

// 监听视图模式切换
watch(viewMode, (newMode) => {
  if (newMode === 'timeline' && diaries.value.length === 0) {
    loadTimeline()
  }
  if (newMode === 'favorites') {
    loadFavorites()
  }
})

const savePageState = () => {
  if (!import.meta.client) return
  sessionStorage.setItem(pageStateKey, JSON.stringify({
    viewMode: viewMode.value,
    year: currentYear.value,
    month: currentMonth.value,
    scrollY: window.scrollY,
  }))
}

// 初始化加载日历
onMounted(() => {
  const saved = sessionStorage.getItem(pageStateKey)
  if (saved) {
    try {
      const state = JSON.parse(saved)
      if (['calendar', 'timeline', 'favorites'].includes(state.viewMode)) viewMode.value = state.viewMode
      if (Number.isInteger(state.year) && Number.isInteger(state.month)) {
        currentYear.value = state.year
        currentMonth.value = state.month
      }
      nextTick(() => window.scrollTo(0, Number(state.scrollY) || 0))
    } catch {
      sessionStorage.removeItem(pageStateKey)
    }
  }
  loadCalendar()
  timelineObserver = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) loadMoreTimeline()
  })
  if (timelineSentinel.value) timelineObserver.observe(timelineSentinel.value)
  window.addEventListener('scroll', savePageState, { passive: true })
})

watch(timelineSentinel, element => {
  if (element && timelineObserver) timelineObserver.observe(element)
})

onBeforeUnmount(() => {
  savePageState()
  timelineObserver?.disconnect()
  window.removeEventListener('scroll', savePageState)
})
</script>
