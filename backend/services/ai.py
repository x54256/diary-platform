"""AI 服务模块 - DeepSeek API 封装"""

import asyncio
import json
import logging
import os
from datetime import date, datetime

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AI 交互日志配置 - 记录每次 AI 调用的请求与响应
# ---------------------------------------------------------------------------
_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_log_dir, exist_ok=True)

_ai_logger = logging.getLogger("ai_interaction")
_ai_logger.setLevel(logging.DEBUG)

_log_file = os.path.join(_log_dir, f"ai_{datetime.now().strftime('%Y-%m-%d')}.log")
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s"))
_ai_logger.addHandler(_file_handler)

# ---------------------------------------------------------------------------
# 结构化日记整理的 5 个独立 Prompt
# ---------------------------------------------------------------------------

CLEAN_PROMPT_LIGHT = """你是一个文本清洗助手。请对用户提供的日记原文（语音转文字）进行基础清洗。

## 规则
1. 修正语病、错别字、断句错误
2. 删除口头禅（嗯、啊、然后、反正、就是、那个 等）
3. 删除明显的重复表达（同一句话说了两遍只保留一遍）
4. 不改变原文含义，不调整语序，不重组内容
5. 保留原文的语气和风格

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"cleaned_text": "清洗后的文本"}"""

CLEAN_PROMPT_DEEP = """你是一个文本清洗助手。请对轻度清洗后的日记原文进行深度重组。

## 最高准则
尊重事实但不过度尊重原文。整理结果必须让人能看懂，这是给人读的。

## 规则
1. 剔除不承载信息价值的口头语言噪音（录音过程自语、叙述过渡、走神重复、无意义填充等），只要不承载事件、情感或认知信息，都应剔除
2. 事件描述围绕事件本身，用书面逻辑重新组织表达，按时间先后单向叙述，补全隐含的逻辑关系，结合上下文修正语音识别错误，确保可读性
3. 不改变事实含义，但整理力度要足够

## 清洗样例

输入：今天早上我们昨天昨天晚上下了可大可大的雨了，所以就嗯没按时出来
输出：昨天晚上下了很大的雨，没按时出来

输入：然后刚刚讲到哪了啊，今天把那个软件过程的文档基本上写完了然后明天看看我早上能不能起来
输出：今天把软件过程的文档基本上写完了，明天早上看看能不能起来

输入：下楼腿都在那抖，走起路来就好很多了
输出：下楼腿都在抖，但走起路来就好很多

输入：然后再讲一个今天早晨的事吧，今天早晨林萧鹏突然问我
输出：今天早上林萧鹏突然问我

输入：就闲着也是闲着就说两句
输出：（删除，属于元叙述）

请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"cleaned_text": "深度清洗后的文本"}"""

EVENT_ORGANIZE_PROMPT = """你是一个事件整理助手。请对用户提供的清洗后日记文本进行事件识别、归类和重组，规则如下：

## 事件拆分规则
- 按"目标"拆分为主：想解决的问题/想完成的事不同就拆成不同事件
- 时间/地点/人物/场景/主题作为辅助判断维度
- 每个事件应有明确的目标或主题

## 事件内文本重组
- 将属于同一事件的散落文本聚合到一起
- 按时间顺序整理事件内的叙述
- 保留原文表达，不改写含义

## 引入段识别
原文开头无法归入事件、琐事、后续计划的开场白或闲聊内容，提取为 introduction。
- 引入段仅整理原文已有内容，不主动生成
- 如果没有这类内容，introduction 为空字符串

## 拆分样例

输入：今天把软件过程文档写完了。东莞的项目也收尾了，没啥活了。昨天给自己找了个活去干前端DUS工作。
输出：
{
  "events": [
    {"event_title": "完成软件过程文档", "organized_text": "今天把软件过程文档基本上写完了，现在就差 Scrum 和 Kanban 两个框架和方法没写，明天早上完成收尾。"},
    {"event_title": "东莞项目收尾", "organized_text": "东莞的项目基本上做完了，任务完成了，我这边没啥活了，下周估计要跟田总要活。"},
    {"event_title": "接手前端 DUS 工作", "organized_text": "昨天给自己找了个活，去干前端的 DUS 工作。"}
  ],
  "trivia": [],
  "plans": ["下周跟田总要活"],
  "introduction": ""
}

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"event_title": "事件标题（什么时候发生/做了什么）", "organized_text": "该事件的全部相关文本重组后的结果"}], "trivia": [], "plans": [], "introduction": "引入段文本（无则空字符串）"}"""

