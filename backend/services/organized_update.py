"""结构化日记定点更新；调用方负责来源校验与事务提交。"""
import json
from datetime import datetime
from utils.diary_render import render_diary_to_markdown


def apply_organized_update(db, diary, update_data, user_id):
    from routers.diaries import parse_json_value, soft_delete_event_annotations
    organized = diary.organized
    structured_changed = False
    # 仅更新提供的字段（非 None）
    if update_data.title is not None and update_data.title != organized.title:
        structured_changed = True
        organized.title = update_data.title
    if update_data.summary is not None and update_data.summary != organized.summary:
        structured_changed = True
        organized.summary = update_data.summary
    if update_data.content is not None and update_data.content != organized.content:
        structured_changed = True
        organized.content = update_data.content
    if update_data.mood is not None and update_data.mood != organized.mood:
        structured_changed = True
        organized.mood = update_data.mood
    if update_data.location is not None and update_data.location != organized.location:
        structured_changed = True
        organized.location = update_data.location
    if update_data.introduction is not None and update_data.introduction != organized.introduction:
        structured_changed = True
        organized.introduction = update_data.introduction
    if update_data.trivia is not None:
        if parse_json_value(organized.trivia, []) != update_data.trivia:
            structured_changed = True
        organized.trivia = json.dumps(update_data.trivia, ensure_ascii=False)
    if update_data.plans is not None:
        if parse_json_value(organized.plans, []) != update_data.plans:
            structured_changed = True
        organized.plans = json.dumps(update_data.plans, ensure_ascii=False)

    # ── 事件批量更新 ──
    if update_data.events is not None:
        existing_events = {e.id: e for e in organized.events}
        for event_data in update_data.events:
            event = existing_events.get(event_data.id)
            if not event:
                continue
            changed_fields: set[str] = set()
            if event_data.event_title is not None:
                if event.event_title != event_data.event_title:
                    structured_changed = True
                event.event_title = event_data.event_title
            if event_data.body is not None:
                if parse_json_value(event.body, []) != event_data.body:
                    changed_fields.add("body")
                    structured_changed = True
                event.body = json.dumps(event_data.body, ensure_ascii=False)
            if event_data.feeling is not None:
                if parse_json_value(event.feeling, []) != event_data.feeling:
                    changed_fields.add("feeling")
                    structured_changed = True
                event.feeling = json.dumps(event_data.feeling, ensure_ascii=False)
            if event_data.reflection is not None:
                if parse_json_value(event.reflection, []) != event_data.reflection:
                    changed_fields.add("reflection")
                    structured_changed = True
                event.reflection = json.dumps(event_data.reflection, ensure_ascii=False)
            if "user_importance" in event_data.model_fields_set:
                event.user_importance = event_data.user_importance
                event.user_importance_reason = event_data.user_importance_reason
                event.importance_updated_at = datetime.utcnow()
            soft_delete_event_annotations(db, event.id, changed_fields, user_id)

    if structured_changed:
        organized.structured_revision += 1
        # 重新生成 content
        events_for_render = []
        for e in organized.events:
            events_for_render.append({
                "title": e.event_title,
                "body": json.loads(e.body) if isinstance(e.body, str) else (e.body or []),
                "feeling": json.loads(e.feeling) if isinstance(e.feeling, str) else (e.feeling or []),
                "reflection": json.loads(e.reflection) if isinstance(e.reflection, str) else (e.reflection or []),
            })
        organized.content = render_diary_to_markdown(
            events=events_for_render,
            introduction=organized.introduction or "",
            trivia=json.loads(organized.trivia) if isinstance(organized.trivia, str) else (organized.trivia or []),
            plans=json.loads(organized.plans) if isinstance(organized.plans, str) else (organized.plans or []),
        )

    if structured_changed:
        db.flush()
        from services.search_indexing import refresh_changed_event_search_indexes
        for event in organized.events:
            refresh_changed_event_search_indexes(db, event.id, include_event_content=True, include_analysis=False)
    return organized
