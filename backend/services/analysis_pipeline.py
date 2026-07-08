"""LangGraph 分析流水线 - 3 环节并行 + 标签落库"""

import json
import logging
import uuid
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from config import settings
from database import SessionLocal
from models.diary import Diary, DiaryAnalysis, DiaryEvent, DiaryOrganized, DiaryStatus, OrganizeTask
from models.tag import EventTag, Tag, diary_tags
from services.pipeline import _get_llm, _invoke_llm, _update_step, get_checkpointer, cleanup_checkpoint

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

    # ── 环节 7 产物：心情 + 标签提取 ──
    mood: str
    event_tags: list

    # ── 环节 8 产物：核心分析 + 可行动建议 ──
    event_emotion_analyses: list
    diary_emotion_analyses: list
    event_behavior_decision_analyses: list
    diary_behavior_decision_analyses: list
    event_self_understanding_analyses: list
    diary_self_understanding_analyses: list
    event_action_suggestions: list
    diary_action_suggestions: list

    # ── 环节 9 产物：认知校准 + 问题解答 + 认知完善 ──
    event_cognitive_calibration_analyses: list
    diary_cognitive_calibration_analyses: list
    event_question_answers: list
    diary_question_answers: list
    event_cognitive_enhancements: list
    diary_cognitive_enhancements: list

    # ── 进度追踪 ──
    current_step: str


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MOOD_TAG_PROMPT = """你是一个日记心情与标签提取助手。请根据结构化日记和原始文本，提取当天整体心情和事件级标签。

## 任务目标
1. 提取当天整体心情 mood。
2. 为每个事件提取事件级标签 event_tags，按五类分组。

## 输入说明
structured_diary 是整理后的结构化日记，是主要依据。
original_text 是原始日记文本，仅用于核对事实。不要从 original_text 中挖掘 structured_diary 已经剔除的语言噪音。

## 心情提取规则
1. 心情用一个短词表示当天整体情绪或状态，例如"疲惫""平静""烦躁""开心""低落""充实""焦虑""放松"。
2. 必须有 structured_diary 或 original_text 中的明确线索支撑。
3. 没有明确线索则填空字符串。

## 标签提取规则
1. 标签不是简单分类，而是为后续检索、AI 对话、人物画像、心路历程和知识沉淀提供入口。
2. 标签类型固定为五类：domain、topic、person_object、psychological、knowledge。
3. 只输出事件级标签，不直接输出整篇日记级标签。日记级标签由所有事件级标签合并、去重后得到。
4. event_tags 必须与 structured_diary.events 一一对应，title 使用事件 title。
5. 每个事件的 tags 都按五类输出：domain、topic、person_object、psychological、knowledge。
6. 每种标签类型都输出数组；没有对应标签时输出空数组。同一事件、同一类型下可以有多个标签，但不要重复。
7. 优先提取 topic、person_object、psychological、knowledge；domain 只作为辅助粗分类，数量要少。
8. 标签必须来自 original_text 或 structured_diary 中的明确依据。
9. 不要生成原文没有依据的标签。
10. 不要生成空泛评价型标签，例如"成长""感悟""重要""日常"。
11. 心情词不要重复作为标签。

## 标签类型说明
- domain：领域标签，用于粗粒度筛选日记，例如"工作""生活""关系""健康""学习""娱乐"。
- topic：主题标签，用于串起长期反复出现的具体事项，例如"日记管理""AI 开发""小红书爬虫""遛狗"。
- person_object：人物 / 对象标签，用于串起具体人物、关系和重要对象，例如"林萧鹏""田总""媳妇""达达"。
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

CORE_ANALYSIS_PROMPT = """你是一个日记核心分析与建议助手。请基于 events，生成事件级分析、整篇日记总结和可行动建议。

## 任务目标
基于当天日记事件，输出三部分分析和可行动建议：
1. 情绪分析：event_emotion_analyses、diary_emotion_analyses
2. 行为与决策分析：event_behavior_decision_analyses、diary_behavior_decision_analyses
3. 关注点、需求与自我理解：event_self_understanding_analyses、diary_self_understanding_analyses
4. 可行动建议：event_action_suggestions、diary_action_suggestions

