const VALID_TIME_TAG = /<time\s+value="\d{4}-\d{2}-\d{2}\s+星期[一二三四五六日](?:\s+\d{2}:\d{2})?">([\s\S]*?)<\/time>/gi

// Vue 插值会继续转义返回值；这里只去掉格式合法的上游时间标签。
export const knowledgePlainText = (value: string | string[] | null | undefined): string =>
  (Array.isArray(value) ? value.join('\n\n') : value || '').replace(VALID_TIME_TAG, '$1')

export const formatKnowledgeDateTime = (date: string, time?: string | null): string => {
  const [year, month, day] = date.split('-').map(Number)
  const dateText = Number.isFinite(year) && Number.isFinite(month) && Number.isFinite(day)
    ? `${year}年${month}月${day}日`
    : date
  return time ? `${dateText} ${time.slice(0, 5)}` : dateText
}
