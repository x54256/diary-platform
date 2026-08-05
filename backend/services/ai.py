"""AI 服务模块 - DeepSeek API 封装"""

import asyncio
import json
import logging
import os
from datetime import datetime

import httpx

from config import settings
from services.model_runtime import ModelRuntimeError, resolve_model_setting, resolve_thinking_payload
from services.llm_metrics import prompt_token_count, record_llm_call
from utils.log_context import Stopwatch, log_extra
from utils.llm_log import truncate_llm_log

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
# 结构化日记整理的 6 个独立 Prompt
# ---------------------------------------------------------------------------

TEXT_MARKUP_RULES = """## 重点标记规则
可见正文必须按以下规则使用两种短语级标记：
1. 普通重点用 **重点短语**。
2. 高代价风险用 <red>风险短语</red>。

加粗适用范围：核心事实、个人底线、核心结论、可复用原则、具体行动、明确结果、关键决定，以及对后续判断或行动产生直接影响的重大转折、关系互动、困难或约束。
红色适用范围：会明显影响健康、亲密关系、隐私安全、数据安全、职业路径或关键流程闭环的高代价风险；只要文本明确包含这类风险，必须使用 <red>...</red> 标记。

标记约束：
0. 当文本中出现符合上述使用范围的短语时必须标记。
1. 只标短语，不整句、不整段标记。
2. 同一句识别出多个短语时，分别标记，不允许标记整句话。
3. 同一短语既是重点又是风险时，只使用 <red>...</red>。
4. 不标记普通背景、流水经过、情绪铺垫、弱推断和空泛鼓励。
5. <red> 是自定义文本标记，不是 HTML；除 **...** 和 <red>...</red> 外，不要输出其他 Markdown 或 HTML。
"""

CLEAN_PROMPT = """你是一个日记文本清洗助手。请对用户提供的日记原文（语音转文字）进行清洗整理，生成一份可读的基准文本，供后续事件整理使用。

## 最高准则
信息保真优先，但允许重写成更加通顺的表达，输出应让人看懂，但不能是摘要。
可以整理口语、错序、断裂和重复表达，使其成为连贯文本；
但不得删除原文中的独立事实、细节、判断、感受、计划、原因、转折或犹豫。

## 清洗目标
在不改变原文事实含义的前提下，删除语音噪音，修正明显错误，整理断句和表达，使文本通顺、自然、可读。

## 规则
1. 修正语病、错别字、断句错误。
2. 删除在上下文中明确不承载语义的内容，例如连续口吃、无意义填充词（例如"嗯、啊、就是"等）。
3. 删除明显重复表达。如果重复表达承载了新的细节、语气变化、情绪变化或补充说明，必须保留，可以合并成逻辑完整、通顺的表达，但不能合并成一个概括性结论。
4. 保留承载事件、情感、判断、偏好、计划、反思的信息，不要因为表达口语化就删除。
5. 应当结合上下文修正语音识别错误：如果某个词或短语在上下文中语义不通，且存在一个读音相近的常见词能令句子通顺，则应当修正。但不能强行猜测无法确定的人名、地名、产品名、专有名词（修正后仍然不通的，保留原样）。
6. 可以在同一句或相邻短句内调整局部语序、合并断裂表达，使表达通顺。
7. 可以补充标点，以及原文关系已经明确的过渡词；不要补充原文没有明确表达的因果、目的、动机。
8. 按原文叙述顺序整理，整体时间线不要倒置。
9. 不新增原文没有的事实、原因、情绪、评价或反思。
10. 保留原文的语气和风格，不要改成过度正式、文学化或总结式表达。
11. 如果原文表达含混，只做可读性整理，不要强行解释成确定结论。

### 人物关系与人名校正
输入中的 person_relations 是用户维护的人物名称和性别资料，仅用于识别人名和人称。
1. name 是人物主名；common_names 是用户确认过的有效称呼，不得统一替换为 name。
2. 原文出现未登记的近音、错写人名时，或结合上下文能够明确判断为该人物的识别错误，才修正为切近的名字；无法明确判断时保留原文。
3. gender 为 male 或 female 时，可在指代明确且原文确有指代错误时分别修正为“他”或“她”；unknown 时不得强行改为“它”，应保留原文指代。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{"cleaned_text": "清洗后的文本"}"""

