// 用户信息
export interface User {
  id: string
  username: string
  created_at?: string
}

export interface HotWord {
  id: string
  text: string
  created_at?: string
  updated_at?: string
}

export type PersonGender = 'male' | 'female' | 'unknown'

export interface PersonRelation {
  id: string
  name: string
  common_names: string[]
  gender: PersonGender
  relation: string
  created_at?: string
  updated_at?: string
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
  is_favorite: boolean
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
  is_favorite: boolean
  ai_importance?: 'HIGH' | 'MEDIUM' | 'LOW' | null
  ai_importance_reason?: string | null
  user_importance?: 'HIGH' | 'MEDIUM' | 'LOW' | null
  user_importance_reason?: string | null
  importance_origin?: string | null
}

export interface FavoriteItem {
  id: string
  favorite_type: 'diary' | 'event'
  created_at: string
  diary: Diary
  event: DiaryEvent | null
}

export type DiaryAnnotationTargetType =
  | 'EVENT_BODY'
  | 'EVENT_FEELING'
  | 'EVENT_REFLECTION'
  | 'ANALYSIS_ITEM'

export interface DiaryAnnotationComment {
  id: string
  content: string
  created_at: string
  updated_at: string
}

export interface DiaryAnnotation {
  id: string
  diary_id: string
  target_type: DiaryAnnotationTargetType
  event_id: string | null
  field_name: 'body' | 'feeling' | 'reflection' | null
  analysis_item_id: string | null
  start_paragraph: number
  start_offset: number
  end_paragraph: number
  end_offset: number
  selected_text: string
  context_before: string | null
  context_after: string | null
  created_at: string
  updated_at: string
  deleted_at?: string | null
  comments: DiaryAnnotationComment[]
}

export interface DiaryAnnotationSelection {
  target_type: DiaryAnnotationTargetType
  event_id?: string
  field_name?: 'body' | 'feeling' | 'reflection'
  analysis_item_id?: string
  start_paragraph: number
  start_offset: number
  end_paragraph: number
  end_offset: number
  selected_text: string
  context_before: string
  context_after: string
}

