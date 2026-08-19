export type KnowledgeTaskStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export interface KnowledgeTask {
  id: string
  diary_id: string
  status: KnowledgeTaskStatus
  current_step?: string | null
  retry_count: number
  error_code?: string | null
  error_message?: string | null
}

export interface DiaryKnowledgeStatus {
  state: 'NOT_DEPOSITED' | 'PROCESSING' | 'FAILED' | 'DEPOSITED'
  model_configured: boolean
  available: boolean
  blocked_by_other_task: boolean
  unavailable_reason?: string | null
  task?: KnowledgeTask | null
  atomic_event_count: number
}

export interface KnowledgeEvent {
  id: string
  diary_id: string
  source_diary_event_id: string
  source_event_order: number
  source_order: number
  title: string
  content: string[]
  occurred_on: string
  occurred_time?: string | null
  source_diary_date: string
  source_diary_title?: string | null
  source_event_title?: string | null
  source_diary_summary?: string | null
  created_at: string
}

export interface KnowledgeEventListResponse {
  items: KnowledgeEvent[]
  next_cursor?: string | null
}