CLEAN_CHECK_PROMPT = """你是一个日记清洗审核助手。请对照原始日记文本，审核文本清洗结果是否准确，并直接修正清洗结果中的问题。

## 清洗环节职责（供审核参考）
前一步"文本清洗"的职责范围：
- 删除口头填充词和重复表达（嗯、呃、"哈喽"重复、"和和和"结巴等）
- 修正语音识别错误（人名、产品名等的合理推断修正）
- 改善断句、标点和可读性
- 保留所有承载事件、情感、认知、计划信息的实质内容
上述操作属于清洗的预期行为，审核时不应回退。

## 任务目标
双向检查 cleaned_text 的质量：
1. 防过度清洗：检查清洗是否误删、误改了有信息价值的内容。
2. 防漏修：检查 cleaned_text 中是否残留语义不通、明显是语音识别错误但未被修正的表达。
发现问题时，直接在 checked_text 中修正，输出更可靠的 checked_text。

## 最高准则
original_text 中的事实信息（事件、时间、人物、地点、行为、结果、感受、判断、偏好、计划、细节）是最高来源。
口语填充词、重复表达、语音识别乱码不属于事实信息，清洗环节删除这些是正确行为。
checked_text 应以 cleaned_text 为基础，只修正审核发现的实质问题，不重新清洗全文，不整体改写表达风格。

## 审核规则
1. 检查 cleaned_text 是否改变了原文事实含义。
2. 检查 cleaned_text 是否遗漏了有信息价值的内容，包括事件、时间、地点、人物、行为、结果、感受、判断、计划。
3. 检查 cleaned_text 是否新增了原文没有的事实、原因、情绪、评价或反思。
4. 检查 cleaned_text 是否强行猜测无法确定的人名、地名、产品名、专有名词。
5. 检查 cleaned_text 是否把原文中的含混、犹豫、矛盾表达强行改成确定结论。
6. 检查 cleaned_text 是否存在明显不通顺、断句错误、指代不清的问题。
7. 检查 cleaned_text 中是否残留语义不通的表达（如某个词在上下文中明显不合理，且存在读音相近的常见词能令句子通顺），这类属于清洗遗漏，应当修正。

## 不属于问题（不应记录到 clean_check_log）
- 清洗删除了口头填充词（嗯、呃、那个、然后就 的重复使用）
- 清洗修正了语音识别错误（如人名、产品名的合理推断修正）
- 清洗合并了重复表达（如"哈喽"重复、"和和和"结巴、同一句话反复说）
- 清洗改善了断句、标点和局部语序
- 清洗删除了不承载信息的过渡自语或走神片段

## 修正规则
1. 发现问题时，直接在 checked_text 中修正。
2. 每个实质性修正都记录到 clean_check_log。
3. 如果 cleaned_text 没有明显问题，checked_text 可以等于 cleaned_text，clean_check_log 为空数组。
4. clean_check_log 只记录影响事实、信息完整性和可读性的实质问题，不记录标点、轻微措辞这类小调整。
5. 只修正必要问题，不重新清洗全文，不做事件拆分，不做摘要，不做结构化整理。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "checked_text": "审核修正后的文本",
  "clean_check_log": [
    {
      "issue": "发现的问题",
      "before": "清洗结果中的问题片段",
      "after": "修正后的片段",
      "reason": "修正原因"
    }
  ]
}"""

