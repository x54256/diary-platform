"""AI 服务模块 - DeepSeek API 封装"""

import asyncio
import json
import logging
from datetime import date

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 结构化日记整理的 5 个独立 Prompt
# ---------------------------------------------------------------------------

CLEAN_PROMPT = """你是一个文本清洗助手。请对用户提供的日记原文进行清洗，规则如下：
1. 修正语病、错别字、断句错误
2. 删除口头禅和明显重复的表达
3. 不改变原文含义
4. 保留原文的语气和风格

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"cleaned_text": "清洗后的文本"}"""

EVENT_ORGANIZE_PROMPT = """你是一个事件整理助手。请对用户提供的清洗后日记文本进行事件识别、归类和重组，规则如下：

## 事件拆分规则
- 按"目标"拆分为主：想解决的问题/想完成的事不同就拆成不同事件
- 时间/地点/人物/场景/主题作为辅助判断维度
- 每个事件应有明确的目标或主题

## 事件内文本重组
- 将属于同一事件的散落文本聚合到一起
- 按时间顺序整理事件内的叙述
- 保留原文表达，不改写含义

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"event_title": "事件标题（简洁概括）", "organized_text": "该事件的全部相关文本重组后的结果"}]}"""

TEMPLATE_FILL_PROMPT = """你是一个结构化整理助手。请将用户提供的每个事件的文本，按照6字段结构化模板进行填充。

## 核心红线
1. 结构化日记是证据层，只整理原文明确表达的内容，不推断、不补充、不拔高
2. 原文未明确的字段统一写"原文未明确"
3. 对模糊表达采用"保留原始表达 + 标注未明确点"，不强行解释成明确结论
4. 重复表达只保留信息最完整、表达最清楚的一版
5. 可以修正错别字、语病、断句，但不改变含义

## 6字段精确定义

### 背景
事件发生前已存在的上下文和外部条件。
- 归入：前因、时间、地点、人物、环境、外部限制、客观条件、已有安排
- 不归入：主观目的（放动机）、实际行动（放过程）

### 动机
原文明确表达的"我为什么要做这件事"。
- 归入：想解决的问题、想达成的目标、为什么在意、当时的考虑、期待、目的
- 不归入：外部原因（放背景）、具体行动（放过程）、原文没说不推断

### 过程
事件实际推进经过，按发生顺序整理。
- 归入：我做了什么、对方做了什么、中间变化、沟通、协作、冲突、等待、尝试
- 不归入：最终状态（放结果）、整体情绪（放感受）、事后经验（放反思与成长）

### 结果
事件最后形成的状态和后续影响。
- 归入：是否完成、是否解决、是否有反馈、后续影响、遗留问题、当前状态
- 不归入：情绪（放感受）、评价和经验总结（放反思与成长）

### 感受
对整个事件情绪变化的总结。
- 归入：主要情绪、情绪变化、情绪转折点、压力、烦躁、轻松、开心、失望、被忽视、被回应等体验
- 不归入：复述过程细节、事后经验、心理分析

### 反思与成长
原文明确表达的事后理解、判断、感悟、学到的东西、自我认识。
- 不归入：原文没说的经验、推断隐含道理、拔高、拆成内部小标题

## 格式规则
1. 过程用编号步骤展示（1. 2. 3.），每步写成通顺完整的一句话，即时感受可自然融入句子
2. 感受字段只总结整个事件的情绪变化，不复述过程细节
3. 反思与成长不拆成内部小标题，只有原文明确表达了才整理
4. 字段缺失时填"原文未明确"

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"title": "事件标题", "background": "背景内容", "motivation": "动机内容", "process": "1. 步骤一\\n2. 步骤二", "result": "结果内容", "feeling": "感受内容", "reflection": "反思内容"}]}"""

CHECK_PROMPT = """你是一个内容审核助手。请对用户提供的结构化事件进行内容检查与修正。

## 检查规则
对照原始日记文本，检查以下7类问题。发现问题直接修正替换，只做一轮检查：

1. 编造内容：事件中出现了原文没有的内容
2. 推断动机：动机字段中包含原文未明确表达的目的或原因
3. 推断感受：感受字段中包含原文未明确表达的情绪
4. 推断反思/成长：反思与成长字段中包含原文未明确表达的经验或感悟
5. 过度总结：将具体的经历过度抽象概括，丢失了原文的细节
6. 事件归类错误：不同目标的内容被放入同一事件，或同一目标被拆成多个事件
7. 字段放错位置：内容被放入了错误的字段（如把行动放进了背景）

## 修正规则
- 发现问题直接在 events 中修正对应字段
- 对每个检查项记录检查结果：通过则 status 为"通过"，发现问题并修正则 status 为"已修正"
- 只做一轮检查，不反复修正

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"title": "...", "background": "...", "motivation": "...", "process": "...", "result": "...", "feeling": "...", "reflection": "..."}], "check_log": [{"check_item": "编造内容", "status": "通过", "issue": "", "fix": "", "before": "", "after": ""}, {"check_item": "推断动机", "status": "已修正", "issue": "问题描述", "fix": "修正动作", "before": "修正前片段", "after": "修正后片段"}]}

check_log 必须包含全部7个检查项。通过时 issue/fix/before/after 为空字符串。"""

METADATA_PROMPT = """你是一个元数据提取助手。请根据用户提供的结构化事件和原始日记文本，提取日记的元数据。

## 提取规则
1. 标题：10-20字的简洁标题，概括日记核心内容
2. 摘要：一句话概括日记的主要内容
3. 心情：单个词概括当天整体心情（如"开心""焦虑""平静"），原文未提到心情时留空字符串
4. 地点：单个词概括当天所在地点，原文未提到地点时留空字符串
5. 标签：不限数量，提取日记中的关键主题词作为标签

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"title": "日记标题", "summary": "一句话摘要", "mood": "心情", "location": "地点", "tag_names": ["标签1", "标签2"]}"""


