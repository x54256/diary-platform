"""LangGraph 分析流水线 - 3 环节 + 独立检查 + 标签落库"""

import json
import logging
import uuid
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
    # 输入
    original_text: str
    structured_diary: dict
    task_id: str
    diary_id: str
    user_id: str
    diary_organized_id: str

    # 环节 7 产物：心情 + 标签提取
    mood: str
    event_tags: list

    # 环节 8 产物：核心分析
    emotion_analysis: str
    behavior_analysis: str
    focus_analysis: str

    # 环节 9 产物：校准与建议
    cognitive_calibration: str
    actionable_suggestions: str

    # 检查环节产物
    analysis_check_log: list

    # 进度追踪
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

CORE_ANALYSIS_PROMPT = """你是一个日记分析助手。请根据结构化日记和原始文本，进行描述性和解释性分析。

## 任务目标
基于当天日记内容，输出三部分分析：
1. 情绪分析 emotion_analysis
2. 行为与决策分析 behavior_analysis
3. 关注点、需求与自我理解 focus_analysis

## 输入说明
structured_diary 是整理后的结构化日记，是主要依据。
original_text 是原始日记文本，仅用于核对事实。不要从 original_text 中挖掘 structured_diary 已经剔除的语言噪音。

## 核心边界
1. 只分析当天这篇日记，不引用当天以外的信息。
2. 不做长期人格判断、心理诊断、贴标签。
3. 较强推断必须写依据，依据来自当天结构化日记中的具体事件或事实。
4. 只做描述性和解释性分析，不做评判。
5. 不把推导写成绝对事实。

## 情绪分析 emotion_analysis
分析用户在当天事件中的主要情绪、情绪变化路径和触发点。
- 描述主要情绪及其变化。
- 描述触发情绪变化的具体事实。
- 情绪背后反映了什么被触动。
- 不用百分比量化，不做心理诊断，不把短期情绪说成长期状态。
- 不写"你是一个情绪化的人"。

## 行为与决策分析 behavior_analysis
分析用户当天面对事件时采取了什么行动、做了什么选择，以及体现出的当天应对方式。
- 描述具体行为和选择。
- 分析应对方式：主动推进、等待观察、寻求外部帮助，还是回避处理。
- 行为带来了什么结果或影响。
- 不上升为长期人格，不写"你一直都是……"，不贴标签。
- 不脱离当天事实分析行为模式。

## 关注点、需求与自我理解 focus_analysis
分析用户当天真正被什么牵动，以及背后反映出的当下需求、期待、边界感、自我叙事和价值排序。
- 用户真正关注的是什么。
- 用户当下想要什么、害怕或抗拒什么。
- 用户正在维护什么。
- 用户对事件形成了什么理解。
- 这件事反映出用户看重什么。
- 不做心理诊断，不写长期人格结论，不写"你缺乏安全感""你很依赖认可"等诊断式表达。
- 不替用户扩展到原文没有支撑的人生经历。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "emotion_analysis": "情绪分析文本",
  "behavior_analysis": "行为与决策分析文本",
  "focus_analysis": "关注点、需求与自我理解分析文本"
}"""

CALIBRATION_PROMPT = """你是一个日记分析助手。请基于结构化日记、原始文本和核心分析结果，进行认知校准并给出可行动建议。

## 任务目标
1. 认知校准 cognitive_calibration：识别明显认知偏差并温和纠正。
2. 可行动建议 actionable_suggestions：给出 1-3 条低成本、具体、可执行的建议。

## 输入说明
structured_diary 是整理后的结构化日记，是主要依据。
original_text 是原始日记文本，仅用于核对事实。不要从 original_text 中挖掘 structured_diary 已经剔除的语言噪音。
analysis_result 是环节 8 的核心分析结果，是认知校准和可行动建议的直接依据。

## 认知校准规则
1. 识别用户对世界、他人、自己、事件因果的理解中是否存在过度概括、绝对化、事实支撑不足等问题。
2. 区分情绪表达和事实可支持的结论。
3. 对知识点、方法论的错误理解，如果有足够把握，可以直接指出并补充更准确理解。
4. 信息不足时写"原文不足以判断该理解是否准确"。
5. 不否定用户感受。
6. 不站在道德高地。
7. 依据不足时不强行纠错。
8. 不对专业知识胡乱纠正。
9. 不把认知校准写成行动建议。

## 可行动建议规则
1. 给出 1-3 条建议。
2. 建议必须低成本、具体、可执行。
3. 使用"下次可以尝试……"这类建议式表达。
4. 不使用"你应该……"这类命令式表达。
5. 不输出空泛建议（鸡汤式表达）。
6. 不输出高成本建议（如辞职、结束关系等重大决策），除非原文明确表达相关打算。
7. 建议服务于下一次遇到类似情况时的具体行动。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "cognitive_calibration": "认知校准文本",
  "actionable_suggestions": "可行动建议文本"
}"""