EVENT_ORGANIZE_PROMPT = """你是一个日记事件整理助手。请对日记文本进行事件识别、归类和汇聚。

## 任务目标
日记中经常出现思维跳跃：说一件事时插入另一件事，之后又回到前一件事。你的任务是识别日记中提到的所有事情，并把属于同一件事的散落内容汇聚到一起。

## 整理规则
1. 先识别日记中有哪些事情。
2. 同一件事即使在原文中分散出现，也要汇聚到同一个 events 项中。
3. 不同事情不要混在同一个 events 项中。
4. 每个事件内部按实际发生顺序整理。
5. 事件标题要具体，能说明"发生了什么"，不要写成抽象主题。
6. 每个事件的 organized_text 是该事件的完整叙述，必须保留原文中属于该事件的事实、细节、判断、感受、反思、成长和后续计划。
7. 无完整事件过程，只是简单提了一下的零散内容放入 trivia，内容的前后逻辑需要通顺，不能只将原文内容复制过去。
8. plans 是从日记文本中提取的后续计划。如果该计划在事件的 organized_text 中也存在，需要保留该计划，不得因为已写入 plans 而删除、缩写或迁移正文内容。
9. 原文开头纯开场白放入 introduction；真实发生的事情不要放入 introduction。
10. 提取 introduction、trivia、plans 时，对内容做轻度可读性整理——修正残余的语音识别错误和不通顺表达，但不改变信息内容，不做深度改写。

## 拆分判据
- 以"事情"为核心：想解决的问题不同、目标不同，就是不同的事。
- 时间、地点、人物、场景、主题作为辅助判断维度。
- 同一件事即使在原文中分散出现，也要汇聚到一起。

## 整理样例

输入：
今天把软件过程文档基本上写完了，就差 Scrum 和 Kanban 两个没写。东莞的项目也收尾了，我这边没啥活了。昨天给自己找了个活，去干前端的 DUS 工作。下周估计要跟田总要活。

输出：
{
  "introduction": "",
  "events": [
    {"event_title": "完成软件过程文档", "organized_text": "今天把软件过程文档基本上写完了，就差 Scrum 和 Kanban 两个没写。"},
    {"event_title": "东莞项目收尾", "organized_text": "东莞的项目也收尾了，我这边没啥活了。"},
    {"event_title": "接手前端 DUS 工作", "organized_text": "昨天给自己找了个活，去干前端的 DUS 工作。"}
  ],
  "trivia": [],
  "plans": ["下周跟田总要活"]
}

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "introduction": "引入段文本，无则空字符串",
  "events": [
    {
      "event_title": "事件标题",
      "organized_text": "同一事件汇聚后的文本"
    }
  ],
  "trivia": [],
  "plans": []
}""" + TEXT_MARKUP_RULES

TEMPLATE_FILL_PROMPT = """你是一个结构化整理助手。请将用户提供的事件列表转换为三字段结构。

## 任务目标
对每个事件填充：
1. 事件正文 body
2. 感受 feeling
3. 反思与成长 reflection

body 是事件的完整信息源；feeling 和 reflection 是从 body 中提取的结构化信息，不是将内容从 body 中拆走。

## 核心红线
1. 不重新拆分事件。不合并不同事件。不补充原文没有的信息。
2. 推断感受时必须包含前因后果，不输出孤立的情绪词。
3. 不拔高反思。
4. 从正文提取感受、反思与成长后，必须在 body 中保留完整原意；不得为避免字段重复而删减 body。

## 字段定义

### body：事件正文
整理该事件的完整叙述，包括背景、过程、结果，以及原文中属于该事件的感受、反思、成长和后续计划。
- body 是字符串数组，每个元素是一个自然段。
- 可以调整断句，使其读起来通顺。
- 可以把事件内的内容按发生顺序组织。
- 保留原文明确表达的事实、细节、判断、感受、反思、成长和后续计划。
- 感受、反思与成长是事件完整叙述的组成部分，即使同时提取到 feeling 或 reflection，也必须在 body 中保留。
- 涉及不同时间段、不同阶段时，分成多个段落（数组元素）。
- 内容较短时也可以是单元素数组。
- 可以使用“在什么场景，发生了什么，做了什么，最终产生了什么效果”这种表述方式

### feeling：感受
整理原文明确表达或有明确文本线索支撑的感受，包含身体体感和心理情绪。
- feeling 是字符串数组，每个元素是一条自包含的短句，带上触发原因，脱离事件正文也能看懂。
- 不要把他人的状态当成"我"的感受。
- 如果没有明确表达或明确线索，填空数组 []。
- 可以使用“发生了什么，有什么感受”这种表述方式；例如：在珠江边遛狗的时候有一个小孩拿垃圾打我的狗，他爸爸在旁边却不制止和责备，感觉很愤怒觉得这个小孩没有教养。

### reflection：反思与成长
整理原文明确表达，或由原文明显判断推出的事后理解、判断、经验、教训、自我认识。
- reflection 是字符串数组，每个元素是一条独立的反思。
- 反思是提炼后的判断或认识，不是事件正文的压缩摘要。不要把事件中的观点、事实、过程重复一遍。
- 优先使用原文明确结论。
- 允许把零散判断整理成轻度概括。
- 不允许拔高成人生经验、方法论或成长感悟。
- 不允许写原文没有支撑的反思。
- 如果没有明确表达或明显判断，填空数组 []。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "events": [
    {
      "title": "事件标题",
      "body": ["段落1", "段落2"],
      "feeling": ["感受1"],
      "reflection": ["反思1", "反思2"]
    }
  ]
}"""

