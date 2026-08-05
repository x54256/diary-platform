import type { ReviewDomainCode } from '~/types'

// 回顾领域码 → 中文标签（新五领域，唯一映射来源）
export const REVIEW_DOMAIN_LABELS: Record<ReviewDomainCode, string> = {
  WORK_OUTPUT: '工作产出',
  PERSONAL_GROWTH: '个人成长',
  HEALTH_WELLBEING: '身心健康',
  RELATIONSHIPS: '人情关系',
  LIFE_AFFAIRS: '生活事务',
}

// 事项状态码 → 中文标签（六态）
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  OPEN: '待推进',
  IN_PROGRESS: '进行中',
  BLOCKED: '受阻',
  COMPLETED: '已完成',
  STOPPED: '已停止',
  UNKNOWN: '未知',
}

// 状态徽标：日记式语义浅底方徽章
export const REVIEW_STATUS_BADGE_CLASSES: Record<string, string> = {
  COMPLETED: 'bg-green-50 text-green-600',
  IN_PROGRESS: 'bg-blue-50 text-blue-500',
  BLOCKED: 'bg-amber-50 text-amber-700',
  OPEN: 'bg-neutral-100 text-neutral-500',
  STOPPED: 'bg-neutral-100 text-neutral-500',
  UNKNOWN: 'bg-neutral-100 text-neutral-400',
}

// 「单日」中性轮廓徽章
export const SINGLE_DAY_BADGE_CLASS = 'border border-neutral-300 text-neutral-500'

export const reviewDomainLabel = (code: ReviewDomainCode) => REVIEW_DOMAIN_LABELS[code] || code
export const reviewStatusLabel = (code?: string) => (code && REVIEW_STATUS_LABELS[code]) || ''
export const reviewStatusBadgeClass = (code?: string) => (code && REVIEW_STATUS_BADGE_CLASSES[code]) || 'bg-neutral-100 text-neutral-400'
