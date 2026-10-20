export interface GraphPoint { id: string; no: number; summary: string; detail: string }
export interface GraphEvent {
  event_id: string; run_id: string; diary_id: string; title: string
  diary_date: string; occurred_on: string | null; points: GraphPoint[]
}
export interface GraphRelation {
  id: string; source_event_id: string; target_event_id: string
  relation_type: '后续事件' | '引发事件' | '提及事件'
  certainty: 'EXPLICIT' | 'SPECULATIVE'; description: string
  source_points: { point_id: string; no: number }[]
  target_points: { point_id: string; no: number }[]
}
export interface DiaryGraphResult {
  diary_id: string; run: { id: string; status: string } | null
  events: GraphEvent[]; relations: GraphRelation[]
}
