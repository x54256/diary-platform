"""日记事件渲染工具"""


def render_events_to_markdown(events: list[dict]) -> str:
    """将事件列表渲染为 markdown 格式字符串

    Args:
        events: 事件列表，每个事件是 dict，包含
                title/background/motivation/process/result/feeling/reflection

    Returns:
        markdown 字符串；events 为空时返回空字符串
    """
    if not events:
        return ""

    sections = []
    for event in events:
        title = event.get("title") or "未命名事件"
        background = event.get("background") or "原文未明确"
        motivation = event.get("motivation") or "原文未明确"
        process = event.get("process") or "原文未明确"
        result = event.get("result") or "原文未明确"
        feeling = event.get("feeling") or "原文未明确"
        reflection = event.get("reflection") or "原文未明确"

        section = f"""## 事件：{title}

### 背景
{background}

### 动机
{motivation}

### 过程
{process}

### 结果
{result}

### 感受
{feeling}

### 反思与成长
{reflection}"""
        sections.append(section)

    return "\n\n".join(sections)
