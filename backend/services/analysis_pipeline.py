"""LangGraph 分析流水线 - 3 环节串行 + 标签落库"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from database import SessionLocal
from models.diary import AnalysisRun, Diary, DiaryEvent, DiaryStatus, OrganizeTask
from models.tag import EventTag, Tag, diary_tags
from services.analysis_history import (
    COGNITION_ANALYSIS_TYPES,
    CORE_ANALYSIS_TYPES,
    create_analysis_run_from_state,
    effective_feedback,
    feedback_keys_for_run,
    feedback_to_context,
    run_to_state,
    section_key,
)
from services.pipeline import (
    _get_llm,
    _invoke_llm,
    _update_step,
    get_checkpointer,
    cleanup_checkpoint,
    run_graph_with_checkpoint,
)
from services.person_relations import load_person_relation_context
from utils.log_context import Stopwatch, log_extra

logger = logging.getLogger(__name__)

# AI 交互日志（复用 pipeline.py 的双写模式）
_ai_logger = logging.getLogger("ai_pipeline")


# ---------------------------------------------------------------------------
# Analysis Pipeline State
# ---------------------------------------------------------------------------

class AnalysisState(TypedDict, total=False):
    # ── 输入字段 ──
    original_text: str
    structured_diary: dict
    task_id: str
    diary_id: str
    diary_organized_id: str
    user_id: str
    person_relations: list[dict]

    # ── 环节 7 产物：心情 + 标签提取 ──
    mood: str
    event_tags: list

    # ── 环节 8 产物：核心分析 + 可行动建议 ──
    event_analyses: list
    diary_analysis: dict

    # ── 环节 9 产物：认知校准 + 问题解答 + 认知完善 ──
    event_cognitive_calibration_analyses: list
    diary_cognitive_calibration_analyses: list
    event_question_answers: list
    event_cognitive_enhancements: list
    diary_cognitive_enhancements: list

    # ── 进度追踪 ──
    current_step: str


class FeedbackAnalysisState(TypedDict, total=False):
    structured_diary: dict
    person_relations: list[dict]
    task_id: str
    diary_id: str
    user_id: str
    diary_organized_id: str
    previous_run_id: str
    previous_state: dict
    feedback_context: list
    merged_core: dict
    merged: dict
    current_step: str


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PERSON_RELATION_RULES = """## 人物关系参考
输入参数 person_relations 为分析时理解人物身份、人物与用户的关系以及指代的参考，无法确认 events 中的称呼对应哪条人物资料时，保留原文含义，不强行匹配。
"""

TEXT_MARKUP_RULES = """## 重点标记规则
可见正文允许使用两种短语级标记：
1. 普通重点用 **重点短语**。
2. 高代价风险用 <red>风险短语</red>。

加粗适用范围：核心事实、个人底线、核心结论、可复用原则、具体行动。
红色适用范围：会明显影响健康、亲密关系、隐私安全、数据安全、职业路径或关键流程闭环的高代价风险。

标记约束：
1. 只标短语，不整句、不整段标记。
2. 同一句包含外部要求和个人底线时，分别标记两个短语。
3. 同一短语既是重点又是风险时，只使用 <red>...</red>。
4. 不标记普通背景、流水经过、情绪铺垫、弱推断和空泛鼓励。
5. <red> 是自定义文本标记，不是 HTML；除 **...** 和 <red>...</red> 外，不要输出其他 Markdown 或 HTML。
"""

MOOD_TAG_PROMPT = """你是一个日记心情与标签提取助手。请根据结构化日记和原始文本，提取当天整体心情和事件级标签。

## 任务目标
1. 提取当天整体心情 mood。
2. 为每个事件提取事件级标签 event_tags，按五类分组。

## 输入说明
structured_diary 是整理后的结构化日记，是主要依据。

## 心情提取规则
1. 心情用一个短词表示当天整体情绪或状态，例如"疲惫""平静""烦躁""开心""低落""充实""焦虑""放松"。
2. 必须有 structured_diary 中的明确线索支撑。没有明确线索则填空字符串。

## 标签提取规则
2. 标签类型固定为五类：domain、topic、person_object、psychological、knowledge。
4. event_tags 必须与 structured_diary.events 一一对应，title 使用事件 title。
6. 每种标签类型都输出数组；没有对应标签时输出空数组。同一事件、同一类型下可以有多个标签，但不要重复。
7. 优先提取 topic、person_object、psychological、knowledge；domain 只作为辅助粗分类，数量要少。
8. 标签必须来自 structured_diary 中的明确依据。

## 标签类型说明
- domain：领域标签，用于粗粒度筛选日记，例如"工作""生活""关系""健康""学习""娱乐"。
- topic：主题标签，用于串起长期反复出现的具体事项，例如"日记管理""AI 开发""小红书爬虫""遛狗"。
- person_object：人物标签，用于串起具体人物、关系和重要对象，例如"殷萧鹏""田总""媳妇""达达"。
- psychological：心理主题标签，用于串起情绪、需求和内在模式，例如"不确定性""控制感""遗憾""无奈""成就感"。
- knowledge：知识点标签，用于串起学习内容、方法、概念和做事方式，例如"软件工程""需求分析""原型设计""AI 辅助开发""项目管理"。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "mood": "心情，没有则空字符串",
  "event_tags": [
    {
      "title": "事件标题",
      "tags": {
        "domain": [],
        "topic": [],
        "person_object": [],
        "psychological": [],
        "knowledge": []
      }
    }
  ]
}"""

CORE_ANALYSIS_RULES = PERSON_RELATION_RULES + "\n" + """
你是日记复盘分析助手，所有分析仅以传入的events日记事件列表为唯一事实依据，严格遵循统一规范输出JSON结构，客观有据、解读落地。

## 全局统一硬性约束（全模块通用）
1. 一一对应规则：事件级结果与events顺序匹配，event_analyses 第 N 项对应 events 第 N 项，title直接复用事件原标题，禁止改写；事件级分析仅针对单条事件，不跨事件推理；日记级分析综合全部事件总结。
2. 推断规范：允许有限的推断，推断必须必须能在当前事件中找到事实依据；无对应线索则对应字段返回空，禁止编造内容硬凑分析；如果依据不足，只保留有明确依据的部分，不强行补深层解释。
3. 输出格式：所有分析、建议均为数组，严格输出标准JSON，除重点标记规则允许的 **...** 和 <red>...</red> 外，不要输出其他 markdown、HTML 或额外注释；每条分析为一段完整连贯文本，像是正常对话一样，避免过度结构化。数组天然表示顺序，数组项内部禁止再写“1.”、“第一”、“首先”等编号或排序前缀。
4. 通用禁止项：不做人格/长期心理结构诊断、不强行要求改造他人/不可控客观条件、不输出鸡汤空话、不给出辞职/分手等重大高成本决策类建议，仅低成本、可落地调整方案。
5. 输出内容人称要求：分析内容是写给用户本人看的，不要使用“用户……”这类第三人称表述，优先使用“你……”或直接使用无主语的分析句式。