class AIService:
    """DeepSeek AI 服务封装"""

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY
        self.api_url = settings.DEEPSEEK_API_URL
        self.model = settings.DEEPSEEK_MODEL

    async def chat(self, messages: list[dict], context: str = "") -> str:
        """调用 DeepSeek 对话接口

        Args:
            messages: 对话消息列表，格式如 [{"role": "user"/"assistant", "content": "..."}]
            context: 额外上下文信息（如日记内容），将作为 system message 注入

        Returns:
            AI 回复文本
        """
        # API Key 未配置时返回友好提示
        if not self.api_key:
            return "抱歉，AI 服务尚未配置，暂时无法回复。请联系管理员设置 DEEPSEEK_API_KEY。"

        # 构建请求消息：先放 system message（含上下文），再追加对话历史
        api_messages = []
        if context:
            api_messages.append({"role": "system", "content": context})
        api_messages.extend(messages)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": api_messages,
                    },
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error("DeepSeek API 返回错误状态码: %s, 响应: %s", e.response.status_code, e.response.text)
            return "抱歉，AI 服务暂时不可用，请稍后再试。"
        except Exception as e:
            logger.error("调用 DeepSeek 对话接口失败: %s", e)
            return "抱歉，AI 服务出现异常，请稍后再试。"

    async def _call_ai(self, system_prompt: str, user_message: str) -> dict:
        """通用 AI 调用方法

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息（通常是 JSON 字符串）

        Returns:
            解析后的 JSON dict

        Raises:
            Exception: 重试1次后仍失败时抛出
        """
        if not self.api_key:
            raise Exception("AI 服务未配置 (DEEPSEEK_API_KEY)")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_error = None
        for attempt in range(2):  # 最多2次（初始+1次重试）
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{self.api_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": 0.3,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    raw_content = response.json()["choices"][0]["message"]["content"]
                    return json.loads(raw_content)
            except (httpx.HTTPStatusError, json.JSONDecodeError, KeyError, Exception) as e:
                last_error = e
                logger.warning("AI 调用第 %d 次失败: %s", attempt + 1, e)
                if attempt < 1:  # 第一次失败，等待2秒后重试
                    await asyncio.sleep(2)

        raise Exception(f"AI 调用重试1次后仍失败: {last_error}")

    def _validate_events(self, events: list) -> list:
        """验证并容错处理事件列表"""
        if not isinstance(events, list):
            return []

        required_fields = [
            "title", "background", "motivation",
            "process", "result", "feeling", "reflection",
        ]
        validated = []
        for event in events:
            if not isinstance(event, dict):
                continue
            validated_event = {}
            for field in required_fields:
                if field == "title":
                    validated_event[field] = event.get(field) or "未命名事件"
                else:
                    validated_event[field] = event.get(field) or "原文未明确"
            validated.append(validated_event)
        return validated

    async def organize_diary(self, original_text: str, progress_callback=None) -> dict:
        """5次AI调用完成结构化日记整理

        Args:
            original_text: 日记原文
            progress_callback: 可选的异步进度回调函数，接收 step 字符串

        Returns:
            包含 title/summary/events/check_log/mood/location/tag_names 的 dict
        """
        # API Key 未配置时返回占位结果
        if not self.api_key:
            today = date.today().isoformat()
            return {
                "title": f"日记 - {today}",
                "summary": "",
                "events": [],
                "check_log": [],
                "mood": "",
                "location": "",
                "tag_names": [],
            }

        # Call 1: 文本清洗
        if progress_callback:
            await progress_callback("text_cleaning")
        clean_result = await self._call_ai(CLEAN_PROMPT, original_text)
        cleaned_text = clean_result.get("cleaned_text", original_text)

        # Call 2: 事件识别+归类+重组
        if progress_callback:
            await progress_callback("event_organizing")
        event_result = await self._call_ai(
            EVENT_ORGANIZE_PROMPT,
            json.dumps({"cleaned_text": cleaned_text}, ensure_ascii=False),
        )

        # Call 3: 结构化模板填充
        if progress_callback:
            await progress_callback("template_filling")
        template_result = await self._call_ai(
            TEMPLATE_FILL_PROMPT,
            json.dumps(event_result, ensure_ascii=False),
        )
        structured_events = self._validate_events(template_result.get("events", []))

        # Call 4: 内容检查与修正
        if progress_callback:
            await progress_callback("content_checking")
        check_input = json.dumps(
            {"events": structured_events, "original_text": original_text},
            ensure_ascii=False,
        )
        check_result = await self._call_ai(CHECK_PROMPT, check_input)
        final_events = self._validate_events(check_result.get("events", structured_events))
        check_log = check_result.get("check_log", [])

        # Call 5: 元数据生成
        if progress_callback:
            await progress_callback("metadata_generating")
        meta_input = json.dumps(
            {"events": final_events, "original_text": original_text},
            ensure_ascii=False,
        )
        meta_result = await self._call_ai(METADATA_PROMPT, meta_input)

        return {
            "title": meta_result.get("title", ""),
            "summary": meta_result.get("summary", ""),
            "events": final_events,
            "check_log": check_log,
            "mood": meta_result.get("mood", ""),
            "location": meta_result.get("location", ""),
            "tag_names": meta_result.get("tag_names", []),
        }


# 全局 AI 服务实例
ai_service = AIService()