CHECK_PROMPT = """你是一个日记内容审核助手。请对照 original_text，审核事件整理与三字段结构化结果，并直接修正问题。

## 任务目标
检查 introduction、events、trivia、plans 是否准确、完整、归类合理、可读。
发现问题时，直接输出修正后的完整结果，并记录关键修正。

## 事实来源
original_text 是最高且唯一的事实来源。
structured_events、organized_result 是待审核结果。

## 检查规则
对照 original_text，检查以下 10 类问题。发现问题直接修正，只做一轮检查：

1. 编造内容：结果中出现了原文没有的事实、人物、时间、地点、行为、结果、评价或结论。
2. 信息遗漏：遗漏了原文中有保留价值的事件、细节、判断、感受或计划。
3. 推断动机：事件正文中包含原文没有明确表达或没有明确线索支撑的目的、原因、动机。
4. 推断感受：feeling 中包含没有原文表达或明确线索支撑的情绪、体验、主观评价。
5. 推断反思/成长：reflection 中包含没有原文表达或明确线索支撑的经验、感悟、教训、成长。
6. 过度总结：将具体经历过度抽象概括，导致原文细节、语气或个人表达丢失。
7. 事件归类错误：不同事情被放入同一事件，或同一事情被拆成多个事件；trivia/plans/introduction 归类错误也属于此类。
8. 字段放错位置：内容被放入错误字段，例如计划放入正文、过程细节放入感受、真实事件放入 introduction、完整事件放入 trivia。
9. 计划处理错误：plans 遗漏、重复、混入非计划内容。
10. 可读性不足：句子不通顺、逻辑跳跃、指代不清、时间顺序混乱，影响阅读体验。

## 修正规则
1. 发现问题直接修正对应字段。
2. 修正范围包括 introduction、events、trivia、plans。
3. 对每个检查项记录检查结果：通过则 status 为"通过"，发现问题并修正则 status 为"已修正"。
4. 只做一轮检查，不反复修正。
5. 允许 feeling/reflection 基于明确文本线索做轻度概括，但必须有原文支撑。
6. check_log 只记录影响事实、归类、字段准确性或可读性的关键修正，不记录轻微标点调整。
7. 不要重新创作，不要改变整体表达风格。
8. body 是完整信息源，feeling、reflection、plans 是派生提取结果；不得以“避免重复”为由删减 body。

""" + TEXT_MARKUP_RULES + """

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "introduction": "审核后的引入段",
  "events": [
    {
      "title": "事件标题",
      "body": ["段落1", "段落2"],
      "feeling": ["感受1"],
      "reflection": ["反思1", "反思2"]
    }
  ],
  "trivia": [],
  "plans": [],
  "check_log": [
    {
      "check_item": "检查项名称",
      "status": "通过或已修正",
      "target": "被修正的字段，例如 events[0].feeling",
      "issue": "问题描述，通过时为空字符串",
      "before": "修正前内容，通过时为空字符串",
      "after": "修正后内容，通过时为空字符串",
      "reason": "修正原因，通过时为空字符串"
    }
  ]
}

check_log 必须包含全部 10 个检查项。
通过的检查项：status 为"通过"，target/issue/before/after/reason 为空字符串。
已修正的检查项：status 为"已修正"，填写 target/issue/before/after/reason。"""