## 证据与留空优先级（优先于下方所有模块目标）
1. 证据强度从高到低依次为：事件明确陈述的事实；用户明确表达的感受、判断、目标和反思；由同一事件多条事实共同支持的有限推断。只允许使用这三类内容。
2. 输出前逐条检查：如果无法指出当前事件中的具体依据，删除该条。宁可返回空数组，也不要为了覆盖模块、显得深入或提供建议而硬凑内容。
3. 分析事件 N 时只允许使用事件 N 的内容。其他事件只能用于 diary_analysis，不能用来补充、解释或推断事件 N。

## 核心目标
情绪分析、行为与决策分析、关注点与需求这三个模块从不同角度帮助用户理解当前事件。只评价事件中有充分依据的部分：做得合适的可以给予正面反馈；存在明确问题的，给出建设性反馈。
分析包括两部分内容：
1. 帮助用户了解自己；
2. 给出有可执行的反馈意见。
不是每个事件、每个模块都需要结论或建议；准确留空本身就是合格结果。

## 四大模块统一要求
### 1. 情绪分析（event_analyses[].emotion_analyses / diary_analysis.emotion_analyses）
核心目标：当事件中存在明确表达或由当前事件可靠支持的情绪时，帮助用户理清情绪来源，情绪背后的深层原因，给出当下化解和长期预防方法
1. 触发情绪的原文事实；
2. 情绪背后冲突/深层需求根因（重点）；
3. 分类型给出对应方案（重点）：
- 正面情绪：说明产生条件+如何复刻创造更多同类情绪
- 负面情绪：当下临时化解手段（例如转化为具体行动）+长期规避同类触发的调整方式
- 方案应尽量展开成对使用者有直接参考价值的完整表达。

事件级输出规则：
- 只有在事件中存在明确情绪线索时，才输出事件级情绪分析。如果事件主要是在记录事务经过，没有明确情绪、情绪判断或可可靠推断的情绪反应，则返回空数组。
- 同一事件里存在两个彼此独立、无法自然合并的情绪主线时，才允许输出多条。
- 如果只是同一主线的不同情绪层次，应合并成一条完整分析。
- 对需要调整的负面情绪，应说明当下如何化解、以后如何减少、为什么这种方式更有效。
- 对应方案应尽量具体到动作、顺序或调整方向，不要只写抽象结论。
- 涉及他人、动物、系统、流程时，要说明情绪冲突是否来自用户期待与对方想法或现实规律之间的不一致。

日记级汇总：按正面/负面情绪三类分类总结当日整体情绪状态，并给出有价值的反馈。

### 2. 行为与决策分析（event_analyses[].behavior_decision_analyses / diary_analysis.behavior_decision_analyses）
核心目标：分析用户的对事情的处理方式，评估处理方式有效性和潜在风险（重点），并提供反馈意见（重点）；
1. 你当时是怎么处理这件事的。
2. 说明这种处理方式为什么有效或无效；只有当前行为确实可能重复且风险有依据时，才说明继续下去的风险。
3. 合理行为说明哪些方面值得保持；存在明确问题时才说明如何改、为什么更合适，以及可以先做的低成本行动。

事件级输出规则：
- 只有在事件中有明显的处理动作、应对方式或决策行为时才输出行为与决策分析，否则返回空数组，不硬做行为分析。
- 在同一事件里同时存在多个明显不同的处理动作、决策分支或行为问题，且放在一条里会混乱时，才允许输出多条。

日记级汇总：总结当日统一行为模式，区分有效、无效行为共性问题，给出合理的整体调整方向，以及用户接下来最值得先开始的具体行为。
- 如果写改进方向，不要只写“加强行动力”“改进情绪管理”这类抽象结论，应尽量说明先改哪一类行为、为什么先改它、第一步怎么做。

### 3. 关注点与需求（event_analyses[].self_understanding_analyses / diary_analysis.self_understanding_analyses）
核心目标：识别事件中明确表现出的关注对象、目标、期待、边界或外部需求，并针对错误关注点和不健康心理诉求给出反馈。
1. 对这件事情你关注什么？想要什么？你在维护什么？只有明确表述或有可靠事实依据推断出来的才进行说明。
2. 评估是否这种关注点和需求是否健康，并给出反馈（正面/建设性反馈）；如果存在问题那么更合适的满足方向是什么。
- 如果写更合适的满足方向，不要只给抽象结论；应尽量说明当前方式卡在哪里、新方向为什么更合适、第一步可以从什么行动开始。

事件级输出规则：
- 如果事件没有明确的关注点、诉求、期待、边界感或需求线索，则返回空数组，不硬做分析。
- 只有在同一事件里存在多个明显不同、难以自然合并的关注轴心或需求主题时，才允许输出多条，严格避免过度拆分。
日记级汇总：只梳理多个事件反复出现、或用户明确跨事件总结的关注点与需求；不得默认存在需求依赖问题，没有明确问题时不强制给调整方向。

### 4. 可行动建议（event_analyses[].action_suggestions / diary_analysis.action_suggestions）
核心目标：在前三类分析已经识别出明确调整空间时，将其转化为有价值、可执行的具象动作。
规则：每条建议为单一清晰动作；不重复分析理论，只输出实操行为；无对应线索则数组置空；

事件级输出规则：
- 如果事件中没有明确可落地的调整空间、推进动作、表达动作或预防动作，则返回空数组，不要为了完整性硬给建议。
- 可以输出多条，但每条建议必须对应不同的行动目标；如果多个动作属于同一个处理方案，应合并为一条，不要拆碎。
日记级汇总规则：
- 日记建议汇总事件级的关键动作，并针对至少两个事件共同呈现的问题给出调整动作；
- 按不同共性问题输出多条，但每条建议都要有独立主题；如果多个动作属于同一个处理方案，应合并为一条。
- 按重要程度排序，优先放置最能降低负面影响、最能解决重复问题、最容易执行且收益明确的建议。
""" + TEXT_MARKUP_RULES

CORE_ANALYSIS_OUTPUT_SCHEMA = """## 固定输出JSON模板
event_analyses 必须与输入 events 按顺序一一对应，即第 N 项对应 events 第 N 项。即使某个事件四类分析都没有内容，也必须输出该事件对象，并将四个分析数组置为空数组。title 直接复用对应事件标题。不要输出 event_index。