TEMPLATE_FILL_PROMPT = """你是一个结构化整理助手。请将用户提供的每个事件的文本，按照3字段结构化模板进行填充。

## 核心红线
1. 只整理原文明确表达的内容，不推断、不补充、不拔高
2. 对模糊表达采用"保留原始表达 + 标注未明确点"，不强行解释成明确结论
3. 重复表达只保留信息最完整、表达最清楚的一版
4. 可以修正错别字、语病、断句，但不改变含义

## 3字段精确定义

### 事件正文（body）
把背景、动机、过程、结果合并成一段或多段自然语言，按阅读顺序整理。
- 背景：事件发生前已存在的上下文和外部条件（前因、时间、地点、人物、环境、外部限制）
- 动机：原文明确表达的"我为什么要做这件事"（想解决的问题、想达成的目标、目的）
- 过程：事件实际推进经过，按发生顺序整理（做了什么、对方做了什么、中间变化、沟通、协作、冲突）
- 结果：事件最后形成的状态和后续影响（是否完成、遗留问题、当前状态）
- 写成自然段，不默认使用编号；只有步骤非常清晰、且编号能明显提升可读性时才使用编号
- 即时感受可自然融入事件正文句子中，但不展开心理分析

### 感受（feeling）
对整个事件情绪变化的总结。
- 归入：主要情绪、情绪变化、情绪转折点、压力、烦躁、轻松、开心、失望、被忽视、被回应等体验
- 不归入：复述过程细节、事后经验、心理分析
- 只有原文明确表达情绪时才整理，否则为空字符串

### 反思与成长（reflection）
原文明确表达的事后理解、判断、感悟、学到的东西、自我认识。
- 有多条时使用编号列表，只有一条时直接写自然段
- 不归入：原文没说的经验、推断隐含道理、拔高、拆成内部小标题
- 只有原文明确表达了才整理，否则为空字符串

## 格式规则
1. 事件正文写成通顺完整的自然段，即时感受可自然融入句子
2. 感受字段只总结整个事件的情绪变化，不复述过程细节
3. 反思与成长不拆成内部小标题，只有原文明确表达了才整理
4. 字段无内容时填空字符串

## 整理样例

输入事件：
{"event_title": "昨天晚上和今天中午带达达遛弯", "organized_text": "达达今天拉了四回。昨天他憋了一天一晚上，晚上又下雨没出来。12点左右，我带他出来溜溜...今天中午带他出来..."}
输出：
{"title": "带达达遛弯", "body": "昨天晚上下雨没带达达出来，他憋了一天一晚上。接近 12 点我带他出来，本想在塑胶道那块溜一会儿，结果达达不愿意，非要往后门走，走到拳击那块就不走了，要过道去玩。我好不容易拽回来，走到正门又不走了，要往地铁站那边走。我还是没让他，带他走了小花园，绕了车库一圈，才生拉硬拽回家。\n\n今天中午带他出来，走到小区正门就死活要出去。我想着中午有时间，点外卖也不快，就惯着他带他出去。出来达达非要走大圈，本来走下渡路都回去了，他非要往回走，无所谓了反正明天休息，宠宠小狗。小狗老舔地上的尿，怎么吓唬都没用，大半是走水坑里了。", "feeling": "对达达又无奈又宠溺", "reflection": ""}

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"title": "事件标题", "body": "事件正文", "feeling": "感受内容", "reflection": "反思内容"}]}"""

