export type KnowledgeTaskStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export interface KnowledgeTask {
  id: string
  diary_id: string
  task_type: 'DEPOSIT' | 'UPGRADE'
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
  matter?: KnowledgeMatterRef | null
  created_at: string
}

export type KnowledgeMatterStatus = 'ONGOING' | 'ENDED' | 'PAUSED'

export interface KnowledgeMatterRef {
  id: string
  name: string
}

export interface KnowledgeMatter {
  id: string
  name: string
  status: KnowledgeMatterStatus
  overview: string
  started_on: string
  last_event_on: string
  event_count: number
  created_at: string
}

export interface KnowledgeMatterListItem {
  id: string
  name: string
  status: KnowledgeMatterStatus
  overview: string
  event_count: number
  last_event_on: string
}

export interface KnowledgeMatterListResponse {
  items: KnowledgeMatterListItem[]
  next_cursor?: string | null
}

export interface KnowledgeMatterEventItem {
  id: string
  title: string
  occurred_on: string
  occurred_time?: string | null
  first_paragraph: string
}

export interface KnowledgeMatterDetail extends KnowledgeMatter {
  events: KnowledgeMatterEventItem[]
}

export interface KnowledgeEventListResponse {
  items: KnowledgeEvent[]
  next_cursor?: string | null
}

export interface KnowledgeUpgradePendingDiary {
  diary_id: string
  diary_date: string
  diary_title?: string | null
}

export interface KnowledgeUpgradeStatusResponse {
  pending_diaries: KnowledgeUpgradePendingDiary[]
  active_task?: KnowledgeTask | null
}