{
  "event_analyses": [
    {
      "title": "事件标题",
      "emotion_analyses": [
        "完整情绪分析段落"
      ],
      "behavior_decision_analyses": [
        "完整行为决策分析段落"
      ],
      "self_understanding_analyses": [
        "完整关注点需求分析段落"
      ],
      "action_suggestions": [
        "具象实操建议"
      ]
    }
  ],
  "diary_analysis": {
    "emotion_analyses": [
      "当日整体情绪总结段落"
    ],
    "behavior_decision_analyses": [
      "当日整体行为模式总结段落"
    ],
    "self_understanding_analyses": [
      "当日整体内在需求总结段落"
    ],
    "action_suggestions": [
      "针对全天共性问题的实操建议"
    ]
  }
}
"""

CORE_ANALYSIS_PROMPT = CORE_ANALYSIS_RULES + "\n\n" + CORE_ANALYSIS_OUTPUT_SCHEMA

COGNITION_ANALYSIS_RULES = PERSON_RELATION_RULES + "\n" + """你是一个日记认知分析助手。只基于 events 完成认知校准、问题解答和认知完善。
## 通用规则
- 仅以输入的 events 为唯一事实依据。事件级结果按 events 顺序排列，event_analyses 第 N 项对应 events 第 N 项，title 直接复用原事件标题；无符合内容时对应数组返回空。
- 分析事件 N 时只允许使用事件 N 的内容，禁止把相邻或其他事件中的观点、术语和事实用于事件 N。其他事件只能用于日记级归纳。
- 输出内容人称要求：分析内容是写给用户本人看的，不要使用“用户……”这类第三人称表述，优先使用“你……”或直接使用无主语的分析句式。
- 输出格式：严格输出标准JSON，除重点标记规则允许的 **...** 和 <red>...</red> 外，不要输出其他 markdown、HTML 或额外注释。

## 认知校准
目的：纠正 event 内容中的认知与现实情况或事实依据不一致的理解，包括用户对事实、因果、他人动机、自己判断、知识方法的不准确理解。
触发条件：当事件内容描述中的理解出现事实与解释混淆、过度概括、绝对化判断、无依据推断他人动机，或对知识、方法、因果关系理解不准确。
事件级规则：
- 只有能够同时指出“用户原理解”“更准确的事实或知识”“原理解具体错在哪里”时才输出。指出不准确时必须说明可靠依据，可以使用稳定的通用知识，但不得编造数据、来源或确定性结论；
- 当事件中没有理解时，直接输出空数组；
- 当事件中包含多个不同事物的理解时，需要输出多条。
日记级规则：
- 只有至少两个事件分别存在有明确依据的同类认知偏差时，才归纳日记级共性偏差；不得把一次事件扩大为全天模式。

## 问题解答
目的：回答 events 内容中明确提出或隐含的疑问。
触发条件：出现直接提问、“我不知道……”这类困惑、“有什么用”这类价值问题、“到底好不好”这类判断问题等明显疑惑时。
规则：
- 输出 question 和 answer，answer 先给核心结论，再给具体理由。
- 可以使用通用知识解释问题，但不能编造具体事实、数据、来源或确定性结论。
- 只输出事件中真实存在的问题，不要为了完整性硬补，事件中没有疑问时，直接输出空数组；当事件中包含多个不同的疑问时，需要输出多条。

