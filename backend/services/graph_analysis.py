"""图谱之后的来源日记分析，按事件ID校验，阶段不提交正式结果。"""

import copy

from schemas.actions import ActionSchedulePayload
from services.graph_points import require
from services.graph_runtime import GraphError

CORE_FIELDS = {"EMOTION": "emotion_analyses", "BEHAVIOR_DECISION": "behavior_decision_analyses",
               "SELF_UNDERSTANDING": "self_understanding_analyses", "ACTION_SUGGESTION": "action_suggestions"}
COGNITION_FIELDS = {"COGNITIVE_CALIBRATION": "cognitive_calibration_analyses",
                    "QUESTION_ANSWER": "question_answers", "COGNITIVE_ENHANCEMENT": "cognitive_enhancements"}
STATE_FIELDS = {"cognitive_calibration_analyses": "event_cognitive_calibration_analyses",
                "question_answers": "event_question_answers", "cognitive_enhancements": "event_cognitive_enhancements"}


def analysis_prompts():
    from services import analysis_pipeline as a
    id_rule = """\n本次接口采用稳定事件ID：每个事件结果必须返回与输入完全一致的event_id和原标题title。
事件数组完整覆盖所有输入ID，允许没有分析内容但不允许漏事件、重复ID或新增ID。
不要仅按标题定位事件。反馈rewrites使用event_id代替event_title，DIARY范围event_id为null。
此ID接口规则覆盖前述输出模板中的事件定位字段，其余分析业务规则保持一致。"""
    return {"mood_tag_extract": a.MOOD_TAG_PROMPT + id_rule,
            "core_analysis": a.CORE_ANALYSIS_PROMPT + id_rule,
            "cognition_analysis": a.COGNITION_ANALYSIS_PROMPT + id_rule,
            "action_planning": a.ACTION_PLANNING_PROMPT,
            "feedback_core_analysis": a.FEEDBACK_CORE_ANALYSIS_PROMPT + id_rule,
            "feedback_cognition_analysis": a.FEEDBACK_COGNITION_ANALYSIS_PROMPT + id_rule}


def string_items(value):
    require(isinstance(value, list) and all(isinstance(s, str) and s.strip() for s in value), "分析项必须为非空白字符串数组")


def check_items(value, field):
    if field != "question_answers": return string_items(value)
    require(isinstance(value, list), "问答必须为数组")
    for item in value:
        require(isinstance(item, dict) and set(item) == {"question", "answer"} and
            all(isinstance(item[k], str) and item[k].strip() for k in ("question", "answer")), "问答字段不合法")


def event_results(rows, events):
    require(isinstance(rows, list) and len(rows) == len(events), "分析结果未完整覆盖来源事件")
    require(all(isinstance(r, dict) for r in rows), "事件结果不是对象")
    ids = [r.get("event_id") for r in rows]
    require(len(set(ids)) == len(ids) and set(ids) == {e["event_id"] for e in events}, "事件ID遗漏、重复或未知")
    by_id = {r["event_id"]: r for r in rows}
    for event in events:
        require(by_id[event["event_id"]].get("title") == event["title"], "事件结果原标题不一致")
    return [by_id[e["event_id"]] for e in events]


def validate_analysis(data, events, fields):
    require(isinstance(data, dict) and set(data) == {"event_analyses", "diary_analysis"}, "分析顶层字段不一致")
    rows = event_results(data["event_analyses"], events)
    for row in rows:
        require(set(row) == {"event_id", "title", *fields}, "事件分析字段不一致")
        for field in fields: check_items(row[field], field)
    require(isinstance(data["diary_analysis"], dict), "日记分析不是对象")
    diary_fields = set(fields) - {"question_answers"}
    require(set(data["diary_analysis"]) == diary_fields, "日记分析字段不一致")
    for field in diary_fields: check_items(data["diary_analysis"][field], field)


def feedback_targets(context, types):
    targets = {(f["scope"], f.get("event_id"), f["analysis_type"]) for f in context if f["analysis_type"] in types}
    targets |= {("DIARY", None, kind) for scope, _, kind in targets if scope == "EVENT"}
    return targets


def validate_rewrites(data, targets, fields):
    require(isinstance(data, dict) and set(data) == {"rewrites"} and isinstance(data["rewrites"], list), "反馈结果结构不合法")
    found = set()
    for row in data["rewrites"]:
        require(isinstance(row, dict) and set(row) == {"scope", "event_id", "analysis_type", "items"}, "反馈字段不一致")
        key = (row["scope"], row["event_id"], row["analysis_type"])
        require(key in targets and key not in found, "反馈重写块重复或超出范围")
        check_items(row["items"], fields[row["analysis_type"]]); found.add(key)
    require(found == targets, "反馈重写未覆盖全部要求块")


def merge_rewrites(previous, data, cognition=False):
    result = copy.deepcopy(previous)
    for row in data["rewrites"]:
        field = (COGNITION_FIELDS if cognition else CORE_FIELDS)[row["analysis_type"]]
        if row["scope"] == "DIARY":
            if cognition: result["diary_" + ("cognitive_enhancements" if field == "cognitive_enhancements" else field)] = row["items"]
            else: result["diary_analysis"][field] = row["items"]
        else:
            rows = result[STATE_FIELDS[field]] if cognition else result["event_analyses"]
            match = next((e for e in rows if e["event_id"] == row["event_id"]), None)
            if match is None: raise GraphError("SOURCE_CHANGED", "反馈目标事件已不在冻结来源中")
            match[field] = row["items"]
    return result


