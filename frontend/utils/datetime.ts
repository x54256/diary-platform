export const APP_TIME_ZONE = 'Asia/Shanghai'

const partsOf = (value: Date | string | number) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: APP_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(typeof value === 'string' || typeof value === 'number' ? new Date(value) : value)
  return Object.fromEntries(parts.filter(item => item.type !== 'literal').map(item => [item.type, item.value])) as Record<string, string>
}

export const dateKeyInAppTimeZone = (value: Date | string | number = new Date()) => {
  const parts = partsOf(value)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export const formatDateTimeInAppTimeZone = (value?: string | number | Date) => {
  if (value === undefined || value === null || Number.isNaN(new Date(value).getTime())) return ''
  const parts = partsOf(value)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}

export const formatDateInAppTimeZone = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return ''
  const [year, month, day] = value.split('-')
  return `${Number(month)}月${Number(day)}日`
}

export const weekDayInAppTimeZone = (value: string) => {
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return ''
  const weekday = new Intl.DateTimeFormat('zh-CN', { timeZone: APP_TIME_ZONE, weekday: 'short' }).format(new Date(Date.UTC(year, month - 1, day, 12)))
  return weekday.replace('星期', '周')
}

export const addDaysToDateKey = (value: string, days: number) => {
  const [year, month, day] = value.split('-').map(Number)
  const result = new Date(Date.UTC(year, month - 1, day + days, 12))
  return `${result.getUTCFullYear()}-${String(result.getUTCMonth() + 1).padStart(2, '0')}-${String(result.getUTCDate()).padStart(2, '0')}`
}