## 认知完善
目的：把用户在 events 中已经表达出的零散知识、做事方式、感悟、成长、体会和半成品观点，以及上面的认知校准和问题解答内容，整理为结构清晰、边界明确、以后可复用的成体系的知识单元。
处理流程：
1. 提取原生认知：仅基于事件内容，精准提取用户真实表达的观点、经验、决策逻辑，禁止无依据拔高、过度引申、脑补用户未表达的结论。
2. 完善原生认知：结合模型知识，将原生认知升华为可复用的通用方法/框架，表述时先给出相关概念的准确含义，再结合当前事件说明具体体现、适用条件和边界。通用知识只能解释或校正用户已经表达的观点，不能成为新增观点的来源。
事件级规则：
- 只有用户明确表达了观点、经验、反思、原则、方法或待完善的理解时才输出；否则只返回空数组。
- 不得从普通行为反向创造“方法论”，不得为已有观点发明新术语、新框架或用户未表达的价值判断。
- 存在多个不同知识单元时输出多条；同一知识单元的概念、事件体现、适用条件和边界应合并成一条。
- 格式为“总结词语：详细说明”
日记级规则：
- 日记级只能归纳事件级已经存在的知识单元，或用户在日记中明确跨事件总结的观点；不得把零散行为拼接成新的共性知识。
""" + TEXT_MARKUP_RULES

COGNITION_ANALYSIS_OUTPUT_SCHEMA = """## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "event_analyses": [
    {
      "title": "事件标题",
      "cognitive_calibration_analyses": [
        "认知校准文本"
      ],
      "question_answers": [
        {
          "question": "问题",
          "answer": "回答"
        }
      ],
      "cognitive_enhancements": [
        "认知完善文本"
      ]
    }
  ],
  "diary_analysis": {
    "cognitive_calibration_analyses": [
      "日记级认知校准文本"
    ],
    "cognitive_enhancements": [
      "日记级认知完善文本"
    ]
  }
}"""

COGNITION_ANALYSIS_PROMPT = COGNITION_ANALYSIS_RULES + "\n\n" + COGNITION_ANALYSIS_OUTPUT_SCHEMA


# ---------------------------------------------------------------------------
# 3 个 Node 异步函数
# ---------------------------------------------------------------------------

def _json_dumps(value: Any) -> str:
    """统一 JSON 日志序列化，避免中文被转义。"""
    return json.dumps(value, ensure_ascii=False)


def _log_llm_request(step_name: str, system_prompt: str, input_data: dict) -> str:
    """记录分析流水线完整 LLM 请求，并返回 user message。"""
    user_message = _json_dumps(input_data)
    _ai_logger.info(
        "[%s] 完整LLM请求: system=%s\nuser=%s",
        step_name,
        system_prompt,
        user_message,
        extra=log_extra(event="analysis.llm.request_payload", step=step_name),
    )
    return user_message


def _log_llm_response(step_name: str, result: dict) -> None:
    """记录分析流水线完整 LLM JSON 响应。"""
    _ai_logger.info(
        "[%s] 完整LLM响应: %s",
        step_name,
        _json_dumps(result),
        extra=log_extra(event="analysis.llm.response_payload", step=step_name),
    )


def _list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _count_event_inner_items(event_items: Any, inner_key: str) -> int:
    if not isinstance(event_items, list):
        return 0
    total = 0
    for item in event_items:
        if isinstance(item, dict):
            total += _list_len(item.get(inner_key))
    return total


async def mood_tag_extract(state: AnalysisState) -> dict:
    """Node 1 (环节 7): 心情 + 标签提取 (temp=0.3)"""
    task_id = state["task_id"]
    started = Stopwatch()
    _update_step(task_id, "mood_tag_extract")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]
    event_count = _list_len(structured_diary.get("events"))
    logger.info(
        "分析流水线环节7开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        event_count,
    )

    llm = _get_llm(0.3, "analysis")
    input_data = {"structured_diary": structured_diary}
    result = await _invoke_llm(
        llm,
        MOOD_TAG_PROMPT,
        _log_llm_request("mood_tag_extract", MOOD_TAG_PROMPT, input_data),
        step_name="mood_tag_extract",
    )
    _log_llm_response("mood_tag_extract", result)

    mood = result.get("mood", "")
    if not isinstance(mood, str):
        mood = ""

    event_tags = result.get("event_tags", [])
    if not isinstance(event_tags, list):
        event_tags = []
    # 容错：确保每个元素有 title 和 tags 字段
    validated_event_tags = []
    for et in event_tags:
        if not isinstance(et, dict):
            continue
        title = et.get("title", "")
        tags = et.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}
        # 确保五类标签都是 list
        for tag_type in ["domain", "topic", "person_object", "psychological", "knowledge"]:
            if not isinstance(tags.get(tag_type), list):
                tags[tag_type] = []
        validated_event_tags.append({"title": title, "tags": tags})

    tag_count = 0
    for event_tag in validated_event_tags:
        tag_groups = event_tag.get("tags", {})
        if isinstance(tag_groups, dict):
            tag_count += sum(_list_len(tags) for tags in tag_groups.values())
    logger.info(
        "分析流水线环节7完成: diary_id=%s, task_id=%s, mood=%s, event_tag_count=%d, tag_count=%d",
        state.get("diary_id"),
        task_id,
        mood,
        len(validated_event_tags),
        tag_count,
        extra=log_extra(
            event="analysis.node.completed",
            step="mood_tag_extract",
            diary_id=state.get("diary_id"),
            task_id=task_id,
            event_count=event_count,
            event_tag_count=len(validated_event_tags),
            tag_count=tag_count,
            duration_ms=started.elapsed_ms(),
        ),
    )
    return {"mood": mood, "event_tags": validated_event_tags}


async def core_analysis(state: AnalysisState) -> dict:
    """环节 8：核心分析 + 可行动建议"""
    task_id = state["task_id"]
    started = Stopwatch()
    _update_step(task_id, "core_analysis")

    events = state["structured_diary"].get("events", [])
    input_data = {
        "events": events,
        "person_relations": state.get("person_relations", []),
    }
    logger.info(
        "分析流水线环节8开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        _list_len(events),
    )

    llm = _get_llm(0.5, "analysis")
    result = await _invoke_llm(
        llm,
        CORE_ANALYSIS_PROMPT,
        _log_llm_request("core_analysis", CORE_ANALYSIS_PROMPT, input_data),
        step_name="core_analysis",
    )
    _log_llm_response("core_analysis", result)

    # 提取并容错处理每个字段
    def safe_list(val):
        return val if isinstance(val, list) else []

    def safe_dict(val):
        return val if isinstance(val, dict) else {}

    event_analyses = []
    for item in safe_list(result.get("event_analyses")):
        if not isinstance(item, dict):
            continue
        event_analyses.append(
            {
                "title": item.get("title", ""),
                "emotion_analyses": safe_list(item.get("emotion_analyses")),
                "behavior_decision_analyses": safe_list(item.get("behavior_decision_analyses")),
                "self_understanding_analyses": safe_list(item.get("self_understanding_analyses")),
                "action_suggestions": safe_list(item.get("action_suggestions")),
            }
        )

    diary_analysis = safe_dict(result.get("diary_analysis"))
    output = {
        "event_analyses": event_analyses,
        "diary_analysis": {
            "emotion_analyses": safe_list(diary_analysis.get("emotion_analyses")),
            "behavior_decision_analyses": safe_list(diary_analysis.get("behavior_decision_analyses")),
            "self_understanding_analyses": safe_list(diary_analysis.get("self_understanding_analyses")),
            "action_suggestions": safe_list(diary_analysis.get("action_suggestions")),
        },
    }
    logger.info(
        "分析流水线环节8完成: diary_id=%s, task_id=%s, event_emotion=%d, diary_emotion=%d, event_behavior=%d, diary_behavior=%d, event_need=%d, diary_need=%d, event_action=%d, diary_action=%d",
        state.get("diary_id"),
        task_id,
        _count_event_inner_items(output["event_analyses"], "emotion_analyses"),
        _list_len(output["diary_analysis"]["emotion_analyses"]),
        _count_event_inner_items(output["event_analyses"], "behavior_decision_analyses"),
        _list_len(output["diary_analysis"]["behavior_decision_analyses"]),
        _count_event_inner_items(output["event_analyses"], "self_understanding_analyses"),
        _list_len(output["diary_analysis"]["self_understanding_analyses"]),
        _count_event_inner_items(output["event_analyses"], "action_suggestions"),
        _list_len(output["diary_analysis"]["action_suggestions"]),
        extra=log_extra(
            event="analysis.node.completed",
            step="core_analysis",
            diary_id=state.get("diary_id"),
            task_id=task_id,
            event_count=_list_len(events),
            duration_ms=started.elapsed_ms(),
        ),
    )
    return output


async def cognition_analysis(state: AnalysisState) -> dict:
    """环节 9：认知校准 + 问题解答 + 认知完善"""
    task_id = state["task_id"]
    started = Stopwatch()
    _update_step(task_id, "cognition_analysis")

    events = state["structured_diary"].get("events", [])
    input_data = {
        "events": events,
        "person_relations": state.get("person_relations", []),
    }
    logger.info(
        "分析流水线环节9开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        _list_len(events),
    )

    llm = _get_llm(0.5, "analysis")
    result = await _invoke_llm(
        llm,
        COGNITION_ANALYSIS_PROMPT,
        _log_llm_request("cognition_analysis", COGNITION_ANALYSIS_PROMPT, input_data),
        step_name="cognition_analysis",
    )
    _log_llm_response("cognition_analysis", result)

    def safe_list(val):
        return val if isinstance(val, list) else []

    def safe_dict(val):
        return val if isinstance(val, dict) else {}

    event_cognitive_calibration_analyses = []
    event_question_answers = []
    event_cognitive_enhancements = []
    for item in safe_list(result.get("event_analyses")):
        if not isinstance(item, dict):
            continue
        event_cognitive_calibration_analyses.append({
            "title": item.get("title", ""),
            "cognitive_calibration_analyses": safe_list(item.get("cognitive_calibration_analyses")),
        })
        event_question_answers.append({
            "title": item.get("title", ""),
            "question_answers": safe_list(item.get("question_answers")),
        })
        event_cognitive_enhancements.append({
            "title": item.get("title", ""),
            "cognitive_enhancements": safe_list(item.get("cognitive_enhancements")),
        })

    diary_analysis = safe_dict(result.get("diary_analysis"))
    output = {
        "event_cognitive_calibration_analyses": event_cognitive_calibration_analyses,
        "diary_cognitive_calibration_analyses": safe_list(diary_analysis.get("cognitive_calibration_analyses")),
        "event_question_answers": event_question_answers,
        "event_cognitive_enhancements": event_cognitive_enhancements,
        "diary_cognitive_enhancements": safe_list(diary_analysis.get("cognitive_enhancements")),
    }
    logger.info(
        "分析流水线环节9完成: diary_id=%s, task_id=%s, event_calibration=%d, diary_calibration=%d, event_qa=%d, event_enhancement=%d, diary_enhancement=%d",
        state.get("diary_id"),
        task_id,
        _count_event_inner_items(output["event_cognitive_calibration_analyses"], "cognitive_calibration_analyses"),
        _list_len(output["diary_cognitive_calibration_analyses"]),
        _count_event_inner_items(output["event_question_answers"], "question_answers"),
        _count_event_inner_items(output["event_cognitive_enhancements"], "cognitive_enhancements"),
        _list_len(output["diary_cognitive_enhancements"]),
        extra=log_extra(
            event="analysis.node.completed",
            step="cognition_analysis",
            diary_id=state.get("diary_id"),
            task_id=task_id,
            event_count=_list_len(events),
            duration_ms=started.elapsed_ms(),
        ),
    )
    return output


async def feedback_core_analysis(state: FeedbackAnalysisState) -> dict:
    """反馈重分析节点 1：根据反馈重写核心分析。"""
    task_id = state["task_id"]
    started = Stopwatch()
    _update_step(task_id, "feedback_core_analysis")

    feedback_context = state["feedback_context"]
    core_input = {
        "structured_diary": state["structured_diary"],
        "person_relations": state.get("person_relations", []),
        "previous_core_analysis": {
            "diary_analysis": state["previous_state"]["diary_analysis"],
            "event_analyses": state["previous_state"]["event_analyses"],
        },
        "feedback": [
            item for item in feedback_context if item["analysis_type"] in CORE_ANALYSIS_TYPES
        ],
    }
    if not core_input["feedback"]:
        logger.info(
            "反馈核心分析无命中内容，复用上一轮结果",
            extra=log_extra(event="analysis.feedback.node.reused", step="feedback_core_analysis", task_id=task_id, feedback_count=0),
        )
        return {"merged_core": state["previous_state"]}

    llm = _get_llm(0.2, "analysis")
    core_result = await _invoke_llm(
        llm,
        FEEDBACK_CORE_ANALYSIS_PROMPT,
        _log_llm_request("feedback_core_analysis", FEEDBACK_CORE_ANALYSIS_PROMPT, core_input),
        step_name="feedback_core_analysis",
    )
    _log_llm_response("feedback_core_analysis", core_result)
    logger.info(
        "反馈核心分析节点完成",
        extra=log_extra(event="analysis.node.completed", step="feedback_core_analysis", task_id=task_id, feedback_count=len(core_input["feedback"]), duration_ms=started.elapsed_ms()),
    )
    return {
        "merged_core": _merge_feedback_core(
            state["previous_state"], core_result, feedback_context
        )
    }


async def feedback_cognition_analysis(state: FeedbackAnalysisState) -> dict:
    """反馈重分析节点 2：根据反馈重写认知分析。"""
    task_id = state["task_id"]
    started = Stopwatch()
    _update_step(task_id, "feedback_cognition_analysis")

    feedback_context = state["feedback_context"]
    previous_state = state["previous_state"]
    cognition_input = {
        "structured_diary": state["structured_diary"],
        "person_relations": state.get("person_relations", []),
        "previous_cognition_analysis": {
            "diary_cognitive_calibration_analyses": previous_state[
                "diary_cognitive_calibration_analyses"
            ],
            "diary_cognitive_enhancements": previous_state["diary_cognitive_enhancements"],
            "event_cognitive_calibration_analyses": previous_state[
                "event_cognitive_calibration_analyses"
            ],
            "event_question_answers": previous_state["event_question_answers"],
            "event_cognitive_enhancements": previous_state["event_cognitive_enhancements"],
        },
        "feedback": [
            item for item in feedback_context if item["analysis_type"] in COGNITION_ANALYSIS_TYPES
        ],
    }
    if not cognition_input["feedback"]:
        logger.info(
            "反馈认知分析无命中内容，复用上一轮结果",
            extra=log_extra(event="analysis.feedback.node.reused", step="feedback_cognition_analysis", task_id=task_id, feedback_count=0),
        )
        return {"merged": state["merged_core"]}

    llm = _get_llm(0.2, "analysis")
    cognition_result = await _invoke_llm(
        llm,
        FEEDBACK_COGNITION_ANALYSIS_PROMPT,
        _log_llm_request(
            "feedback_cognition_analysis", FEEDBACK_COGNITION_ANALYSIS_PROMPT, cognition_input
        ),
        step_name="feedback_cognition_analysis",
    )
    _log_llm_response("feedback_cognition_analysis", cognition_result)
    logger.info(
        "反馈认知分析节点完成",
        extra=log_extra(event="analysis.node.completed", step="feedback_cognition_analysis", task_id=task_id, feedback_count=len(cognition_input["feedback"]), duration_ms=started.elapsed_ms()),
    )
    return {
        "merged": _merge_feedback_cognition(
            state["merged_core"], cognition_result, feedback_context
        )
    }


# ---------------------------------------------------------------------------
# 标签落库
# ---------------------------------------------------------------------------

def _persist_tags(
    user_id: str,
    diary_id: str,
    diary_organized_id: str,
    event_tags: list,
):
    """
    将分析环节提取的标签落库：
    1. upsert 标签到 tags 表（按 user_id + name 去重）
    2. 删除该日记的旧 diary_tags 和旧 event_tags 关联
    3. 为每个事件创建 event_tags 关联
    4. 为日记创建 diary_tags 关联（去重后）
    """
    db = SessionLocal()
    started = Stopwatch()
    logger.info(
        "开始标签落库",
        extra=log_extra(event="analysis.tags.persist_started", diary_id=diary_id, diary_organized_id=diary_organized_id, event_tag_count=_list_len(event_tags)),
    )
    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        diary_uuid = uuid.UUID(diary_id) if isinstance(diary_id, str) else diary_id
        org_uuid = uuid.UUID(diary_organized_id) if isinstance(diary_organized_id, str) else diary_organized_id

        # 查找该日记下的所有事件（用于匹配事件标题 → diary_event_id）
        events = (
            db.query(DiaryEvent)
            .filter(DiaryEvent.diary_organized_id == org_uuid)
            .all()
        )
        # 构建 event_title → diary_event_id 映射
        title_to_event_id: dict[str, uuid.UUID] = {}
        for ev in events:
            if ev.event_title:
                title_to_event_id[ev.event_title] = ev.id

        # ── 1. 删除旧关联 ──
        # 删除该日记的旧 diary_tags 关联
        db.execute(diary_tags.delete().where(diary_tags.c.diary_id == diary_uuid))

        # 删除该日记所有事件的旧 event_tags 关联
        event_ids = [ev.id for ev in events]
        if event_ids:
            db.execute(
                EventTag.__table__.delete().where(
                    EventTag.__table__.c.diary_event_id.in_(event_ids)
                )
            )

        # ── 2. Upsert 标签并收集关联 ──
        all_tag_ids: set[uuid.UUID] = set()  # 日记级去重
        tag_cache: dict[str, Tag] = {}  # name → Tag 实例缓存

        def _get_or_create_tag(name: str, tag_type: str) -> Tag:
            """按 user_id + name upsert 标签"""
            if name in tag_cache:
                existing = tag_cache[name]
                # 如果已有标签的 type 为空，更新 type
                if not existing.type and tag_type:
                    existing.type = tag_type
                    db.flush()
                return existing

            tag = (
                db.query(Tag)
                .filter(Tag.user_id == user_uuid, Tag.name == name)
                .first()
            )
            if tag:
                if not tag.type and tag_type:
                    tag.type = tag_type
                    db.flush()
            else:
                tag = Tag(user_id=user_uuid, name=name, type=tag_type)
                db.add(tag)
                db.flush()
            tag_cache[name] = tag
            return tag

        # ── 3. 遍历事件级标签，创建关联 ──
        # 用内存 set 跟踪本批次已添加的 (event_id, tag_id) 对，防止重复插入
        added_event_tag_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()

        for et in event_tags:
            event_title = et.get("title", "")
            tags_dict = et.get("tags", {})
            event_id = title_to_event_id.get(event_title)

            for tag_type, tag_names in tags_dict.items():
                if not isinstance(tag_names, list):
                    continue
                for tag_name in tag_names:
                    if not isinstance(tag_name, str) or not tag_name.strip():
                        continue
                    tag_name = tag_name.strip()
                    tag = _get_or_create_tag(tag_name, tag_type)
                    all_tag_ids.add(tag.id)

                    # 创建事件-标签关联（去重：DB + 内存双重检查）
                    if event_id:
                        pair = (event_id, tag.id)
                        if pair not in added_event_tag_pairs:
                            existing_link = (
                                db.query(EventTag)
                                .filter(
                                    EventTag.diary_event_id == event_id,
                                    EventTag.tag_id == tag.id,
                                )
                                .first()
                            )
                            if not existing_link:
                                db.add(EventTag(diary_event_id=event_id, tag_id=tag.id))
                            added_event_tag_pairs.add(pair)

        # ── 4. 创建日记-标签关联（去重） ──
        for tag_id in all_tag_ids:
            db.execute(
                diary_tags.insert().values(diary_id=diary_uuid, tag_id=tag_id)
            )

        db.commit()
        logger.info(
            "标签落库完成: diary_id=%s, 标签数=%d",
            diary_id,
            len(all_tag_ids),
            extra=log_extra(event="analysis.tags.persisted", diary_id=diary_id, diary_organized_id=diary_organized_id, tag_count=len(all_tag_ids), event_count=len(events), duration_ms=started.elapsed_ms()),
        )
    except Exception as e:
        logger.exception(
            "标签落库失败",
            extra=log_extra(event="analysis.tags.persist_failed", diary_id=diary_id, diary_organized_id=diary_organized_id, error_type=type(e).__name__, duration_ms=started.elapsed_ms()),
        )
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 结果存储 + 状态更新
# ---------------------------------------------------------------------------

def _save_analysis_result(
    state: AnalysisState,
    diary_organized_id: str,
    feedback_source_run_id: str | None = None,
    inherited_feedback_keys: set[tuple] | None = None,
):
    """将分析结果存入历史分析表，并将新轮次标记为 CURRENT。"""
    db = SessionLocal()
    started = Stopwatch()
    try:
        diary_id = state["diary_id"]
        task_id = state["task_id"]
        diary_uuid = uuid.UUID(diary_id) if isinstance(diary_id, str) else diary_id
        if feedback_source_run_id and inherited_feedback_keys is None:
            inherited_feedback_keys = feedback_keys_for_run(db, feedback_source_run_id)
        run = create_analysis_run_from_state(
            db,
            state,
            diary_organized_id,
            feedback_source_run_id=feedback_source_run_id,
            inherited_feedback_keys=inherited_feedback_keys,
        )

        # 更新日记状态为 analyzed
        diary = db.query(Diary).filter(Diary.id == diary_uuid).first()
        old_status = diary.status.value if diary and hasattr(diary.status, "value") else str(diary.status) if diary else None
        if diary:
            diary.status = DiaryStatus.analyzed

        db.commit()
        logger.info(
            "分析结果已保存: diary_id=%s, task_id=%s",
            diary_id,
            task_id,
            extra=log_extra(
                event="analysis.result.persisted",
                diary_id=diary_id,
                task_id=task_id,
                analysis_run_id=str(run.id),
                feedback_source_run_id=feedback_source_run_id,
                old_status=old_status,
                new_status="analyzed",
                analysis_item_count=len(run.items),
                duration_ms=started.elapsed_ms(),
            ),
        )
    except Exception as e:
        logger.exception(
            "保存分析结果失败",
            extra=log_extra(event="analysis.result.persist_failed", diary_id=state.get("diary_id"), task_id=state.get("task_id"), error_type=type(e).__name__, duration_ms=started.elapsed_ms()),
        )
        db.rollback()
        raise
    finally:
        db.close()


FEEDBACK_CORE_ANALYSIS_OUTPUT_SCHEMA = """