async def analyze(ctx, source, state):
    from services.analysis_pipeline import _action_planning_input
    events = source["events"]
    structured = source["structured_diary"]
    metadata = state.get("analysis_metadata")
    feedback = source.get("analysis_mode") == "feedback"
    result = copy.deepcopy(state.get("analysis_result") or source.get("previous_state") or {})
    if not feedback and metadata is None:
        def validate_meta(data):
            require(isinstance(data, dict) and set(data) == {"title", "summary", "location", "mood", "event_tags"}, "元数据字段不一致")
            require(all(isinstance(data[k], str) for k in ("title", "summary", "location", "mood")), "元数据必须为文本")
            for row in event_results(data["event_tags"], events):
                require(set(row) == {"event_id", "title", "tags"} and isinstance(row["tags"], dict) and set(row["tags"]) == {"domain", "topic", "person_object", "psychological", "knowledge"}, "标签结构不一致")
                for values in row["tags"].values(): string_items(values)
        metadata = await ctx.call("mood_tag_extract", "diary", {"structured_diary": structured}, validate_meta)
        metadata["event_tags"] = event_results(metadata["event_tags"], events)
        state = ctx.save("ANALYZE_METADATA", analysis_metadata=metadata)
    if feedback:
        metadata = source["previous_metadata"]
    result.update(metadata)
    for cognition in (False, True):
        cache_key = "cognition_complete" if cognition else "core_complete"
        if state.get(cache_key):
            result = copy.deepcopy(state["analysis_result"]); continue
        fields = COGNITION_FIELDS if cognition else CORE_FIELDS
        if feedback:
            role = "feedback_cognition_analysis" if cognition else "feedback_core_analysis"
            targets = feedback_targets(source["feedback_context"], fields)
            if targets:
                previous_input = {k: v for k, v in result.items() if ("cognitive" in k or "question" in k)} if cognition else {"event_analyses": result["event_analyses"], "diary_analysis": result["diary_analysis"]}
                raw = await ctx.call(role, "diary", {"structured_diary": structured,
                    "person_relations": source["person_relations"],
                    "previous_cognition_analysis" if cognition else "previous_core_analysis": previous_input,
                    "feedback": [f for f in source["feedback_context"] if f["analysis_type"] in fields]},
                    lambda x: validate_rewrites(x, targets, fields))
                result = merge_rewrites(result, raw, cognition)
        else:
            role = "cognition_analysis" if cognition else "core_analysis"
            payload = {"structured_diary": structured, "person_relations": source["person_relations"]} if cognition else {"events": events, "person_relations": source["person_relations"]}
            raw = await ctx.call(role, "diary", payload, lambda x: validate_analysis(x, events, fields.values()))
            rows = event_results(raw["event_analyses"], events)
            if cognition:
                for field, state_field in STATE_FIELDS.items():
                    result[state_field] = [{"event_id": r["event_id"], "title": r["title"], field: r[field]} for r in rows]
                result["diary_cognitive_calibration_analyses"] = raw["diary_analysis"]["cognitive_calibration_analyses"]
                result["diary_cognitive_enhancements"] = raw["diary_analysis"]["cognitive_enhancements"]
            else:
                result.update(event_analyses=rows, diary_analysis=raw["diary_analysis"])
        state = ctx.save("ANALYZE_COGNITION" if cognition else "ANALYZE_CORE", analysis_result=result, **{cache_key: True})
    if not state.get("actions_complete"):
        payload = _action_planning_input({"structured_diary": structured, **result})
        supplied = {s["source_key"]: s["text"] for s in payload["plans"] + payload["action_suggestions"]}
        def validate_actions(data):
            require(isinstance(data, dict) and set(data) == {"action_items"} and isinstance(data["action_items"], list), "行动结果结构不合法")
            for row in data["action_items"]:
                require(isinstance(row, dict) and set(row) == {"title", "source", "schedule"}, "行动字段不一致")
                require(isinstance(row["title"], str) and 0 < len(row["title"].strip()) <= 200, "行动标题不合法")
                require(isinstance(row["source"], list) and bool(row["source"]), "行动缺少来源")
                for item in row["source"]:
                    require(isinstance(item, dict) and item.get("source_key") in supplied and isinstance(item.get("text"), str) and item["text"].strip() and item["text"] in supplied[item["source_key"]], "行动来源不属于本轮输入")
                schedule = dict(row["schedule"])
                if "month" in schedule: schedule["recurrence_month"] = schedule.pop("month")
                validated = ActionSchedulePayload.model_validate(schedule)
                require(validated.start_date.isoformat() >= structured["analysis_date"], "推荐日程早于冻结分析日期")
        raw = await ctx.call("action_planning", "diary", payload, validate_actions)
        actions = []
        for row in raw["action_items"]:
            schedule = dict(row["schedule"])
            if "month" in schedule: schedule["recurrence_month"] = schedule.pop("month")
            actions.append({"title": row["title"], "source": row["source"],
                "source_keys": list(dict.fromkeys(x["source_key"] for x in row["source"])),
                "plan_sources": [x for x in row["source"] if x["source_key"].startswith("plan:")],
                "analysis_sources": [x for x in row["source"] if x["source_key"].startswith("suggestion:")],
                "schedule": ActionSchedulePayload.model_validate(schedule).model_dump(mode="json")})
        result["action_items"] = actions
        state = ctx.save("PLAN_ACTIONS", analysis_result=result, actions_complete=True)
    return state