## 输入说明
events 是整理后的日记事件列表，是唯一依据。
不要引用 events 之外的信息。

## 核心边界
1. 只分析当天这篇日记，不引用当天以外的信息。
2. 不做长期人格判断、心理诊断、贴标签。
3. 较强推断必须写依据，依据来自 events 中的具体事件或事实。
4. 只做描述性和解释性分析，不做评判。
5. 不把推导写成绝对事实。
6. 所有分析字段都输出数组；没有明显线索时返回空数组，不硬凑分析。
7. 没有明显可行动建议时返回空数组，不硬凑建议。
8. 每个事件级结果必须与 events 按顺序一一对应，event_index 从 0 开始，title 使用对应事件的 title，不要改写。

## 情绪分析
为每个事件生成 emotion_analyses，并基于所有事件生成 diary_emotion_analyses。二者都是数组。

分析内容：
- 主要情绪。
- 情绪变化路径。
- 触发情绪的具体事实。
- 情绪背后被触动的东西（重点），例如需求、边界、控制感、确定性、价值排序、自我叙事。
- 可以区分表层情绪和更深层的情绪，但必须有事件依据。

分析规则：
- 事件级分析只分析该事件，不引用其他事件。
- 日记级分析需要综合所有事件，整理成当天整体情绪总结。
- 如果某个事件没有明显情绪线索，该事件 emotion_analyses 返回空数组。
- 如果整篇日记没有明显情绪线索，diary_emotion_analyses 返回空数组。
- 不输出 events 中没有依据的深层解释。

## 行为与决策分析
为每个事件生成 behavior_decision_analyses，并基于所有事件生成 diary_behavior_decision_analyses。二者都是数组。

分析内容：
- 用户做了什么。
- 用户做了什么选择。
- 用户遇到问题时怎么处理（核心）。
- 行为已经带来的结果。
- 行为可能带来的后续风险。

分析规则：
- 可以指出当天体现出的行为模式线索，例如主动推进、等待观察、反复确认、寻求外部帮助、暂时回避、先处理情绪再处理事情。
- 行为模式只能写成"今天体现出……"，不能写成长期人格或固定模式。
- 如果事件还没有结果，可以基于当天事实适当推测后续风险。
- 事件级分析只分析该事件，不引用其他事件。
- 日记级分析需要综合所有事件，整理成当天整体行为与决策总结。
- 如果某个事件没有明显行为或决策线索，该事件 behavior_decision_analyses 返回空数组。
- 如果整篇日记没有明显行为或决策线索，diary_behavior_decision_analyses 返回空数组。

## 关注点、需求与自我理解
为每个事件生成 self_understanding_analyses，并基于所有事件生成 diary_self_understanding_analyses。二者都是数组。

分析内容：
- 用户真正关注什么。
- 用户当下想要什么。
- 用户正在维护什么。
- 用户怎么看待这件事。
- 这件事反映用户看重什么。

分析规则：
- 可以分析未说出口的期待，例如希望对方主动回应、希望事情有明确进展、希望自己的投入被看见、希望责任边界更清楚、希望获得尊重、理解、确定性、公平或掌控感。
- 可以写"你真正想要的是……"，但必须有 events 中的明确依据。
- 不要把推断写成绝对事实。较强推断要写明依据。
- 事件级分析只分析该事件，不引用其他事件。
- 日记级分析需要综合所有事件，整理成当天整体自我理解总结。
- 如果某个事件没有明显线索，该事件 self_understanding_analyses 返回空数组。
- 如果整篇日记没有明显线索，diary_self_understanding_analyses 返回空数组。
- 帮助用户理解自己，不评价用户。

## 可行动建议
为每个事件生成 action_suggestions，并基于整篇日记生成 diary_action_suggestions。

分析依据：
- 可以基于 events 中的具体事实。
- 可以基于本次输出中的情绪分析、行为与决策分析、关注点/需求与自我理解分析。
- 建议必须服务于用户下次遇到类似情况时的具体行动。