ANALYSIS_CHECK_PROMPT = """你是一个日记分析审核助手。请对照原始日记和结构化日记，审核分析结果（环节 7/8/9 的全部产出），发现问题直接修正。

## 任务目标
对以下分析结果进行 8 项检查，发现问题直接输出修正版，修正后不重新检查。

## 输入说明
original_text 是原始日记文本。
structured_diary 是整理后的结构化日记。
analysis_result 包含环节 7/8/9 的全部产出：mood、event_tags、emotion_analysis、behavior_analysis、focus_analysis、cognitive_calibration、actionable_suggestions。

## 检查项
1. 是否引用了当天日记以外的信息（如历史日记、其他日期事件）。
2. 是否做了长期人格判断或贴标签（如"你是一个…的人""你总是…"）。
3. 较强推断是否缺少依据（推断必须写明依据来自哪个具体事件或事实）。
4. 认知校准是否否定了用户感受（如"你不应该感到…"、"这种感受不合理"）。
5. 认知校准是否在依据不足时强行纠错（原文信息不足时应标注"不足以判断"而非强行纠正）。
6. 可行动建议是否具体、低成本、可执行（不能是空泛鸡汤或高成本建议）。
7. 是否出现命令式表达（如"你应该…""你必须…"）。
8. 是否出现空泛建议（如"学会放下""接受自己""多沟通"等无具体行动的表述）。

## 修正规则
1. 发现问题时直接输出修正后的对应字段内容。
2. 没有问题的字段原样输出。
3. 每个检查项记录检查结果：通过则 status 为"通过"，发现问题并修正则 status 为"已修正"。
4. 只做一轮检查，修正后不重新检查。

## 输出要求
请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：

{
  "emotion_analysis": "修正后的情绪分析（或原样）",
  "behavior_analysis": "修正后的行为分析（或原样）",
  "focus_analysis": "修正后的关注点分析（或原样）",
  "cognitive_calibration": "修正后的认知校准（或原样）",
  "actionable_suggestions": "修正后的建议（或原样）",
  "analysis_check_log": [
    {
      "check_item": "检查项名称",
      "status": "通过/已修正",
      "issue": "问题描述，通过时为空字符串",
      "fix": "修正说明，通过时为空字符串"
    }
  ]
}

analysis_check_log 必须包含全部 8 个检查项。"""


# ---------------------------------------------------------------------------
# 4 个 Node 异步函数
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
    """Node 2 (环节 8): 核心分析 (temp=0.5)"""
    task_id = state["task_id"]
    _update_step(task_id, "core_analyzing")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]

    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        CORE_ANALYSIS_PROMPT,
        json.dumps(
            {"original_text": original_text, "structured_diary": structured_diary},
            ensure_ascii=False,
        ),
        step_name="core_analysis",
    )

    return {
        "emotion_analysis": result.get("emotion_analysis", "") or "",
        "behavior_analysis": result.get("behavior_analysis", "") or "",
        "focus_analysis": result.get("focus_analysis", "") or "",
    }


async def calibration_suggest(state: AnalysisState) -> dict:
    """Node 3 (环节 9): 校准与建议 (temp=0.5)"""
    task_id = state["task_id"]
    _update_step(task_id, "calibrating")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]
    analysis_result = {
        "emotion_analysis": state["emotion_analysis"],
        "behavior_analysis": state["behavior_analysis"],
        "focus_analysis": state["focus_analysis"],
    }

    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        CALIBRATION_PROMPT,
        json.dumps(
            {
                "original_text": original_text,
                "structured_diary": structured_diary,
                "analysis_result": analysis_result,
            },
            ensure_ascii=False,
        ),
        step_name="calibration_suggest",
    )

    return {
        "cognitive_calibration": result.get("cognitive_calibration", "") or "",
        "actionable_suggestions": result.get("actionable_suggestions", "") or "",
    }


