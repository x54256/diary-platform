// 用户信息
export interface User {
  id: string
  username: string
  created_at?: string
}

// 日记整理内容（后端字段可能为 null）
export interface DiaryOrganized {
  id: string
  title: string | null
  summary: string | null
  content: string | null
  mood: string | null
  location: string | null
  introduction: string | null
  trivia: string[] | null
  plans: string[] | null
  events: DiaryEvent[]
  check_logs: CheckLog[]
  clean_check_logs: CleanCheckLog[]
  analysis: AnalysisRun | null
}

// 日记状态：已保存 → 已整理 → 已分析
export type DiaryStatus = 'saved' | 'organized' | 'analyzed'

// 日记
export interface Diary {
  id: string
  user_id?: string
  diary_date: string
  status: DiaryStatus
  original_text: string
  created_at?: string
  updated_at?: string
  organized?: DiaryOrganized | null
  tags?: Tag[]
}

// 标签类型
export type TagType = 'domain' | 'topic' | 'person_object' | 'psychological' | 'knowledge'

// 标签
export interface Tag {
  id: string
  name: string
  type: TagType | null
  created_at?: string
}

// 事件级标签（旧结构兼容）
export interface EventTags {
  domain: string[]
  topic: string[]
  person_object: string[]
  psychological: string[]
  knowledge: string[]
}

export type AnalysisScope = 'DIARY' | 'EVENT'

export type AnalysisType =
  | 'EMOTION'
  | 'BEHAVIOR_DECISION'
  | 'SELF_UNDERSTANDING'
  | 'ACTION_SUGGESTION'
  | 'COGNITIVE_CALIBRATION'
  | 'COGNITIVE_ENHANCEMENT'
  | 'QUESTION_ANSWER'

export interface AnalysisFeedback {
  id: string
  rating: number
  comment: string | null
  is_inherited: boolean
  source_feedback_id: string | null
  updated_at: string | null
}

export interface AnalysisItem {
  id: string
  content: string
  question?: string | null
  sort_order: number
}

export interface AnalysisSection {
  scope: AnalysisScope
  event_id: string | null
  analysis_type: AnalysisType
  title: string
  items: AnalysisItem[]
  feedback: AnalysisFeedback | null
}

export interface AnalysisRun {
  id: string
  mood: string | null
  status: 'CURRENT' | 'ARCHIVED'
  sections: AnalysisSection[]
  created_at: string | null
  updated_at: string | null
}

// 日记事件
export interface DiaryEvent {
  id: string
  event_title: string | null
  body: string[]
  feeling: string[]
  reflection: string[]
  event_tags: EventTags | null
  sort_order: number
  tags: Tag[]
  analysis: AnalysisSection[] | null
}

// 审核日志
export interface CheckLog {
  id: string
  check_item: string
  status: string
  target: string | null
  issue: string | null
  before: string | null
  after: string | null
  reason: string | null
}

// 清洗审核日志
export interface CleanCheckLog {
  id: string
  issue: string | null
  before: string | null
  after: string | null
  reason: string | null
}

// 日历项
export interface DiaryCalendarItem {
  diary_date: string
  mood: string | null
  status: string
}

export type ScheduleStatus = 'pending' | 'completed' | 'deleted'
export interface ScheduleOccurrence {
  id: string
  task_id: string
  scheduled_date: string
  title: string
  is_all_day: boolean
  start_time: string | null
  end_time: string | null
  status: ScheduleStatus
  completed_at: string | null
  execution_note: string | null
  recurrence_type: 'NONE' | 'DAILY' | 'WEEKLY' | 'MONTHLY_DATE' | 'MONTHLY_NTH_WEEKDAY' | 'YEARLY' | 'WORKDAY' | 'REST_DAY'
  recurrence_until: string | null
  recurrence_count: number | null
  interval: number
  weekdays: number[]
  nth_week: number | null
  nth_weekday: number | null
}

export type TranscriptionBatchStatus =
  | 'COLLECTING' | 'QUEUED' | 'PROCESSING' | 'PARTIAL_FAILED'
  | 'FINALIZING' | 'COMPLETED' | 'CANCELLED' | 'EXPIRED'

export type TranscriptionItemStatus =
  | 'UPLOADING' | 'UPLOADED' | 'QUEUED' | 'SUBMITTING'
  | 'SUBMITTED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'DELETED'

export interface TranscriptionItem {
  id: string
  sort_order: number
  filename: string
  file_size: number
  status: TranscriptionItemStatus
  progress?: number
  transcript_preview?: string | null
  error_code?: string | null
  error_message?: string | null
  retry_count: number
  local?: boolean
}

export interface TranscriptionBatch {
  id: string
  diary_date: string | null
  status: TranscriptionBatchStatus
  diary_id: string | null
  error_message?: string | null
  expires_at?: string | null
  items: TranscriptionItem[]
}

// 事件更新请求 payload
export interface DiaryEventUpdatePayload {
  id: string
  event_title?: string
  body?: string[]
  feeling?: string[]
  reflection?: string[]
}

// 对话消息
export interface DialogMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

// 对话来源类型
export type DialogSourceType = 'diary_detail' | 'review' | 'ai_companion'

// 对话
export interface Dialog {
  id: string
  source_type: DialogSourceType
  source_id?: string
  messages: DialogMessage[]
}
