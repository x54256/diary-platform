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
}

// 日记状态：草稿 → 已发布 → 已整理
export type DiaryStatus = 'draft' | 'published' | 'organized'

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

// 标签
export interface Tag {
  id: string
  name: string
  created_at?: string
}

// 日历项
export interface DiaryCalendarItem {
  diary_date: string
  mood: string | null
  status: string
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