class AIService:
    """DeepSeek AI 服务封装"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=240.0)

    async def chat(self, messages: list[dict], context: str = "") -> str:
        """调用 DeepSeek 对话接口

        Args:
            messages: 对话消息列表，格式如 [{"role": "user"/"assistant", "content": "..."}]
            context: 额外上下文信息（如日记内容），将作为 system message 注入

        Returns:
            AI 回复文本
        """
        try:
            runtime_config = resolve_model_setting("chat")
        except ModelRuntimeError as exc:
            logger.warning("对话模型未配置: %s", exc)
            return str(exc)

        # 构建请求消息：先放 system message（含上下文），再追加对话历史
        api_messages = []
        if context:
            api_messages.append({"role": "system", "content": context})
        api_messages.extend(messages)
        started = Stopwatch()
        prompt_payload = json.dumps(api_messages, ensure_ascii=False)
        prompt_tokens, prompt_tokens_source = prompt_token_count(
            None, runtime_config.model_name, context, prompt_payload,
        )

        try:
            request_body = {
                "model": runtime_config.model_name,
                "messages": api_messages,
            }
            request_body.update(resolve_thinking_payload(runtime_config))
            _ai_logger.info(
                "[chat] LLM 请求（正文最多 2000 字符）: %s",
                truncate_llm_log(request_body),
                extra=log_extra(event="chat.llm.request_payload", model=runtime_config.model_name),
            )
            response = await self.client.post(
                f"{runtime_config.api_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {runtime_config.api_key}"},
                json=request_body,
            )
            response.raise_for_status()
            response_data = response.json()
            _ai_logger.info(
                "[chat] LLM 原始响应（正文最多 2000 字符）: %s",
                truncate_llm_log(response_data),
                extra=log_extra(event="chat.llm.response_payload", model=runtime_config.model_name),
            )
            prompt_tokens, prompt_tokens_source = prompt_token_count(
                response_data, runtime_config.model_name, context, prompt_payload,
            )
            duration_ms = started.elapsed_ms()
            record_llm_call(
                step_name="chat",
                model_name=runtime_config.model_name,
                prompt_tokens=prompt_tokens,
                prompt_tokens_source=prompt_tokens_source,
                duration_ms=duration_ms,
                status="success",
            )
            _ai_logger.info(
                "LLM 调用统计",
                extra=log_extra(event="llm.call.metrics", step="chat", model=runtime_config.model_name, prompt_tokens=prompt_tokens, prompt_tokens_source=prompt_tokens_source, duration_ms=duration_ms, status="success"),
            )
            return response_data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            self._record_chat_failure(runtime_config.model_name, prompt_tokens, prompt_tokens_source, started, type(e).__name__)
            logger.error("对话模型返回错误状态码: %s, 响应: %s", e.response.status_code, truncate_llm_log(e.response.text))
            return "抱歉，AI 服务暂时不可用，请稍后再试。"
        except Exception as e:
            self._record_chat_failure(runtime_config.model_name, prompt_tokens, prompt_tokens_source, started, type(e).__name__)
            logger.error("调用 DeepSeek 对话接口失败: %s", e)
            return "抱歉，AI 服务出现异常，请稍后再试。"

    @staticmethod
    def _record_chat_failure(model_name: str, prompt_tokens: int, prompt_tokens_source: str, started: Stopwatch, error_type: str) -> None:
        duration_ms = started.elapsed_ms()
        record_llm_call(
            step_name="chat",
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            prompt_tokens_source=prompt_tokens_source,
            duration_ms=duration_ms,
            status="failed",
            error_type=error_type,
        )
        _ai_logger.info(
            "LLM 调用统计",
            extra=log_extra(event="llm.call.metrics", step="chat", model=model_name, prompt_tokens=prompt_tokens, prompt_tokens_source=prompt_tokens_source, duration_ms=duration_ms, status="failed", error_type=error_type),
        )

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
        runtime_config = resolve_model_setting("organize")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 记录请求日志
        _ai_logger.info(
            f"=== AI Call: {truncate_llm_log(system_prompt, 50)} ===\n"
            f"[Temperature] {temperature}\n"
            f"[System Prompt]\n{truncate_llm_log(system_prompt)}\n"
            f"[User Message]\n{truncate_llm_log(user_message)}"
        )

        last_error = None
        for attempt in range(settings.LLM_MAX_ATTEMPTS):
            try:
                response = await self.client.post(
                    f"{runtime_config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {runtime_config.api_key}"},
                    json={
                        "model": runtime_config.model_name,
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
                    f"[Response]\n{truncate_llm_log(json.dumps(result, ensure_ascii=False, indent=2))}\n"
                    f"{'='*60}\n"
                )

                return result
            except (httpx.HTTPStatusError, json.JSONDecodeError, KeyError, Exception) as e:
                last_error = e
                logger.warning("AI 调用第 %d 次失败: %s", attempt + 1, e)
                if attempt + 1 < settings.LLM_MAX_ATTEMPTS:
                    await asyncio.sleep(2)

        raise Exception(f"AI 调用在 {settings.LLM_MAX_ATTEMPTS} 次尝试后仍失败: {last_error}")

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
                    val = event.get(field) or []
                    if not isinstance(val, list):
                        val = [val] if val else []
                    validated_event[field] = val
            validated.append(validated_event)
        return validated

    async def organize_diary(self, original_text: str, task_id: str, diary_id: str, user_id: str) -> dict:
        """6次AI调用完成结构化日记整理（委托给 LangGraph 流水线）

        Args:
            original_text: 日记原文
            task_id: 整理任务 ID（用于 checkpoint）
            diary_id: 日记 ID
            user_id: 用户 ID

        Returns:
            包含 title/summary/events/check_log/clean_check_log/location/introduction/trivia/plans 的 dict
        """
        from database import SessionLocal
        from services.person_relations import load_person_name_gender_context
        from services.pipeline import run_pipeline

        db = SessionLocal()
        try:
            person_relations = load_person_name_gender_context(db, user_id)
        finally:
            db.close()
        return await run_pipeline(original_text, task_id, diary_id, user_id, person_relations)

    async def analyze_diary(
        self,
        original_text: str,
        structured_diary: dict,
        task_id: str,
        diary_id: str,
        user_id: str,
        diary_organized_id: str,
        feedback_source_run_id: str | None = None,
    ) -> dict:
        """触发分析流水线（3 环节 + 独立检查 + 标签落库）

        Args:
            original_text: 日记原文
            structured_diary: 整理后的结构化日记
            task_id: 分析任务 ID
            diary_id: 日记 ID
            user_id: 用户 ID
            diary_organized_id: diary_organized 的 ID

        Returns:
            包含 mood/event_tags/emotion_analysis/behavior_analysis/focus_analysis/
            cognitive_calibration/actionable_suggestions/analysis_check_log 的 dict
        """
        from services.analysis_pipeline import run_analysis_pipeline
        return await run_analysis_pipeline(
            original_text,
            structured_diary,
            task_id,
            diary_id,
            user_id,
            diary_organized_id,
            feedback_source_run_id=feedback_source_run_id,
        )


# 全局 AI 服务实例
ai_service = AIService()