async def analysis_check(state: AnalysisState) -> dict:
    """Node 4 (检查): 分析内部检查 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "analysis_checking")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]
    analysis_result = {
        "mood": state["mood"],
        "event_tags": state["event_tags"],
        "emotion_analysis": state["emotion_analysis"],
        "behavior_analysis": state["behavior_analysis"],
        "focus_analysis": state["focus_analysis"],
        "cognitive_calibration": state["cognitive_calibration"],
        "actionable_suggestions": state["actionable_suggestions"],
    }

    llm = _get_llm(0.3)
    result = await _invoke_llm(
        llm,
        ANALYSIS_CHECK_PROMPT,
        json.dumps(
            {
                "original_text": original_text,
                "structured_diary": structured_diary,
                "analysis_result": analysis_result,
            },
            ensure_ascii=False,
        ),
        step_name="analysis_check",
    )

    analysis_check_log = result.get("analysis_check_log", [])
    if not isinstance(analysis_check_log, list):
        analysis_check_log = []

    # 用修正值覆盖 state 中的对应字段
    return {
        "emotion_analysis": result.get("emotion_analysis", state["emotion_analysis"]) or "",
        "behavior_analysis": result.get("behavior_analysis", state["behavior_analysis"]) or "",
        "focus_analysis": result.get("focus_analysis", state["focus_analysis"]) or "",
        "cognitive_calibration": result.get("cognitive_calibration", state["cognitive_calibration"]) or "",
        "actionable_suggestions": result.get("actionable_suggestions", state["actionable_suggestions"]) or "",
        "analysis_check_log": analysis_check_log,
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

                    # 创建事件-标签关联
                    if event_id:
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

def _save_analysis_result(
    task_id: str,
    diary_organized_id: str,
    diary_id: str,
    result: dict,
):
    """将分析结果存入 diary_analysis 表，并更新日记状态为 analyzed"""
    db = SessionLocal()
    try:
        org_uuid = uuid.UUID(diary_organized_id) if isinstance(diary_organized_id, str) else diary_organized_id
        diary_uuid = uuid.UUID(diary_id) if isinstance(diary_id, str) else diary_id

        # 先删除该 diary_organized 的旧分析记录（重新分析场景）
        db.query(DiaryAnalysis).filter(
            DiaryAnalysis.diary_organized_id == org_uuid
        ).delete()

        analysis = DiaryAnalysis(
            task_id=uuid.UUID(task_id) if isinstance(task_id, str) else task_id,
            diary_organized_id=org_uuid,
            mood=result.get("mood", ""),
            emotion_analysis=result.get("emotion_analysis", ""),
            behavior_analysis=result.get("behavior_analysis", ""),
            focus_analysis=result.get("focus_analysis", ""),
            cognitive_calibration=result.get("cognitive_calibration", ""),
            actionable_suggestions=result.get("actionable_suggestions", ""),
        )
        db.add(analysis)

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
    """构建并执行 LangGraph 分析流水线（3 环节 + 检查）"""
    builder = StateGraph(AnalysisState)
    builder.add_node("mood_tag_extract", mood_tag_extract)
    builder.add_node("core_analysis", core_analysis)
    builder.add_node("calibration_suggest", calibration_suggest)
    builder.add_node("analysis_check", analysis_check)

    builder.add_edge(START, "mood_tag_extract")
    builder.add_edge("mood_tag_extract", "core_analysis")
    builder.add_edge("core_analysis", "calibration_suggest")
    builder.add_edge("calibration_suggest", "analysis_check")
    builder.add_edge("analysis_check", END)

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
        "emotion_analysis": result.get("emotion_analysis", ""),
        "behavior_analysis": result.get("behavior_analysis", ""),
        "focus_analysis": result.get("focus_analysis", ""),
        "cognitive_calibration": result.get("cognitive_calibration", ""),
        "actionable_suggestions": result.get("actionable_suggestions", ""),
        "analysis_check_log": result.get("analysis_check_log", []),
    }

    # 标签落库
    try:
        _persist_tags(user_id, diary_id, diary_organized_id, analysis_result["event_tags"])
    except Exception as e:
        logger.error("标签落库异常（不影响分析结果返回）: %s", e)

    # 保存分析结果 + 更新日记状态
    _save_analysis_result(task_id, diary_organized_id, diary_id, analysis_result)

    return analysis_result
