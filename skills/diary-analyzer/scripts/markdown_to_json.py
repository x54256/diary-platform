#!/usr/bin/env python3
"""将可阅读的日记分析 Markdown 转为绑定来源的 JSON，仅使用标准库。"""

import argparse
import hashlib
import json
import re
from datetime import date, time
from pathlib import Path
from uuid import UUID


class AnalysisInputError(ValueError):
    """可直接向用户展示、不含驱动参数的校验信息。"""


FIELDS = {
    "情绪分析": "emotion_analyses", "行为与决策分析": "behavior_decision_analyses",
    "关注点与需求": "self_understanding_analyses", "可行动建议": "action_suggestions",
    "认知校准": "cognitive_calibration_analyses", "问题解答": "question_answers",
    "认知完善": "cognitive_enhancements",
}
CORE = list(FIELDS.values())[:4]
DIARY_FIELDS = [v for v in FIELDS.values() if v != "question_answers"]
SCHEDULE_FIELDS = {
    "全天": "is_all_day", "开始日期": "start_date", "开始时间": "start_time",
    "结束时间": "end_time", "重复": "recurrence_type", "间隔": "interval",
    "星期": "weekdays", "月份": "recurrence_month", "月内日期": "month_day",
    "第几个星期": "nth_week", "星期几": "nth_weekday", "截止日期": "recurrence_until",
    "次数": "recurrence_count",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_export(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "source", "structured_diary", "person_relations", "export_sha256"
    } or data["schema_version"] != 1:
        raise AnalysisInputError("来源导出格式不合法")
    if digest({k: v for k, v in data.items() if k != "export_sha256"}) != data["export_sha256"]:
        raise AnalysisInputError("来源导出已修改，请重新导出并核对稿件")
    UUID(data["source"]["diary_id"])
    UUID(data["source"]["user_id"])
    structured = data["structured_diary"]
    date.fromisoformat(structured["diary_date"])
    date.fromisoformat(structured["analysis_date"])
    if structured["timezone"] != "Asia/Shanghai":
        raise AnalysisInputError("本项目时区须为 Asia/Shanghai")
    events = structured["events"]
    if not isinstance(events, list) or len({e["event_id"] for e in events}) != len(events):
        raise AnalysisInputError("来源事件 ID 重复或格式错误")
    for event in events:
        UUID(event["event_id"])
    return data


def list_items(lines):
    items = []
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items:
            items[-1] += "\n" + line[2:].rstrip()
        else:
            raise AnalysisInputError("分析栏目须用 - 列表，续行缩进两个空格；留空栏目不填内容")
    if any(not x.strip() for x in items):
        raise AnalysisInputError("分析条目不能为空")
    return items


def source_catalog(result, structured):
    """可读别名对应项目行动来源键；内容变更时重新计算，不接受模型编造键。"""
    rows = []
    for index, text in enumerate(structured["plans"]):
        if text.strip():
            rows.append({"alias": f"P{index + 1}", "source_key":
                         f"plan:{index}:{hashlib.sha256(text.encode()).hexdigest()[:12]}", "text": text})
    for index, event in enumerate(result["event_analyses"]):
        for pos, text in enumerate(event["action_suggestions"]):
            rows.append({"alias": f"E{index + 1}-S{pos + 1}", "event_id": event["event_id"],
                         "source_key": f"suggestion:event:{index}:{hashlib.sha256(text.encode()).hexdigest()[:12]}",
                         "text": text})
    for pos, text in enumerate(result["diary_analysis"]["action_suggestions"]):
        rows.append({"alias": f"D-S{pos + 1}", "source_key":
                     f"suggestion:diary:{hashlib.sha256(text.encode()).hexdigest()[:12]}", "text": text})
    return rows


def parse_schedule(values, analysis_date):
    required = {"全天", "开始日期", "重复"}
    if not required <= values.keys() or not values.keys() <= SCHEDULE_FIELDS.keys():
        raise AnalysisInputError("日程缺少全天、开始日期、重复字段，或存在未知字段")
    if values["全天"] not in {"是", "否"}:
        raise AnalysisInputError("全天须为是或否")
    schedule = dict(is_all_day=values["全天"] == "是", start_date=values["开始日期"],
                    start_time=None, end_time=None, recurrence_type=values["重复"], interval=1,
                    weekdays=[], recurrence_month=None, month_day=None, nth_week=None,
                    nth_weekday=None, recurrence_until=None, recurrence_count=None)
    integer_fields = {"间隔", "月份", "月内日期", "第几个星期", "星期几", "次数"}
    for label, value in values.items():
        key = SCHEDULE_FIELDS[label]
        if label == "全天":
            continue
        if label in integer_fields:
            schedule[key] = int(value) if value else None
        elif label == "星期":
            schedule[key] = [int(x.strip()) for x in value.split(",")] if value else []
        else:
            schedule[key] = value or None
    start = date.fromisoformat(schedule["start_date"])
    if start < date.fromisoformat(analysis_date):
        raise AnalysisInputError("推荐日期早于冻结分析日期")
    if schedule["is_all_day"]:
        if schedule["start_time"] or schedule["end_time"]:
            raise AnalysisInputError("全天日程不得填写时间")
    else:
        for key in ("start_time", "end_time"):
            if not re.fullmatch(r"\d{2}:\d{2}", schedule[key] or ""):
                raise AnalysisInputError("定时日程须填写 HH:MM 开始、结束时间")
            time.fromisoformat(schedule[key])
        if schedule["end_time"] <= schedule["start_time"]:
            raise AnalysisInputError("结束时间须晚于开始时间，不支持跨日")
        for key in ("start_time", "end_time"):
            schedule[key] = time.fromisoformat(schedule[key]).isoformat()
    kind = schedule["recurrence_type"]
    if kind not in {"NONE", "DAILY", "WEEKLY", "MONTHLY_DATE", "MONTHLY_NTH_WEEKDAY", "YEARLY", "WORKDAY", "REST_DAY"}:
        raise AnalysisInputError("重复类型不合法")
    if not schedule["interval"] or schedule["interval"] < 1:
        raise AnalysisInputError("间隔须为正整数")
    until, count = schedule["recurrence_until"], schedule["recurrence_count"]
    if count is not None and count < 1:
        raise AnalysisInputError("次数须为正整数")
    if until and (date.fromisoformat(until) < start or count is not None):
        raise AnalysisInputError("截止日期须不早于开始日期，且与次数二选一")
    if kind == "NONE" and (until or count is not None or schedule["interval"] != 1):
        raise AnalysisInputError("不重复日程不得设置循环期限或非 1 间隔")
    active = {"WEEKLY": {"weekdays"}, "MONTHLY_DATE": {"month_day"},
              "MONTHLY_NTH_WEEKDAY": {"nth_week", "nth_weekday"},
              "YEARLY": {"recurrence_month", "month_day"}}.get(kind, set())
    for key in {"weekdays", "month_day", "recurrence_month", "nth_week", "nth_weekday"} - active:
        if schedule[key] not in (None, []):
            raise AnalysisInputError("填写了不适用于当前重复类型的定位字段")
    if kind == "WEEKLY" and (not schedule["weekdays"] or
            len(set(schedule["weekdays"])) != len(schedule["weekdays"]) or
            any(x not in range(7) for x in schedule["weekdays"])):
        raise AnalysisInputError("星期须为不重复的 0–6 数组，0 代表周日")
    if kind in {"MONTHLY_DATE", "YEARLY"} and schedule["month_day"] not in range(1, 32):
        raise AnalysisInputError("月内日期须为 1–31")
    if kind == "YEARLY":
        if schedule["recurrence_month"] not in range(1, 13):
            raise AnalysisInputError("月份须为 1–12")
        date(2000, schedule["recurrence_month"], schedule["month_day"])
    if kind == "MONTHLY_NTH_WEEKDAY" and (
            schedule["nth_week"] not in range(1, 6) or schedule["nth_weekday"] not in range(7)):
        raise AnalysisInputError("每月第几个星期几规则不完整")
    return schedule


def parse_actions(lines, catalog, analysis_date):
    actions, current = [], None
    by_alias = {row["alias"]: row for row in catalog}
    def finish():
        if current is None:
            return
        title, body = current
        if not title or len(title) > 200 or any(a["title"] == title for a in actions):
            raise AnalysisInputError("行动标题为空、超过 200 字或重复")
        values, sources, aliases = {}, [], set()
        for line in body:
            if not line.strip():
                continue
            match = re.fullmatch(r"- ([^：]+)：(.*)", line)
            if not match:
                raise AnalysisInputError("行动字段须使用 - 字段：值 格式")
            label, value = match[1], match[2].strip()
            if label == "来源":
                alias, separator, excerpt = value.partition(" | ")
                if not separator or alias not in by_alias or alias in aliases:
                    raise AnalysisInputError("行动来源别名未知、重复或缺少摘录")
                original = by_alias[alias]
                if not excerpt.strip() or excerpt not in original["text"]:
                    raise AnalysisInputError("行动来源摘录须为原计划或建议的连续片段")
                sources.append({"source_key": original["source_key"], "text": excerpt})
                aliases.add(alias)
            else:
                if label in values:
                    raise AnalysisInputError("行动日程字段重复")
                values[label] = value
        if not sources:
            raise AnalysisInputError("行动须有至少一个合法来源")
        actions.append({"title": title, "source": sources,
                        "source_keys": list(dict.fromkeys(s["source_key"] for s in sources)),
                        "schedule": parse_schedule(values, analysis_date)})
    for line in lines:
        if line.startswith("### 行动："):
            finish()
            current = (line.removeprefix("### 行动：").strip(), [])
        elif current is not None:
            current[1].append(line)
        elif line.strip():
            raise AnalysisInputError("行动规划中只能出现 ### 行动：标题；无行动时留空")
    finish()
    return actions


def parse_markdown(markdown, exported, *, sources_only=False):
    events, diary, action_lines = [], None, []
    target, section, buffer, question = None, None, [], None
    seen, actions_started = set(), False

    def flush():
        nonlocal buffer, question
        if section == "question_answers":
            answer = "\n\n".join(p.strip() for p in "\n".join(buffer).split("\n\n") if p.strip())
            if question is not None:
                if not answer:
                    raise AnalysisInputError("问题缺少回答")
                target[section].append({"question": question, "answer": answer})
            elif answer:
                raise AnalysisInputError("问题解答须使用 #### 问题：具体问题")
        elif section:
            target[section] = list_items(buffer)
        elif any(x.strip() for x in buffer):
            raise AnalysisInputError("存在未归属到栏目的文本")
        buffer, question = [], None

    def finish_target():
        if target is None:
            return
        expected = set(DIARY_FIELDS if target is diary else FIELDS.values())
        if seen != expected:
            raise AnalysisInputError("事件或日记级分析缺少栏目；无内容时仍须保留栏目标题")
        if target is not diary and "event_id" not in target:
            raise AnalysisInputError("事件缺少事件 ID")

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if actions_started:
            action_lines.append(line)
            continue
        if line.startswith("## "):
            flush()
            finish_target()
            section, seen = None, set()
            if line.startswith("## 事件：") and diary is None:
                target = {"title": line.removeprefix("## 事件：").strip()}
                events.append(target)
            elif line == "## 日记级分析" and diary is None:
                diary = target = {}
            elif line == "## 行动规划" and diary is not None:
                actions_started, target = True, None
            else:
                raise AnalysisInputError("未知、重复或顺序错误的顶层标题")
        elif line.startswith("事件 ID：") and target is not None and target is not diary and section is None:
            if "event_id" in target:
                raise AnalysisInputError("事件 ID 重复")
            target["event_id"] = str(UUID(line.removeprefix("事件 ID：").strip()))
        elif line.startswith("### "):
            flush()
            label = line[4:]
            if target is None or label not in FIELDS or FIELDS[label] in seen:
                raise AnalysisInputError("未知、重复或无所属事件的分析栏目")
            section = FIELDS[label]
            if target is diary and section == "question_answers":
                raise AnalysisInputError("日记级不设问题解答栏目")
            target[section] = []
            seen.add(section)
        elif line.startswith("#### 问题：") and section == "question_answers":
            flush()
            question = line.removeprefix("#### 问题：").strip()
            if not question:
                raise AnalysisInputError("问题不能为空")
        elif line.startswith("#") or line.startswith("```"):
            raise AnalysisInputError("出现未知标题或代码围栏")
        else:
            buffer.append(line)
    flush()
    finish_target()
    if diary is None or not actions_started:
        raise AnalysisInputError("须包含日记级分析与行动规划栏目")
    source_events = exported["structured_diary"]["events"]
    by_id = {e.get("event_id"): e for e in events}
    if len(by_id) != len(events) or set(by_id) != {e["event_id"] for e in source_events}:
        raise AnalysisInputError("事件 ID 遗漏、重复或不属于来源")
    ordered = []
    for event in source_events:
        row = by_id[event["event_id"]]
        if row["title"] != event["title"]:
            raise AnalysisInputError("事件标题与来源不一致")
        ordered.append(row)
    result = {"event_analyses": ordered, "diary_analysis": diary}
    catalog = source_catalog(result, exported["structured_diary"])
    if sources_only:
        return catalog
    result["action_items"] = parse_actions(action_lines, catalog, exported["structured_diary"]["analysis_date"])
    return result


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sources-only", action="store_true", help="只生成行动来源别名清单，暂不解析行动规划正文")
    args = parser.parse_args()
    try:
        result = parse_markdown(args.markdown.read_text(encoding="utf-8"), read_export(args.source),
                                sources_only=args.sources_only)
        write_json(args.output, result)
        print(f"已生成：{args.output.resolve()}")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"转换停止：{exc}\n")


if __name__ == "__main__":
    main()
