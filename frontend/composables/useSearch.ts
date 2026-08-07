import { ref, computed } from 'vue'
import type { SearchEventResult } from '~/types'
import { useApi } from '~/composables/useApi'

const PAGE_SIZE = 20

/**
 * 统一搜索状态封装：关键词 / 日期范围 / 分页 offset / 加载态 / 无限滚动回调。
 * 复用现有 /diaries/search 端点，结果以事件卡形式累积渲染。
 */
export function useSearch() {
  const query = ref('')
  const startDate = ref<string | null>(null)
  const endDate = ref<string | null>(null)
  const results = ref<SearchEventResult[]>([])
  const total = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const hasMore = computed(() => results.value.length < total.value)

  const { api } = useApi()

  const buildParams = () => {
    const params: Record<string, string | number> = {
      q: query.value.trim(),
      limit: PAGE_SIZE,
      offset: offset.value,
      // 决策 9：前端始终请求 hybrid（关键词 + 语义 RRF 融合），不暴露模式切换 UI。
      mode: 'hybrid',
    }
    if (startDate.value) params.start_date = startDate.value
    if (endDate.value) params.end_date = endDate.value
    return params
  }

  /**
   * 执行搜索。
   * @param replace true=新搜索（重置分页）；false=无限滚动加载更多（累加结果）。
   */
  const search = async (replace: boolean) => {
    const text = query.value.trim()
    if (!text) return
    loading.value = true
    error.value = null
    try {
      const params = {
        ...buildParams(),
        offset: replace ? 0 : offset.value,
      }
      const data = await api<{ items: SearchEventResult[]; total: number }>('/diaries/search', { params })
      if (replace) {
        results.value = data.items
        offset.value = data.items.length
        total.value = data.total
      } else {
        results.value.push(...data.items)
        offset.value += data.items.length
      }
    } catch (err) {
      error.value = '搜索失败，请稍后重试'
      console.error('搜索失败', err)
      if (replace) {
        results.value = []
        total.value = 0
        offset.value = 0
      }
    } finally {
      loading.value = false
    }
  }

  /** 重置全部搜索状态（清除搜索时调用）。 */
  const reset = () => {
    results.value = []
    total.value = 0
    offset.value = 0
    loading.value = false
    error.value = null
  }

  return {
    query,
    startDate,
    endDate,
    results,
    total,
    loading,
    error,
    hasMore,
    search,
    reset,
  }
}
