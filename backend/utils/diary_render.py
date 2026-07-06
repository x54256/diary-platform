"""日记 Markdown 渲染工具"""


def _render_introduction(introduction: str) -> str:
    """渲染开头引入段，为空时返回空字符串"""
    return introduction if introduction else ""


def _render_events(events: list) -> str:
    """渲染事件列表为 Markdown"""
    parts = []
    for event in events:
        title = event.get("title") or "未命名事件"
        body = event.get("body") or ""
        feeling = event.get("feeling") or ""
        reflection = event.get("reflection") or ""

        part = f"## 事件：{title}\n\n{body}"
        if feeling:
            part += f"\n\n### 感受\n{feeling}"
        if reflection:
            part += f"\n\n### 反思与成长\n{reflection}"
        parts.append(part)
    return "\n\n".join(parts)


def _render_trivia(trivia: list) -> str:
    """渲染琐事列表为 Markdown"""
    if not trivia:
        return ""
    items = "\n".join(f"{i}. {t}" for i, t in enumerate(trivia, 1))
    return f"## 琐事\n\n{items}"


def _render_plans(plans: list) -> str:
    """渲染后续计划列表为 Markdown"""
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


def render_events_to_markdown(events):
    """旧接口兼容，不推荐新代码使用"""
    adapted = []
    for e in events:
        if "body" not in e and "background" in e:
            parts = [
                e.get("background", ""),
                e.get("motivation", ""),
                e.get("process", ""),
                e.get("result", ""),
            ]
            body = "\n\n".join(p for p in parts if p and p != "原文未明确")
            adapted.append({
                "title": e.get("title", ""),
                "body": body,
                "feeling": e.get("feeling", ""),
                "reflection": e.get("reflection", ""),
            })
        else:
            adapted.append(e)
    return render_diary_to_markdown(adapted)
