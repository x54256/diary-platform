"""日记 Markdown 渲染工具"""

import json


def _ensure_list(value) -> list:
    """确保返回 list 类型：支持 list、JSON 字符串、None"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return []
    return []


def _render_introduction(introduction: str) -> str:
    """渲染开头引入段，为空或 None 时返回空字符串"""
    if not introduction:
        return ""
    return introduction


def _render_events(events: list) -> str:
    """渲染事件列表为 Markdown"""
    if not events or not isinstance(events, list):
        return ""
    parts = []
    for event in events:
        title = event.get("title") or "未命名事件"
        body = event.get("body") or []
        feeling = event.get("feeling") or []
        reflection = event.get("reflection") or []

        # 兼容旧数据：如果字段是字符串而非数组，包装为数组
        if isinstance(body, str):
            body = [body] if body else []
        if isinstance(feeling, str):
            feeling = [feeling] if feeling else []
        if isinstance(reflection, str):
            reflection = [reflection] if reflection else []

        part = f"## 事件：{title}\n\n" + "\n\n".join(body)
        if feeling:
            if len(feeling) == 1:
                part += f"\n\n### 感受\n{feeling[0]}"
            else:
                items = "\n".join(f"{i}. {f}" for i, f in enumerate(feeling, 1))
                part += f"\n\n### 感受\n{items}"
        if reflection:
            if len(reflection) == 1:
                part += f"\n\n### 反思与成长\n{reflection[0]}"
            else:
                items = "\n".join(f"{i}. {r}" for i, r in enumerate(reflection, 1))
                part += f"\n\n### 反思与成长\n{items}"
        parts.append(part)
    return "\n\n".join(parts)


def _render_trivia(trivia) -> str:
    """渲染琐事列表为 Markdown"""
    trivia = _ensure_list(trivia)
    if not trivia:
        return ""
    items = "\n".join(f"{i}. {t}" for i, t in enumerate(trivia, 1))
    return f"## 琐事\n\n{items}"


def _render_plans(plans) -> str:
    """渲染后续计划列表为 Markdown"""
    plans = _ensure_list(plans)
    if not plans:
        return ""
    items = "\n".join(f"{i}. {p}" for i, p in enumerate(plans, 1))
    return f"## 后续计划\n\n{items}"


def render_diary_to_markdown(
    events: list,
    introduction: str = "",
    trivia: list = None,
    plans: list = None,
) -> str:
    """将日记结构化数据渲染为 Markdown 格式字符串

    Args:
        events: 事件列表，每个事件包含 title/body/feeling/reflection
        introduction: 开头引入段文本，为空时不输出
        trivia: 琐事列表
        plans: 后续计划列表

    Returns:
        markdown 字符串
    """
    sections = [
        s for s in [
            _render_introduction(introduction),
            _render_events(events),
            _render_trivia(trivia or []),
            _render_plans(plans or []),
        ]
        if s
    ]
    return "\n\n".join(sections)