建议类型：
- 表达方式建议。
- 降低不确定性的动作。
- 区分事实、情绪和解释。
- 边界保护。
- 推进事情的下一步小动作。
- 其他低成本、具体、可执行动作。

生成规则：
- 事件级建议只针对单个事件中能明确落地的动作。
- 日记级建议不必是事件级建议的合并，可以包含不归属于任何单个事件、但基于整篇日记整体分析得到的建议。
- 日记级建议可以来自某个关键事件、多个事件共同呈现的问题、当天整体情绪/行为/需求分析，或不适合归属到单个事件的整体调整动作。
- 每条建议使用"下次可以尝试…"、"建议…"表达。
- 不限制建议数量，但只输出有依据、可执行的建议，不为凑数量生成建议。
- 不输出泛泛而谈的鸡汤。
- 不输出高成本建议，例如辞职、分手、拉黑、放弃项目、重大关系决策。
- 只有 events 明确表达相关打算时，才允许涉及高成本建议。
- 如果某个事件没有明显可行动建议，该事件 action_suggestions 返回空数组。
- 如果整篇日记没有明显可行动建议，diary_action_suggestions 返回空数组。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "event_emotion_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "emotion_analyses": [
        "一条独立情绪分析文本"
      ]
    }
  ],
  "diary_emotion_analyses": [
    "一条独立日记级情绪总结文本"
  ],
  "event_behavior_decision_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "behavior_decision_analyses": [
        "一条独立行为与决策分析文本"
      ]
    }
  ],
  "diary_behavior_decision_analyses": [
    "一条独立日记级行为与决策总结文本"
  ],
  "event_self_understanding_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "self_understanding_analyses": [
        "一条独立关注点、需求与自我理解分析文本"
      ]
    }
  ],
  "diary_self_understanding_analyses": [
    "一条独立日记级关注点、需求与自我理解总结文本"
  ],
  "event_action_suggestions": [
    {
      "event_index": 0,
      "title": "事件标题",
      "action_suggestions": [
        "下次可以尝试……"
      ]
    }
  ],
  "diary_action_suggestions": [
    "下次可以尝试……"
  ]
}"""

COGNITION_ANALYSIS_PROMPT = """你是一个日记认知分析助手。请基于 events，按顺序完成认知校准、问题解答和认知完善。

## 任务目标
按以下顺序输出：
1. event_cognitive_calibration_analyses：事件级认知校准。
2. diary_cognitive_calibration_analyses：整篇日记的认知校准。
3. event_question_answers：事件级问题解答。
4. diary_question_answers：日记级问题解答。
5. event_cognitive_enhancements：事件级认知完善。
6. diary_cognitive_enhancements：日记级认知完善。

## 输入说明
events 是整理后的日记事件列表，是主要依据。
不要引用 events 之外的信息。

## 认知校准规则
1. 主要校准以下内容：
   - 事实与解释是否混淆。
   - 是否存在过度概括。
   - 是否存在绝对化判断。
   - 是否无依据判断别人动机。
   - 对知识、方法、因果关系的理解是否准确。
2. 允许直接指出判断不准确，但必须说明依据。
3. 事件级认知校准只分析该事件，不引用其他事件。
4. 日记级认知校准需要综合所有事件，识别整篇日记层面的理解偏差。
5. 可以引用事件标题和 events 中的具体事实，不引用原始文本。
6. 语气根据严重程度动态选择：事实错误可以直接指出；情绪中的判断要温和校准。
7. 如果某个事件没有明显需要校准的判断，该事件 cognitive_calibration_analyses 返回空数组。
8. 如果整篇日记没有明显需要校准的判断，diary_cognitive_calibration_analyses 返回空数组。
9. 不否定用户感受。
10. 不站在道德高地。
11. 依据不足时不强行纠错。
12. 不对专业知识胡乱纠正。
13. 不把认知校准写成行动建议。

## 问题解答规则
1. 先从 events 中找出问题，再回答问题。
2. 需要识别的问题包括：
   - 日记里明确提出的问题。
   - "我不知道……"这类隐性问题。
   - "这个有什么用"这类价值问题。
   - "这个该归到哪里"这类分类问题。
   - "这个到底好不好"这类判断问题。