## 反馈重写模式
你将收到 3 类输入：
1. structured_diary：结构化日记，是唯一事实依据。只能基于其中的 events、trivia、plans 进行重写。
2. previous_core_analysis：上一轮核心分析结果，是本次被参考和修正的旧分析，不是事实依据。
3. feedback：用户对上一轮分析结果的反馈意见，用于指出旧分析哪里不准确、太泛、遗漏重点或需要调整。feedback 不是事实，不能当作新增日记内容。

## 重写范围
- 本次只重写 feedback 命中的 analysis_type。
- 用户对某个事件的某个 analysis_type 的反馈，作用于该事件该 analysis_type 的整体分析内容，不只是修改某一句话。

## 日记级同步重写
- 如果 feedback 命中 EVENT 级某个 analysis_type，必须同时重写 DIARY 级同一个 analysis_type。
- DIARY 级同类型分析要基于全量 structured_diary.events，并参考 previous_core_analysis 中同类型的事件级分析和本次事件级重写方向重新得出。如果用户对日记级分析结果给了反馈意见要着重参考。

## 输出要求
- 输出必须是标准 JSON，除 **...** 和 <red>...</red> 外，不要包含其他 markdown、HTML、解释文字或额外字段。
格式如下：
{
  "rewrites": [
    {
      "scope": "DIARY",
      "event_title": null,
      "analysis_type": "EMOTION",
      "items": ["重写后的分析内容"]
    },
    {
      "scope": "EVENT",
      "event_title": "事件标题",
      "analysis_type": "BEHAVIOR_DECISION",
      "items": ["重写后的分析内容"]
    }
  ]
}
"""

FEEDBACK_CORE_ANALYSIS_PROMPT = CORE_ANALYSIS_RULES + "\n\n" + FEEDBACK_CORE_ANALYSIS_OUTPUT_SCHEMA


FEEDBACK_COGNITION_ANALYSIS_OUTPUT_SCHEMA = """