export interface DiaryAnnotationClick {
  annotationId: string
  selectedText: string
  clientX: number
  clientY: number
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

export type DiaryActionStatus = 'pending' | 'completed'
export type DiaryActionSyncStatus = 'unsynced' | 'synced' | 'schedule_deleted'
export type DiaryActionRecurrenceType = ScheduleOccurrence['recurrence_type']

export interface DiaryActionItem {
  id: string
  diary_id: string
  generation_run_id: string
  source_kind: 'PLAN' | 'SUGGESTION' | 'MERGED'
  source_refs: Record<string, unknown>
  title: string
  is_all_day: boolean
  start_date: string
  start_time: string | null
  end_time: string | null
  recurrence_type: DiaryActionRecurrenceType
  interval: number
  weekdays: number[]
  month_day: number | null
  recurrence_month: number | null
  nth_week: number | null
  nth_weekday: number | null
  recurrence_until: string | null
  recurrence_count: number | null
  status: DiaryActionStatus
  completed_at: string | null
  user_modified: boolean
  sort_order: number
  schedule: {
    task_id: string | null
    occurrence_id: string | null
    status: DiaryActionSyncStatus
  }
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
  user_importance?: 'HIGH' | 'MEDIUM' | 'LOW' | null
  user_importance_reason?: string | null
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

// 定期回顾
export type ReviewType = 'WEEK' | 'MONTH'
export type ReviewDomainCode =
  | 'WORK_CAREER'
  | 'HEALTH_WELLBEING'
  | 'RELATIONSHIPS_SOCIAL'
  | 'LEARNING_GROWTH'
  | 'LIFE_RESOURCES'
  | 'LEISURE_EXPERIENCE'

export interface ReviewSummary {
  id: string
  review_type: ReviewType
  period_start: string
  period_end: string
  current_version_id: string | null
  current_version_no: number | null
  version_count?: number
  is_unread: boolean
  summary: string | null
  analysis_stale?: boolean
  updated_at: string | null
}

export interface ReviewEventThread {
  id?: string
  thread_id?: string
  thread_key: string
  title: string
  narrative: string
  primary_domain: ReviewDomainCode
  related_domains?: ReviewDomainCode[]
  continuity_status?: string
  current_status?: string
  nodes?: Array<{ node_key: string; source_date: string; fact: string; source_ids: string[] }>
  prior_context_source_ids?: string[]
  user_overridden?: boolean
  narrative_correction_source_id?: string | null
}

export interface ReviewCoreFocus {
  focus_key: string
  label: string
  thread_keys: string[]
  source_ids: string[]
}

export interface ReviewEventDomain {
  domain_code: ReviewDomainCode
  core_focus?: ReviewCoreFocus[]
  event_threads: ReviewEventThread[]
}

export interface ReviewAnalysisItemData {
  id?: string
  analysis_item_id?: string
  analysis_key: string
  angle_code: string
  claim: string
  supporting_source_ids: string[]
  counterevidence_source_ids?: string[]
  context_source_ids?: string[]
  thread_keys?: string[]
  related_domains?: ReviewDomainCode[]
}

export interface ReviewAnalysisDomain {
  domain_code: ReviewDomainCode
  analysis_items: ReviewAnalysisItemData[]
}

export interface ReviewEventDocument {
  domains: ReviewEventDomain[]
  other_matters?: Array<{ title: string; narrative: string; source_ids: string[] }>
}

export interface ReviewAnalysisDocument {
  domains: ReviewAnalysisDomain[]
}

export type ReviewActionStatus = 'CANDIDATE' | 'CONFIRMED' | 'IGNORED'

export interface ReviewAction {
  id: string
  version_id?: string
  domain_code?: ReviewDomainCode
  primary_domain: ReviewDomainCode
  related_domains?: ReviewDomainCode[]
  content: string
  edited_content?: string | null
  rationale?: string | null
  status: ReviewActionStatus
  basis_analysis_ids?: string[]
  basis_source_ids?: string[]
  verification_rule?: { success_condition?: string; allow_partial?: boolean }
}

export interface ReviewActionCheck {
  id: string
  previous_action_id: string
  primary_domain?: ReviewDomainCode
  check_status: 'FULFILLED' | 'PARTIALLY_FULFILLED' | 'EXPLICITLY_NOT_FULFILLED' | 'NOT_ASSESSABLE'
  explanation: string
  evidence_source_ids: string[]
  previous_action_content?: string
  previous_action?: ReviewAction
}

export interface ReviewFeedback {
  id?: string
  analysis_item_id: string
  rating: number | null
  comment: string | null
  is_inherited?: boolean
  updated_at?: string | null
}

export interface ReviewVersion {
  id: string
  review_id: string
  version_no: number
  version_type: string
  base_version_id: string | null
  source_set_id: string | null
  event_document: ReviewEventDocument
  analysis_document: ReviewAnalysisDocument
  summary: string | null
  analysis_stale: boolean
  superseded_at_creation: boolean
  missing_periods?: unknown[]
  event_model_info?: Record<string, unknown> | null
  analysis_model_info?: Record<string, unknown> | null
  created_at: string
}

export interface ReviewVersionDetail {
  review: ReviewSummary
  version: ReviewVersion
  actions: ReviewAction[]
  action_checks: ReviewActionCheck[]
  feedback: ReviewFeedback[]
  dependencies?: unknown[]
  source_updates_available?: boolean
}

export interface ReviewDailyDigest {
  id: string
  review_task_id: string
  review_version_id: string | null
  digest_date: string
  status: 'EMPTY' | 'READY' | 'FAILED'
  material_document: ReviewDailyMaterialDocument
  created_at: string
  updated_at: string
}

export interface ReviewDailyMaterialDocument {
  digest_date?: string
  day_overview: { main_changes: string[]; overall_state: string[] }
  matters: ReviewDailyMatter[]
}

export interface ReviewDailyMatter {
  item_key: string
  title: string
  core_changes: string[]
  facts_and_progress: string[]
  emotions_and_state: string[]
  actions_and_results: Array<{ action: string; result: string }>
  concerns_and_expectations: Array<{ kind: 'ATTENTION' | 'CONCERN' | 'EXPECTATION'; text: string }>
  reflections_and_learning: string[]
  key_quotes?: unknown
  source_ids: string[]
}

export type ReviewTaskStatus =
  | 'PENDING'
  | 'PENDING_START'
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'COMPLETED'
  | 'FAILED'
  | 'SKIPPED_NO_DATA'

export interface ReviewTask {
  id: string
  review_id: string | null
  review_type?: ReviewType
  period_start?: string
  period_end?: string
  trigger_type: string
  generation_mode: 'FULL' | 'ANALYSIS_ONLY'
  base_version_id: string | null
  status: ReviewTaskStatus
  requested_start_at?: string | null
  started_by_user_id?: string | null
  current_step: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  result_version_id: string | null
}

export interface ReviewSource {
  id: string
  type?: string
  source_type?: string
  fact_kind?: string | null
  date?: string | null
  source_date?: string | null
  role?: string | null
  period_role?: string | null
  content: string
  snapshot?: Record<string, unknown> | null
  lineage?: unknown[]
  origin_review_id?: string | null
  origin_review_version_id?: string | null
  origin_content_item_key?: string | null
  origin?: { type?: string; id?: string; diary_id?: string; date?: string } | null
}