3. 只输出 question 和 answer 两个字段。
4. answer 必须先给核心重点，不绕；复杂问题可以在 answer 内部简要拆解。
5. 可以使用模型已有的通用知识进行解释，但不能编造具体事实、数据、来源或确定性结论。
6. 没有可靠答案时，在 answer 中直接说明哪些部分无法可靠回答，不能装作确定。
7. 如果某个事件没有问题，该事件 question_answers 返回空数组。
8. 如果整篇日记没有日记级问题，diary_question_answers 返回空数组。

## 认知完善规则
1. 认知完善必须在问题解答之后进行。
2. 认知完善的输入包括：
   - events 中的零散知识。
   - events 中的随想、判断、类比和半成品观点。
   - 本环节生成的问题解答结果。
3. 认知完善的目标是把碎片想法转化为可复用的认知体系。
4. 认知完善应尽量整理出：
   - 核心概念。
   - 关键关系。
   - 因果链。
   - 适用边界。
   - 反例或限制。
   - 可以沉淀的知识点。
5. 可以使用模型已有的通用知识补全框架，但不能编造具体事实、数据、来源或确定性结论。
6. 不要先搭框架再反推问题答案，必须先问题解答，再认知完善。
7. 如果某个事件没有需要完善的认知，该事件 cognitive_enhancements 返回空数组。
8. 如果整篇日记没有需要完善的认知，diary_cognitive_enhancements 返回空数组。
9. 不输出行动建议。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "event_cognitive_calibration_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "cognitive_calibration_analyses": [
        "一条独立认知校准文本"
      ]
    }
  ],
  "diary_cognitive_calibration_analyses": [
    "一条独立日记级认知校准文本"
  ],
  "event_question_answers": [
    {
      "event_index": 0,
      "title": "事件标题",
      "question_answers": [
        {
          "question": "",
          "answer": ""
        }
      ]
    }
  ],
  "diary_question_answers": [
    {
      "question": "",
      "answer": ""
    }
  ],
  "event_cognitive_enhancements": [
    {
      "event_index": 0,
      "title": "事件标题",
      "cognitive_enhancements": [
        "一条独立认知完善文本"
      ]
    }
  ],
  "diary_cognitive_enhancements": [
    "一条独立日记级认知完善文本"
  ]
}"""


# ---------------------------------------------------------------------------
# 3 个 Node 异步函数
# ---------------------------------------------------------------------------

async def mood_tag_extract(state: AnalysisState) -> dict:
    """Node 1 (环节 7): 心情 + 标签提取 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "mood_tag_extracting")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]

    llm = _get_llm(0.3)
    result = await _invoke_llm(
        llm,
        MOOD_TAG_PROMPT,
        json.dumps(
            {"original_text": original_text, "structured_diary": structured_diary},
            ensure_ascii=False,
        ),
        step_name="mood_tag_extract",
    )

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

    return {"mood": mood, "event_tags": validated_event_tags}


async def core_analysis(state: AnalysisState) -> dict:
    """环节 8：核心分析 + 可行动建议"""
    task_id = state["task_id"]
    _update_step(task_id, "core_analyzing")

    events = state["structured_diary"].get("events", [])
    input_data = {"events": events}

    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        CORE_ANALYSIS_PROMPT,
        json.dumps(input_data, ensure_ascii=False),
        step_name="core_analysis",
    )

    # 提取并容错处理每个字段
    def safe_list(val):
        return val if isinstance(val, list) else []

    return {
        "event_emotion_analyses": safe_list(result.get("event_emotion_analyses")),
        "diary_emotion_analyses": safe_list(result.get("diary_emotion_analyses")),
        "event_behavior_decision_analyses": safe_list(result.get("event_behavior_decision_analyses")),
        "diary_behavior_decision_analyses": safe_list(result.get("diary_behavior_decision_analyses")),
        "event_self_understanding_analyses": safe_list(result.get("event_self_understanding_analyses")),
        "diary_self_understanding_analyses": safe_list(result.get("diary_self_understanding_analyses")),
        "event_action_suggestions": safe_list(result.get("event_action_suggestions")),
        "diary_action_suggestions": safe_list(result.get("diary_action_suggestions")),
    }