CHECK_PROMPT = """你是一个内容审核助手。请对用户提供的结构化事件进行内容检查与修正。

## 检查规则
对照原始日记文本，检查以下8类问题。发现问题直接修正替换，只做一轮检查：

1. 编造内容：事件中出现了原文没有的内容
2. 推断动机：事件正文中包含了原文未明确表达的目的或原因
3. 推断感受：感受字段中包含了原文未明确表达的情绪
4. 推断反思/成长：反思与成长字段中包含了原文未明确表达的经验或感悟
5. 过度总结：将具体的经历过度抽象概括，丢失了原文的细节
6. 事件归类错误：不同目标的内容被放入同一事件，或同一目标被拆成多个事件
7. 字段放错位置：内容被放入了错误的字段（如把事后反思放进了事件正文，或把过程细节放进了感受）
8. 可读性不足：以读者视角通读全文，检查是否有句子读不通顺、逻辑跳跃、因果关系不清、时间混乱等影响阅读体验的问题，发现问题直接改写为通顺表达

## 修正规则
- 发现问题直接在 events 中修正对应字段
- 对每个检查项记录检查结果：通过则 status 为"通过"，发现问题并修正则 status 为"已修正"
- 只做一轮检查，不反复修正

## 输出格式
请严格按以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{"events": [{"title": "...", "body": "...", "feeling": "...", "reflection": "..."}], "check_log": [{"check_item": "编造内容", "status": "通过", "issue": "", "fix": "", "before": "", "after": ""}, {"check_item": "推断动机", "status": "已修正", "issue": "问题描述", "fix": "修正动作", "before": "修正前片段", "after": "修正后片段"}]}

check_log 必须包含全部8个检查项。通过时 issue/fix/before/after 为空字符串。"""

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

    async def _call_ai(self, system_prompt: str, user_message: str, temperature: float = 0.3) -> dict:
        """通用 AI 调用方法

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息（通常是 JSON 字符串）
            temperature: 温度参数，控制输出随机性

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

        # 记录请求日志
        _ai_logger.info(
            f"=== AI Call: {system_prompt[:50]}... ===\n"
            f"[Temperature] {temperature}\n"
            f"[System Prompt]\n{system_prompt}\n"
            f"[User Message]\n{user_message}"
        )

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
                            "temperature": temperature,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    raw_content = response.json()["choices"][0]["message"]["content"]
                    result = json.loads(raw_content)

                    # 记录响应日志
                    _ai_logger.info(
                        f"[Response]\n{json.dumps(result, ensure_ascii=False, indent=2)}\n"
                        f"{'='*60}\n"
                    )

                    return result
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
            "title", "body", "feeling", "reflection",
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
                    validated_event[field] = event.get(field) or ""
            validated.append(validated_event)
        return validated

    async def organize_diary(self, original_text: str, progress_callback=None) -> dict:
        """6次AI调用完成结构化日记整理

        Args:
            original_text: 日记原文
            progress_callback: 可选的异步进度回调函数，接收 step 字符串

        Returns:
            包含 title/summary/events/check_log/mood/location/tag_names/introduction 的 dict
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
                "introduction": "",
            }

        # Call 1: 轻度清洗
        if progress_callback:
            await progress_callback("text_cleaning")
        clean_light_result = await self._call_ai(CLEAN_PROMPT_LIGHT, original_text, temperature=0.3)
        light_cleaned_text = clean_light_result.get("cleaned_text", original_text)

        # Call 2: 深度重组
        if progress_callback:
            await progress_callback("deep_cleaning")
        clean_deep_result = await self._call_ai(
            CLEAN_PROMPT_DEEP,
            json.dumps({"cleaned_text": light_cleaned_text}, ensure_ascii=False),
            temperature=0.5,
        )
        cleaned_text = clean_deep_result.get("cleaned_text", light_cleaned_text)

        # Call 3: 事件识别+归类+重组
        if progress_callback:
            await progress_callback("event_organizing")
        event_result = await self._call_ai(
            EVENT_ORGANIZE_PROMPT,
            json.dumps({"cleaned_text": cleaned_text}, ensure_ascii=False),
            temperature=0.5,
        )
        introduction = event_result.get("introduction", "")
        if not isinstance(introduction, str):
            introduction = ""

        # Call 4: 结构化模板填充
        if progress_callback:
            await progress_callback("template_filling")
        template_result = await self._call_ai(
            TEMPLATE_FILL_PROMPT,
            json.dumps(event_result, ensure_ascii=False),
            temperature=0.5,
        )
        structured_events = self._validate_events(template_result.get("events", []))

        # Call 5: 内容检查与修正
        if progress_callback:
            await progress_callback("content_checking")
        check_input = json.dumps(
            {"events": structured_events, "original_text": original_text},
            ensure_ascii=False,
        )
        check_result = await self._call_ai(CHECK_PROMPT, check_input, temperature=0.3)
        final_events = self._validate_events(check_result.get("events", structured_events))
        check_log = check_result.get("check_log", [])

        # Call 6: 元数据生成
        if progress_callback:
            await progress_callback("metadata_generating")
        meta_input = json.dumps(
            {"events": final_events, "original_text": original_text},
            ensure_ascii=False,
        )
        meta_result = await self._call_ai(METADATA_PROMPT, meta_input, temperature=0.3)

        return {
            "title": meta_result.get("title", ""),
            "summary": meta_result.get("summary", ""),
            "events": final_events,
            "check_log": check_log,
            "mood": meta_result.get("mood", ""),
            "location": meta_result.get("location", ""),
            "tag_names": meta_result.get("tag_names", []),
            "introduction": introduction,
        }


# 全局 AI 服务实例
ai_service = AIService()