## 反馈重写模式
你将收到 3 类输入：
1. structured_diary：结构化日记，是唯一事实依据。只能基于其中的 events、trivia、plans 进行重写。
2. previous_cognition_analysis：上一轮认知分析结果，是本次被参考和修正的旧分析，不是事实依据。
3. feedback：用户对上一轮分析结果的反馈意见，用于指出旧分析哪里不准确、太泛、遗漏重点或需要调整。feedback 不是事实，不能当作新增日记内容。

## 重写范围
- 本次只重写 feedback 命中的 analysis_type。
- 用户对某个事件的某个 analysis_type 的反馈，不要扩散到其他 analysis_type。

## 日记级同步重写
- 如果 feedback 命中 EVENT 级某个 analysis_type，必须同时重写 DIARY 级同一个 analysis_type。
- DIARY 级同类型分析要基于全量 structured_diary.events，并参考 previous_cognition_analysis 中同类型的事件级分析和本次事件级重写方向重新得出。如果用户对日记级分析结果给了反馈意见要着重参考。

## 输出要求
- 输出必须是标准 JSON，除 **...** 和 <red>...</red> 外，不要包含其他 markdown、HTML、解释文字或额外字段。
格式如下：
{
  "rewrites": [
    {
      "scope": "DIARY",
      "event_title": null,
      "analysis_type": "COGNITIVE_CALIBRATION",
      "items": ["重写后的分析内容"]
    },
    {
      "scope": "EVENT",
      "event_title": "事件标题",
      "analysis_type": "QUESTION_ANSWER",
      "items": [
        {"question": "问题", "answer": "重写后的回答"}
      ]
    }
  ]
}
"""

FEEDBACK_COGNITION_ANALYSIS_PROMPT = COGNITION_ANALYSIS_RULES + "\n\n" + FEEDBACK_COGNITION_ANALYSIS_OUTPUT_SCHEMA


def _feedback_targets(feedback_context: list[dict], allowed_types: set[str]) -> set[tuple]:
    targets = {
        (item.get("scope"), item.get("event_title"), item.get("analysis_type"))
        for item in feedback_context
        if item.get("analysis_type") in allowed_types
    }
    for scope, _event_title, analysis_type in list(targets):
        if scope == "EVENT":
            targets.add(("DIARY", None, analysis_type))
    return targets


def _inherited_feedback_keys(feedback_context: list[dict]) -> set[tuple]:
    keys = set()
    for item in feedback_context:
        scope = item.get("scope")
        event_id = item.get("event_id")
        analysis_type = item.get("analysis_type")
        if scope not in {"DIARY", "EVENT"} or not analysis_type:
            continue
        keys.add(section_key(scope, event_id, analysis_type))
        if scope == "EVENT":
            keys.add(section_key("DIARY", None, analysis_type))
    return keys


def _rewrite_items_by_target(rewritten: dict) -> dict[tuple, list]:
    result: dict[tuple, list] = {}
    rewrites = rewritten.get("rewrites", []) if isinstance(rewritten, dict) else []
    if not isinstance(rewrites, list):
        return result
    for rewrite in rewrites:
        if not isinstance(rewrite, dict):
            continue
        scope = rewrite.get("scope")
        event_title = rewrite.get("event_title")
        analysis_type = rewrite.get("analysis_type")
        items = rewrite.get("items", [])
        if scope not in {"DIARY", "EVENT"} or not analysis_type or not isinstance(items, list):
            continue
        result[(scope, event_title, analysis_type)] = items
    return result


def _merge_feedback_core(previous: dict, rewritten: dict, feedback_context: list[dict]) -> dict:
    targets = _feedback_targets(feedback_context, CORE_ANALYSIS_TYPES)
    if not targets:
        return previous

    merged = json.loads(json.dumps(previous, ensure_ascii=False))
    rewrite_items = _rewrite_items_by_target(rewritten)
    field_by_type = {
        "EMOTION": "emotion_analyses",
        "BEHAVIOR_DECISION": "behavior_decision_analyses",
        "SELF_UNDERSTANDING": "self_understanding_analyses",
        "ACTION_SUGGESTION": "action_suggestions",
    }

    for analysis_type, field_name in field_by_type.items():
        if ("DIARY", None, analysis_type) in targets:
            rewrite_key = ("DIARY", None, analysis_type)
            if rewrite_key in rewrite_items:
                merged["diary_analysis"][field_name] = safe_list(rewrite_items[rewrite_key])

    for idx, current_event in enumerate(merged.get("event_analyses", [])):
        title = current_event.get("title")
        for analysis_type, field_name in field_by_type.items():
            if ("EVENT", title, analysis_type) in targets:
                rewrite_key = ("EVENT", title, analysis_type)
                if rewrite_key in rewrite_items:
                    current_event[field_name] = safe_list(rewrite_items[rewrite_key])

    return merged


def _merge_feedback_cognition(previous: dict, rewritten: dict, feedback_context: list[dict]) -> dict:
    targets = _feedback_targets(feedback_context, COGNITION_ANALYSIS_TYPES)
    if not targets:
        return previous

    merged = json.loads(json.dumps(previous, ensure_ascii=False))
    rewrite_items = _rewrite_items_by_target(rewritten)

    if ("DIARY", None, "COGNITIVE_CALIBRATION") in targets:
        rewrite_key = ("DIARY", None, "COGNITIVE_CALIBRATION")
        if rewrite_key in rewrite_items:
            merged["diary_cognitive_calibration_analyses"] = safe_list(rewrite_items[rewrite_key])
    if ("DIARY", None, "COGNITIVE_ENHANCEMENT") in targets:
        rewrite_key = ("DIARY", None, "COGNITIVE_ENHANCEMENT")
        if rewrite_key in rewrite_items:
            merged["diary_cognitive_enhancements"] = safe_list(rewrite_items[rewrite_key])

    event_field_map = {
        "COGNITIVE_CALIBRATION": ("event_cognitive_calibration_analyses", "cognitive_calibration_analyses"),
        "QUESTION_ANSWER": ("event_question_answers", "question_answers"),
        "COGNITIVE_ENHANCEMENT": ("event_cognitive_enhancements", "cognitive_enhancements"),
    }
    for analysis_type, (state_key, field_name) in event_field_map.items():
        for idx, current_event in enumerate(merged.get(state_key, [])):
            title = current_event.get("title")
            if ("EVENT", title, analysis_type) in targets:
                rewrite_key = ("EVENT", title, analysis_type)
                if rewrite_key in rewrite_items:
                    current_event[field_name] = safe_list(rewrite_items[rewrite_key])

    return merged


# ---------------------------------------------------------------------------
# 流水线执行
# ---------------------------------------------------------------------------

async def run_analysis_pipeline(
    original_text: str,
    structured_diary: dict,
    task_id: str,
    diary_id: str,
    user_id: str,
    diary_organized_id: str,
    feedback_source_run_id: str | None = None,
) -> dict:
    """构建并执行 LangGraph 分析流水线（3 环节串行）。"""
    started = Stopwatch()
    logger.info(
        "分析流水线开始: diary_id=%s, task_id=%s, diary_organized_id=%s, event_count=%d",
        diary_id,
        task_id,
        diary_organized_id,
        _list_len(structured_diary.get("events")),
        extra=log_extra(event="analysis.pipeline.started", diary_id=diary_id, task_id=task_id, diary_organized_id=diary_organized_id, event_count=_list_len(structured_diary.get("events")), feedback_source_run_id=feedback_source_run_id),
    )
    db = SessionLocal()
    try:
        person_relations = load_person_relation_context(db, user_id)
    finally:
        db.close()

    builder = StateGraph(AnalysisState)
    builder.add_node("mood_tag_extract", mood_tag_extract)
    builder.add_node("core_analysis", core_analysis)
    builder.add_node("cognition_analysis", cognition_analysis)

    # 串行执行：每个节点完成后保存一个 checkpoint，失败重试时从失败节点继续。
    builder.add_edge(START, "mood_tag_extract")
    builder.add_edge("mood_tag_extract", "core_analysis")
    builder.add_edge("core_analysis", "cognition_analysis")
    builder.add_edge("cognition_analysis", END)

    # 配置 checkpointer（支持断点续跑）
    async with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)

        # 首次执行或从 checkpoint 恢复
        result = await run_graph_with_checkpoint(
            graph,
            task_id,
            {
                "original_text": original_text,
                "structured_diary": structured_diary,
                "task_id": task_id,
                "diary_id": diary_id,
                "user_id": user_id,
                "person_relations": person_relations,
                "diary_organized_id": diary_organized_id,
            },
        )
    logger.info("分析流水线图执行完成: diary_id=%s, task_id=%s", diary_id, task_id)

    # 提取结果
    analysis_result = {
        "mood": result.get("mood", ""),
        "event_tags": result.get("event_tags", []),
        "event_analyses": result.get("event_analyses", []),
        "diary_analysis": result.get("diary_analysis", {}),
        "event_cognitive_calibration_analyses": result.get("event_cognitive_calibration_analyses", []),
        "diary_cognitive_calibration_analyses": result.get("diary_cognitive_calibration_analyses", []),
        "event_question_answers": result.get("event_question_answers", []),
        "event_cognitive_enhancements": result.get("event_cognitive_enhancements", []),
        "diary_cognitive_enhancements": result.get("diary_cognitive_enhancements", []),
    }

    # 标签落库
    try:
        _persist_tags(user_id, diary_id, diary_organized_id, analysis_result["event_tags"])
    except Exception as e:
        logger.exception(
            "标签落库异常（不影响分析结果返回）",
            extra=log_extra(event="analysis.tags.degraded", diary_id=diary_id, task_id=task_id, error_type=type(e).__name__),
        )

    # 保存分析结果 + 更新日记状态
    _update_step(task_id, "saving_result")
    _save_analysis_result(
        result,
        diary_organized_id,
        feedback_source_run_id=feedback_source_run_id,
    )
    # 清理 checkpoint 不应影响已提交的分析结果。
    try:
        await cleanup_checkpoint(task_id)
        logger.info("分析流水线 checkpoint 已清理: diary_id=%s, task_id=%s", diary_id, task_id, extra=log_extra(event="analysis.checkpoint.cleaned", diary_id=diary_id, task_id=task_id, checkpoint_action="cleanup"))
    except Exception as cleanup_error:
        logger.warning("分析流水线 checkpoint 清理失败，保留 checkpoint: diary_id=%s, task_id=%s, error=%s", diary_id, task_id, cleanup_error, extra=log_extra(event="analysis.checkpoint.cleanup_failed", diary_id=diary_id, task_id=task_id, checkpoint_action="retained", error_type=type(cleanup_error).__name__))
    logger.info(
        "分析流水线完成: diary_id=%s, task_id=%s, mood=%s, event_tags=%d, diary_actions=%d",
        diary_id,
        task_id,
        analysis_result["mood"],
        _list_len(analysis_result["event_tags"]),
        _list_len(analysis_result["diary_analysis"].get("action_suggestions") if isinstance(analysis_result["diary_analysis"], dict) else []),
        extra=log_extra(event="analysis.pipeline.completed", diary_id=diary_id, task_id=task_id, event_tag_count=_list_len(analysis_result["event_tags"]), duration_ms=started.elapsed_ms()),
    )

    return analysis_result


async def run_feedback_reanalysis_pipeline(
    structured_diary: dict,
    task_id: str,
    diary_id: str,
    user_id: str,
    diary_organized_id: str,
    previous_run_id: str,
) -> dict:
    """基于低分文字反馈串行重写环节 8、9，不重跑心情和标签。"""
    started = Stopwatch()
    logger.info(
        "反馈重分析流水线开始",
        extra=log_extra(event="analysis.feedback.pipeline.started", diary_id=diary_id, task_id=task_id, previous_run_id=previous_run_id),
    )
    db = SessionLocal()
    try:
        previous_run = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.id == uuid.UUID(previous_run_id))
            .first()
        )
        if not previous_run:
            raise ValueError("上一轮分析结果不存在")

        org_uuid = uuid.UUID(diary_organized_id) if isinstance(diary_organized_id, str) else diary_organized_id
        event_records = (
            db.query(DiaryEvent)
            .filter(DiaryEvent.diary_organized_id == org_uuid)
            .order_by(DiaryEvent.sort_order)
            .all()
        )
        feedbacks = effective_feedback(db, previous_run.id)
        if not feedbacks:
            logger.warning(
                "反馈重分析没有有效反馈",
                extra=log_extra(event="analysis.feedback.pipeline.rejected", diary_id=diary_id, task_id=task_id, previous_run_id=previous_run_id, reason="feedback_missing"),
            )
            raise ValueError("没有可用于反馈重写的低分文字反馈")

        person_relations = load_person_relation_context(db, user_id)
        previous_state = run_to_state(previous_run, event_records)
        feedback_context = feedback_to_context(feedbacks, event_records)
    finally:
        db.close()

    builder = StateGraph(FeedbackAnalysisState)
    builder.add_node("feedback_core_analysis", feedback_core_analysis)
    builder.add_node("feedback_cognition_analysis", feedback_cognition_analysis)
    builder.add_edge(START, "feedback_core_analysis")
    builder.add_edge("feedback_core_analysis", "feedback_cognition_analysis")
    builder.add_edge("feedback_cognition_analysis", END)

    async with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        # 首次执行或从 checkpoint 恢复
        result = await run_graph_with_checkpoint(
            graph,
            task_id,
            {
                "structured_diary": structured_diary,
                "person_relations": person_relations,
                "task_id": task_id,
                "diary_id": diary_id,
                "user_id": user_id,
                "diary_organized_id": diary_organized_id,
                "previous_run_id": previous_run_id,
                "previous_state": previous_state,
                "feedback_context": feedback_context,
            },
        )

    merged = result["merged"]

    merged.update(
        {
            "task_id": task_id,
            "diary_id": diary_id,
            "diary_organized_id": diary_organized_id,
            "user_id": user_id,
            "structured_diary": structured_diary,
        }
    )

    _update_step(task_id, "saving_result")
    _save_analysis_result(
        merged,
        diary_organized_id,
        feedback_source_run_id=previous_run_id,
        inherited_feedback_keys=_inherited_feedback_keys(feedback_context),
    )
    # 清理 checkpoint 不应影响已提交的反馈重分析结果。
    try:
        await cleanup_checkpoint(task_id)
        logger.info("反馈重分析 checkpoint 已清理: diary_id=%s, task_id=%s", diary_id, task_id)
    except Exception as cleanup_error:
        logger.warning("反馈重分析 checkpoint 清理失败，保留 checkpoint: diary_id=%s, task_id=%s, error=%s", diary_id, task_id, cleanup_error)
    logger.info(
        "反馈重分析完成: diary_id=%s, task_id=%s, feedback_count=%d",
        diary_id,
        task_id,
        len(feedback_context),
        extra=log_extra(event="analysis.feedback.pipeline.completed", diary_id=diary_id, task_id=task_id, previous_run_id=previous_run_id, feedback_count=len(feedback_context), duration_ms=started.elapsed_ms()),
    )
    return merged