async def cognition_analysis(state: AnalysisState) -> dict:
    """环节 9：认知校准 + 问题解答 + 认知完善"""
    task_id = state["task_id"]
    _update_step(task_id, "cognition_analyzing")

    events = state["structured_diary"].get("events", [])
    input_data = {"events": events}

    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        COGNITION_ANALYSIS_PROMPT,
        json.dumps(input_data, ensure_ascii=False),
        step_name="cognition_analysis",
    )

    def safe_list(val):
        return val if isinstance(val, list) else []

    return {
        "event_cognitive_calibration_analyses": safe_list(result.get("event_cognitive_calibration_analyses")),
        "diary_cognitive_calibration_analyses": safe_list(result.get("diary_cognitive_calibration_analyses")),
        "event_question_answers": safe_list(result.get("event_question_answers")),
        "diary_question_answers": safe_list(result.get("diary_question_answers")),
        "event_cognitive_enhancements": safe_list(result.get("event_cognitive_enhancements")),
        "diary_cognitive_enhancements": safe_list(result.get("diary_cognitive_enhancements")),
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
        logger.info("标签落库完成: diary_id=%s, 标签数=%d", diary_id, len(all_tag_ids))
    except Exception as e:
        logger.error("标签落库失败: %s", e)
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 结果存储 + 状态更新
# ---------------------------------------------------------------------------

def _save_analysis_result(state: AnalysisState, diary_organized_id: str):
    """将分析结果存入数据库：日记级分析写入 diary_analysis 表，事件级分析写入 diary_events.analysis"""
    db = SessionLocal()
    try:
        task_id = state["task_id"]
        diary_id = state["diary_id"]

        org_uuid = uuid.UUID(diary_organized_id) if isinstance(diary_organized_id, str) else diary_organized_id
        diary_uuid = uuid.UUID(diary_id) if isinstance(diary_id, str) else diary_id

        # 辅助函数：JSON 序列化
        def to_json(val):
            if val is None:
                return None
            return json.dumps(val, ensure_ascii=False)

        # 辅助函数：从事件级数组中提取指定事件的分析
        def extract_event_analysis(event_array, event_idx, inner_key):
            """从事件级分析数组中提取指定事件的分析数据"""
            if not isinstance(event_array, list):
                return []
            for item in event_array:
                if isinstance(item, dict) and item.get("event_index") == event_idx:
                    return item.get(inner_key, [])
            return []

        # 先删除该 diary_organized 的旧分析记录（重新分析场景）
        db.query(DiaryAnalysis).filter(
            DiaryAnalysis.diary_organized_id == org_uuid
        ).delete()

        # 1. 保存日记级分析
        analysis = DiaryAnalysis(
            task_id=uuid.UUID(task_id) if isinstance(task_id, str) else task_id,
            diary_organized_id=org_uuid,
            mood=state.get("mood", ""),
            emotion_analyses=to_json(state.get("diary_emotion_analyses", [])),
            behavior_decision_analyses=to_json(state.get("diary_behavior_decision_analyses", [])),
            self_understanding_analyses=to_json(state.get("diary_self_understanding_analyses", [])),
            action_suggestions=to_json(state.get("diary_action_suggestions", [])),
            cognitive_calibration_analyses=to_json(state.get("diary_cognitive_calibration_analyses", [])),
            question_answers=to_json(state.get("diary_question_answers", [])),
            cognitive_enhancements=to_json(state.get("diary_cognitive_enhancements", [])),
            analyzed_at=datetime.now(),
        )
        db.add(analysis)

        # 2. 保存事件级分析
        event_records = db.query(DiaryEvent).filter(
            DiaryEvent.diary_organized_id == org_uuid
        ).order_by(DiaryEvent.sort_order).all()

        for idx, event_record in enumerate(event_records):
            event_analysis = {
                "emotion_analyses": extract_event_analysis(state.get("event_emotion_analyses", []), idx, "emotion_analyses"),
                "behavior_decision_analyses": extract_event_analysis(state.get("event_behavior_decision_analyses", []), idx, "behavior_decision_analyses"),
                "self_understanding_analyses": extract_event_analysis(state.get("event_self_understanding_analyses", []), idx, "self_understanding_analyses"),
                "action_suggestions": extract_event_analysis(state.get("event_action_suggestions", []), idx, "action_suggestions"),
                "cognitive_calibration_analyses": extract_event_analysis(state.get("event_cognitive_calibration_analyses", []), idx, "cognitive_calibration_analyses"),
                "question_answers": extract_event_analysis(state.get("event_question_answers", []), idx, "question_answers"),
                "cognitive_enhancements": extract_event_analysis(state.get("event_cognitive_enhancements", []), idx, "cognitive_enhancements"),
            }
            event_record.analysis = json.dumps(event_analysis, ensure_ascii=False)

        # 更新日记状态为 analyzed
        diary = db.query(Diary).filter(Diary.id == diary_uuid).first()
        if diary:
            diary.status = DiaryStatus.analyzed

        db.commit()
        logger.info("分析结果已保存: diary_id=%s, task_id=%s", diary_id, task_id)
    except Exception as e:
        logger.error("保存分析结果失败: %s", e)
        db.rollback()
        raise
    finally:
        db.close()


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
) -> dict:
    """构建并执行 LangGraph 分析流水线（3 环节并行）"""
    builder = StateGraph(AnalysisState)
    builder.add_node("mood_tag_extract", mood_tag_extract)
    builder.add_node("core_analysis", core_analysis)
    builder.add_node("cognition_analysis", cognition_analysis)

    # fan-out: START 并行分叉到 3 个节点
    builder.add_edge(START, "mood_tag_extract")
    builder.add_edge(START, "core_analysis")
    builder.add_edge(START, "cognition_analysis")
    # fan-in: 3 个节点全部完成后汇聚到 END
    builder.add_edge("mood_tag_extract", END)
    builder.add_edge("core_analysis", END)
    builder.add_edge("cognition_analysis", END)

    # 配置 checkpointer（支持断点续跑）
    async with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": task_id}}
        result = await graph.ainvoke(
            {
                "original_text": original_text,
                "structured_diary": structured_diary,
                "task_id": task_id,
                "diary_id": diary_id,
                "user_id": user_id,
                "diary_organized_id": diary_organized_id,
            },
            config=config,
        )

    # 清理 checkpoint
    await cleanup_checkpoint(task_id)

    # 提取结果
    analysis_result = {
        "mood": result.get("mood", ""),
        "event_tags": result.get("event_tags", []),
        "event_emotion_analyses": result.get("event_emotion_analyses", []),
        "diary_emotion_analyses": result.get("diary_emotion_analyses", []),
        "event_behavior_decision_analyses": result.get("event_behavior_decision_analyses", []),
        "diary_behavior_decision_analyses": result.get("diary_behavior_decision_analyses", []),
        "event_self_understanding_analyses": result.get("event_self_understanding_analyses", []),
        "diary_self_understanding_analyses": result.get("diary_self_understanding_analyses", []),
        "event_action_suggestions": result.get("event_action_suggestions", []),
        "diary_action_suggestions": result.get("diary_action_suggestions", []),
        "event_cognitive_calibration_analyses": result.get("event_cognitive_calibration_analyses", []),
        "diary_cognitive_calibration_analyses": result.get("diary_cognitive_calibration_analyses", []),
        "event_question_answers": result.get("event_question_answers", []),
        "diary_question_answers": result.get("diary_question_answers", []),
        "event_cognitive_enhancements": result.get("event_cognitive_enhancements", []),
        "diary_cognitive_enhancements": result.get("diary_cognitive_enhancements", []),
    }

    # 标签落库
    try:
        _persist_tags(user_id, diary_id, diary_organized_id, analysis_result["event_tags"])
    except Exception as e:
        logger.error("标签落库异常（不影响分析结果返回）: %s", e)

    # 保存分析结果 + 更新日记状态
    _save_analysis_result(result, diary_organized_id)

    return analysis_result
