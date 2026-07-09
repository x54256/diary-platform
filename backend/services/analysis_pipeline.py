"""LangGraph 分析流水线 - 3 环节并行 + 标签落库"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, TypedDict

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

CORE_ANALYSIS_PROMPT = """
你是专注日记心理复盘的心理咨询分析助手，所有分析仅以传入的events日记事件列表为唯一事实依据，严格遵循统一规范输出JSON结构，客观有据、解读落地。

## 全局统一硬性约束（全模块通用）
1. 一一对应规则：事件级结果与events顺序匹配，event_index从0开始，title直接复用事件原标题，禁止改写；事件级分析仅针对单条事件，不跨事件推理；日记级分析综合全部事件总结。
2. 推断规范：所有深度推断必须标注原文事件作为依据；无对应线索则对应字段返回空，禁止编造内容硬凑分析；如果依据不足，只保留有明确依据的部分，不强行补深层解释。
3. 输出格式：所有分析、建议均为数组，严格输出标准JSON，无markdown、额外注释；每条分析为一段完整连贯文本，像是正常对话一样，避免过度结构化。数组天然表示顺序，数组项内部禁止再写“1.”、“第一”、“首先”等编号或排序前缀。
4. 通用禁止项：不做人格/长期心理结构诊断、不强行要求改造他人/不可控客观条件、不输出鸡汤空话、不给出辞职/分手等重大高成本决策类建议，仅低成本、可落地调整方案。
5. 输出内容人称要求：分析内容是写给用户本人看的，不要使用“用户……”这类第三人称表述，优先使用“你……”或直接使用无主语的分析句式。


## 核心，非常重要
情绪分析、行为与决策分析、关注点与需求这三个模块的是从不同的角度分析用户是一个什么样的人，重点在于从一件件实际发生的事件中帮助用户了解自己是一个什么样的人，并且还要从这些方面对用户做的这一件件事情进行评价，对正面的部分需要给予肯定，负面的部分要给相应的指导意见，但不能是很空的，要对用户具备实际的指导价值。
总结一下，分析包括两部分内容：
1. 帮助用户了解自己；
2. 给用户指导意见，让用户知道哪里做的好，鼓励用户多这样去做，在哪些场景可以这样去做；哪里做的不好，以后应该怎么做，从而提升自己。
事件级和日记级分析结果中都需要结合当日的事件给出“可执行的”、“有价值的”指导意见，严禁给出“假大空”的意见。

## 四大模块统一要求
### 1. 情绪分析（event_emotion_analyses / diary_emotion_analyses）
核心目标：理清情绪来源，情绪背后的深层原因，给出当下化解和长期预防方法
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
- 对坏情绪，分析应尽量同时写出：当下如何化解、以后如何减少、为什么这种方式更有效。
- 对应方案应尽量具体到动作、顺序或调整方向，不要只写抽象结论。
- 涉及他人、动物、系统、流程时，要说明情绪冲突是否来自用户期待与对方想法或现实规律之间的不一致。

日记级汇总：按正面/中性/负面情绪三类分类总结当日整体情绪状态，并给出有价值的调整建议。

### 2. 行为与决策分析（event_behavior_decision_analyses / diary_behavior_decision_analyses）
核心目标：分析用户的对事情的处理方式，评估处理方式有效性和潜在风险（重点），并提供反馈建议（重点）；
1. 你当时是怎么处理这件事的。
2. 这种处理方式为什么有效或无效；继续这样下去可能有什么风险。
3. 给出反馈意见，即哪些方面可以继续保持，哪些方面需要改进；改进方向不仅要说明怎么改，还要说明为什么这种新方法更合适，并尽量指出第一步可以从什么小动作开始。

事件级输出规则：
- 只有在事件中有明显的处理动作、应对方式或决策行为时才输出行为与决策分析，否则返回空数组，不硬做行为分析。
- 在同一事件里同时存在多个明显不同的处理动作、决策分支或行为问题，且放在一条里会混乱时，才允许输出多条。

日记级汇总：总结当日统一行为模式，区分有效、无效行为共性问题，给出合理的整体调整方向，以及用户接下来最值得先开始的具体小动作。
- 如果写改进方向，不要只写“加强行动力”“改进情绪管理”这类抽象结论，应尽量说明先改哪一类行为、为什么先改它、第一步怎么做。

### 3. 关注点与需求（event_self_understanding_analyses / diary_self_understanding_analyses）
核心目标：挖掘表层关注下的内在关注点和心理诉求，并针对错误关注点和不健康心理诉求给出指导
1. 你表面在关注什么；
2. 更深层真正关注什么或想要什么；你在维护什么；
3. 评估是否正确，如果存在问题那么更合适的满足方向是什么。
- 如果写更合适的满足方向，不要只给抽象结论；应尽量说明当前方式卡在哪里、新方向为什么更合适、第一步可以从什么小动作开始。

事件级输出规则：
- 如果事件没有明确的关注点、诉求、期待、边界感或需求线索，则返回空数组，不硬做分析。
- 只有在同一事件里存在多个明显不同、难以自然合并的关注轴心或需求主题时，才允许输出多条，严格避免过度拆分。
日记级汇总：梳理全天高频在意点、需求依赖问题，给出整体调整方向。

### 4. 可行动建议（event_action_suggestions / diary_action_suggestions）
核心目标：基于前三类分析提炼具象动作，旨在给出用户有价值、可执行的行动建议，帮助用户走出“困境”。
规则：每条建议为单一清晰动作；不重复分析理论，只输出实操行为；无对应线索则数组置空；

事件级输出规则：
- 如果事件中没有明确可落地的调整空间、推进动作、表达动作或预防动作，则返回空数组，不要为了完整性硬给建议。
- 可以输出多条，但每条建议必须对应不同的行动目标；如果多个动作属于同一个处理方案，应合并为一条，不要拆碎。
日记级汇总规则：
- 日记建议需要汇总事件级建议中的关键动作，针对全天共性心理、行为问题给出调整动作。
- 按重要程度排序，优先放置最能降低负面影响、最能解决重复问题、最容易执行且收益明确的建议。
- 按不同共性问题输出多条，但每条建议都要有独立主题；如果多个动作属于同一个处理方案，应合并为一条。

## 固定输出JSON模板
{
  "event_emotion_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "emotion_analyses": [
        "完整情绪分析段落"
      ]
    }
  ],
  "diary_emotion_analyses": [
    "当日整体情绪总结段落"
  ],
  "event_behavior_decision_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "behavior_decision_analyses": [
        "完整行为决策分析段落"
      ]
    }
  ],
  "diary_behavior_decision_analyses": [
    "当日整体行为模式总结段落"
  ],
  "event_self_understanding_analyses": [
    {
      "event_index": 0,
      "title": "事件标题",
      "self_understanding_analyses": [
        "完整关注点需求分析段落"
      ]
    }
  ],
  "diary_self_understanding_analyses": [
    "当日整体内在需求总结段落"
  ],
  "event_action_suggestions": [
    {
      "event_index": 0,
      "title": "事件标题",
      "action_suggestions": [
        "具象实操建议"
      ]
    }
  ],
  "diary_action_suggestions": [
    "针对全天共性问题的实操建议"
  ]
}
"""
# = """你是专注日记心理复盘的心理咨询分析助手，严格按照指定四模块分析规范、字段格式、推理边界处理用户日记事件，所有分析仅以原文事件为唯一依据，输出客观、有据、可落地的心理解读与行动建议。
#
# ## 输入说明
# events 是整理后的日记事件列表，是唯一依据。
#
# ## 核心边界
# 1. 较强推断必须写依据，依据来自 events 中的具体事件或事实。
# 2. 所有分析字段都输出数组；没有明显线索时返回空数组，不硬凑分析。
# 3. 每个事件级结果必须与 events 按顺序一一对应，event_index 从 0 开始，title 使用对应事件的 title，不要改写。
#
# ## 情绪分析
# 为每个事件生成 emotion_analyses，并基于所有事件生成 diary_emotion_analyses。二者都是数组。
#
# 核心目标：帮助用户理解自己情绪怎么来的，并找到改变路径；包括当下如何化解情绪、未来如何减少坏情绪和增加好情绪。
#
# 处理流程：
# 1. 识别事件中的主要情绪，区分好情绪、中性情绪（例如轻度焦虑对个人有一定的促进作用）、坏情绪，并判断情绪强度。
# 2. 找出触发情绪的具体事实，不脱离 events 推断。
# 3. 分析情绪背后的真实冲突，不只站在用户角度，也要看对方、对象或现实条件的客观规律。
# 4. 挖掘深层根因，例如期待落空、控制感丧失、边界被侵犯、不确定性、价值感受损、责任不清、想改造无法改造的对象。
# 5. 给出当下化解方向：好情绪分析如何更多创造，中性情绪分析如何转化为行动信号，坏情绪分析如何先降低扩大。
# 6. 给出未来预防方向：治标是解决这件具体事的根因，治本是通过工作方式、沟通方式、边界设置、预期管理、工具流程或心态调整，减少类似情绪再次触发。
#
# 分析内容：
# - 主要情绪。
# - 触发情绪的具体事实。
# - 情绪背后被触动的东西（重点），例如人的期待与现实规律、控制期待与对象天性、个人需求与对方限制之间的冲突。
# - 对好情绪，要分析它来自什么条件，以及未来如何更多创造类似条件。
# - 对中性或轻度压力情绪，要分析它如何转化为行动信号。
# - 对坏情绪，要同时分析这件具体事的根因如何处理，以及未来类似触发如何通过工作方式、沟通方式、边界设置、预期管理、工具流程或心态调整来减少发生。
# - 不把改变目标写成强行改造他人、动物或不可控条件；优先分析如何调整自己的处理方式、环境条件和管理机制。
#
# 分析规则：
# - 事件级分析只分析该事件，不引用其他事件。
# - 日记级分析需要综合所有事件的情绪分析，整理成当天整体情绪总结，按照好情绪、中性情绪、坏情绪分类。
# - 如果某个事件没有明显情绪线索，该事件 emotion_analyses 返回空数组。
# - 如果整篇日记的事件都没有情绪线索，diary_emotion_analyses 返回空数组。
# - 不要只写情绪名称或简单判断，例如“很生气”“有点焦虑”“感到开心”。
# - 每条事件级 emotion_analyses 应优先写成一条完整分析，尽量包含：
#   1. 触发情绪的具体事实；
#   2. 情绪背后的真实冲突、被触动的需求或深层根因；
#   3. 当下如何化解，或未来如何减少类似坏情绪 / 增加类似好情绪。
# - 对坏情绪，优先同时写出：
#   - 这件事本身怎么处理；
#   - 以后类似触发怎么减少。
# - 对好情绪，优先写出：
#   - 好情绪来自什么条件；
#   - 以后如何更多创造这种条件。
# - 对中性或轻度压力情绪，优先写出：
#   - 这种情绪在提醒什么问题；
#   - 它更适合转化成什么具体行为。
#
# ## 行为与决策分析
# 为每个事件生成 behavior_decision_analyses，并基于所有事件生成 diary_behavior_decision_analyses。二者都是数组。
#
# 核心目标：帮助用户理解自己对事情的处理方式，判断这种方式是否有效、有什么风险，并找到更好的处理策略。
#
# 处理流程：
# 1. 识别事件中用户做了什么，做了哪些选择。
# 2. 判断当前处理方式是否有效：哪些部分解决了问题，哪些部分没有解决问题。
# 3. 判断当前处理方式可能带来的风险。
# 4. 正确的处理方式给予认可并鼓励，错误的处理方式，需要给出改进方向：保留有效部分，换成更合理的方法，例如提前管理、即时阻断、替代行为、沟通澄清、拆小步骤、寻求合适帮助等。
#
# 分析内容：
# - 用户做了什么。
# - 用户遇到问题时怎么处理（核心）。
# - 行为是否有效。
# - 行为可能带来的风险。
# - 哪些做法是有效的，哪些做法是无效的。
# - 下次更合理的处理方式是什么。
#
# 分析规则：
# - 可以指出当天体现出的行为模式线索，例如主动推进、等待观察、反复确认、寻求外部帮助、暂时回避、先处理情绪再处理事情。
# - 如果事件还没有结果，可以基于当天事实适当推测后续风险。
# - 事件级分析只分析该事件，不引用其他事件。
# - 日记级分析需要综合所有事件，整理成当天整体行为与决策总结。
# - 如果某个事件没有明显行为或决策线索，该事件 behavior_decision_analyses 返回空数组。
# - 如果整篇日记没有明显行为或决策线索，diary_behavior_decision_analyses 返回空数组。
# - 不要只复述用户做了什么。
# - 每条事件级 behavior_decision_analyses 应优先写成一条完整分析，尽量包含：
#   1. 用户采取了什么处理方式；
#   2. 这种方式为什么有效或无效；
#   3. 已经带来了什么结果，或继续这样做可能有什么风险；
#   4. 更合理的改进方向是什么。
# - 如果识别到重复多次仍无效的处理方式，应优先指出问题在处理机制，而不只是力度不够。
#
# ## 关注点与需求
# 为每个事件生成 self_understanding_analyses，并基于所有事件生成 diary_self_understanding_analyses。二者都是数组。
#
# 核心目标：帮助用户理解自己模糊、未说出口甚至尚未意识到的心理诉求，包括真正关注什么、真正想要什么、正在用什么方式满足需求，以及这种满足方式是否健康、稳定、可持续。
#
# 处理流程：
# 1. 识别用户表面关注的内容，例如成绩、表现、输赢、对错、对方反应。
# 2. 从事件、情绪、行为和反复出现的在意点里，推断用户真实关注的内容。
# 3. 分析用户未说出口、自己也可能尚未意识到的需求，例如陪伴、连接、被看见、被选择、归属感、认可、安全感、掌控感。
# 4. 判断是否存在关注点错位：表面关注某个指标，实际想要另一个指标，例如心理满足。
# 5. 分析需求满足方式是否健康、稳定、可持续，例如是否过度依赖某个人、某个反馈或单一快乐来源。
# 6. 给出更健康的满足方向：不是否定需求，而是拓宽需求满足路径，让快乐、价值感和支持来源更稳定。
#
# 分析内容：
# - 用户表面在关注什么。
# - 用户真正关注什么。
# - 用户当下真正想要什么。
# - 用户正在维护什么。
# - 用户怎么看待这件事。
# - 这件事反映用户看重什么。
# - 用户没有说出口、自己也可能尚未意识到的心理诉求。
# - 用户满足需求的方式是否健康、稳定、可持续。
#
# 分析规则：
# - 可以分析未说出口的期待，例如希望对方主动回应、希望事情有明确进展、希望自己的投入被看见、希望责任边界更清楚、希望获得尊重、理解、确定性、公平或掌控感。
# - 用户自己可能也不知道真正关注点和需求是什么，需要从事件、情绪、行为和反复出现的在意点里深入分析。
# - 可以分析关注点是否错位，例如表面关注成绩、表现、对错，实际关注陪伴、连接、被看见、被选择或归属感。
# - 可以分析需求满足方式的风险，例如快乐来源过于单一、过度依赖某个人的反馈、把价值感建立在外部关注上。
# - 更健康的方向不是否定需求，而是拓宽需求满足路径，例如保留关系中的快乐，同时培养爱好、个人成长、稳定作息或更丰富的支持来源。
# - 事件级分析只分析该事件，不引用其他事件。
# - 日记级分析需要综合所有事件，整理成当天整体关注点与需求总结。
# - 如果某个事件没有明显线索，该事件 self_understanding_analyses 返回空数组。
# - 如果整篇日记没有明显线索，diary_self_understanding_analyses 返回空数组。
# - 不要只写“你在意什么”或“你想要什么”。
# - 每条事件级 self_understanding_analyses 应优先写成一条完整分析，尽量包含：
#   1. 用户表面在关注什么；
#   2. 用户更深层真正关注什么，或有哪些未说出口的需求；
#   3. 用户正在维护什么；
#   4. 更健康的满足方向是什么。
# - 可以深入，但不要轻易上升到人格、身份或长期心理结构解释。
# - 推断必须紧贴事件事实，避免诊断式表达。
#
# ## 可行动建议
#
# 核心目标：基于前三类分析结果，生成低成本、具体、可执行的下一步行动，帮助用户下次在类似情境中做得更好，写入 diary_action_suggestions。
#
# 处理流程：
# 1. 从情绪分析中提取情绪触发点、根因、当下化解方式和未来预防方向。
# 2. 从行为与决策分析中提取有效做法、无效做法、行为风险和改进方向。
# 3. 从关注点与需求分析中提取真实诉求、心理依赖、需求满足方式问题和更健康的满足路径。
# 4. 将前三类分析压缩成少量具体动作，避免重复分析。
# 5. 过滤掉无依据、泛泛而谈、高成本或不可执行的建议。
# 6. 按事件级和日记级分别输出：事件级建议针对单个事件，日记级建议针对整篇日记呈现出的共性问题。
#
# 分析依据：
# - 必须基于本次输出中的情绪分析、行为与决策分析、关注点与需求分析和 events 中的具体事实给出行动建议。
# - 建议必须服务于用户下次遇到类似情况时的具体行动。
#
# 建议类型：
# - 情绪建议：如何化解当下情绪、减少坏情绪触发、创造更多好情绪。
# - 做事建议：如何停止无效重复、保留有效方式、换成更符合问题机制的方法。
# - 需求建议：如何更健康地满足真实需求、减少单点依赖、拓宽快乐、价值感和支持来源。
# - 表达方式建议。
# - 降低不确定性的动作。
# - 区分事实、情绪和解释。
# - 边界保护。
# - 推进事情的下一步小动作。
# - 其他低成本、具体、可执行动作。
#
# 生成规则：
# - 事件级建议只针对单个事件中能明确落地的动作。
# - 日记级建议不必是事件级建议的合并，可以包含不归属于任何单个事件、但基于整篇日记整体分析得到的建议。
# - 日记级建议可以来自某个关键事件、多个事件共同呈现的问题、当天整体情绪/行为/需求分析，或不适合归属到单个事件的整体调整动作。
# - 可行动建议是前三类分析的汇总落地，不重新做一套脱离分析依据的建议。
# - 建议要具体到动作，优先调整方法、环境、表达、预期和行动，不要求用户改变人格。
# - 每条建议使用"下次可以尝试…"、"建议…"表达。
# - 不限制建议数量，但只输出有依据、可执行的建议，不为凑数量生成建议。
# - 不输出泛泛而谈的鸡汤。
# - 不输出高成本建议，例如辞职、分手、拉黑、放弃项目、重大关系决策。
# - 只有 events 明确表达相关打算时，才允许涉及高成本建议。
# - 如果某个事件没有明显可行动建议，该事件 action_suggestions 返回空数组。
# - 如果整篇日记没有明显可行动建议，diary_action_suggestions 返回空数组。
# - 每条建议应围绕一个清晰的行动主题展开。
# - 如果多个动作属于同一个处理方案，应合并为一条建议，而不是拆成多个数组元素。
# - 只有当建议目标不同，才拆分为多条建议。
# - 不要重复分析结论，要直接给出动作。
# - 每条建议都应尽量明确对应前三类分析中的某个问题、冲突、风险或需求。
# - 建议应使用建议式表达，但不强制固定前缀。
#
# ## 输出要求
# 请严格按以下 JSON 格式返回，不要包含 markdown 代码块标记：
#
# 写作约束：
# - 优先输出“事实 -> 分析 -> 改进/风险/方向”的完整表达，而不是标签式短句。
# - 宁可少写，也不要把一条完整分析拆碎。
# - 宁可少写，也不要只给一个未展开的抽象结论。
#
# {
#   "event_emotion_analyses": [
#     {
#       "event_index": 0,
#       "title": "事件标题",
#       "emotion_analyses": [
#         "一条独立情绪分析文本"
#       ]
#     }
#   ],
#   "diary_emotion_analyses": [
#     "一条独立日记级情绪总结文本"
#   ],
#   "event_behavior_decision_analyses": [
#     {
#       "event_index": 0,
#       "title": "事件标题",
#       "behavior_decision_analyses": [
#         "一条独立行为与决策分析文本"
#       ]
#     }
#   ],
#   "diary_behavior_decision_analyses": [
#     "一条独立日记级行为与决策总结文本"
#   ],
#   "event_self_understanding_analyses": [
#     {
#       "event_index": 0,
#       "title": "事件标题",
#       "self_understanding_analyses": [
#         "一条独立关注点与需求分析文本"
#       ]
#     }
#   ],
#   "diary_self_understanding_analyses": [
#     "一条独立日记级关注点与需求总结文本"
#   ],
#   "event_action_suggestions": [
#     {
#       "event_index": 0,
#       "title": "事件标题",
#       "action_suggestions": [
#         "下次可以尝试……"
#       ]
#     }
#   ],
#   "diary_action_suggestions": [
#     "下次可以尝试……"
#   ]
# }"""

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
    )
    return user_message


def _log_llm_response(step_name: str, result: dict) -> None:
    """记录分析流水线完整 LLM JSON 响应。"""
    _ai_logger.info("[%s] 完整LLM响应: %s", step_name, _json_dumps(result))


def _list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


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
    _update_step(task_id, "mood_tag_extracting")

    original_text = state["original_text"]
    structured_diary = state["structured_diary"]
    event_count = _list_len(structured_diary.get("events"))
    logger.info(
        "分析流水线环节7开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        event_count,
    )

    llm = _get_llm(0.3)
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
    )
    return {"mood": mood, "event_tags": validated_event_tags}


async def core_analysis(state: AnalysisState) -> dict:
    """环节 8：核心分析 + 可行动建议"""
    task_id = state["task_id"]
    _update_step(task_id, "core_analyzing")

    events = state["structured_diary"].get("events", [])
    input_data = {"events": events}
    logger.info(
        "分析流水线环节8开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        _list_len(events),
    )

    llm = _get_llm(0.5)
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

    output = {
        "event_emotion_analyses": safe_list(result.get("event_emotion_analyses")),
        "diary_emotion_analyses": safe_list(result.get("diary_emotion_analyses")),
        "event_behavior_decision_analyses": safe_list(result.get("event_behavior_decision_analyses")),
        "diary_behavior_decision_analyses": safe_list(result.get("diary_behavior_decision_analyses")),
        "event_self_understanding_analyses": safe_list(result.get("event_self_understanding_analyses")),
        "diary_self_understanding_analyses": safe_list(result.get("diary_self_understanding_analyses")),
        "event_action_suggestions": safe_list(result.get("event_action_suggestions")),
        "diary_action_suggestions": safe_list(result.get("diary_action_suggestions")),
    }
    logger.info(
        "分析流水线环节8完成: diary_id=%s, task_id=%s, event_emotion=%d, diary_emotion=%d, event_behavior=%d, diary_behavior=%d, event_need=%d, diary_need=%d, event_action=%d, diary_action=%d",
        state.get("diary_id"),
        task_id,
        _count_event_inner_items(output["event_emotion_analyses"], "emotion_analyses"),
        _list_len(output["diary_emotion_analyses"]),
        _count_event_inner_items(output["event_behavior_decision_analyses"], "behavior_decision_analyses"),
        _list_len(output["diary_behavior_decision_analyses"]),
        _count_event_inner_items(output["event_self_understanding_analyses"], "self_understanding_analyses"),
        _list_len(output["diary_self_understanding_analyses"]),
        _count_event_inner_items(output["event_action_suggestions"], "action_suggestions"),
        _list_len(output["diary_action_suggestions"]),
    )
    return output


async def cognition_analysis(state: AnalysisState) -> dict:
    """环节 9：认知校准 + 问题解答 + 认知完善"""
    task_id = state["task_id"]
    _update_step(task_id, "cognition_analyzing")

    events = state["structured_diary"].get("events", [])
    input_data = {"events": events}
    logger.info(
        "分析流水线环节9开始: diary_id=%s, task_id=%s, event_count=%d",
        state.get("diary_id"),
        task_id,
        _list_len(events),
    )

    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        COGNITION_ANALYSIS_PROMPT,
        _log_llm_request("cognition_analysis", COGNITION_ANALYSIS_PROMPT, input_data),
        step_name="cognition_analysis",
    )
    _log_llm_response("cognition_analysis", result)

    def safe_list(val):
        return val if isinstance(val, list) else []

    output = {
        "event_cognitive_calibration_analyses": safe_list(result.get("event_cognitive_calibration_analyses")),
        "diary_cognitive_calibration_analyses": safe_list(result.get("diary_cognitive_calibration_analyses")),
        "event_question_answers": safe_list(result.get("event_question_answers")),
        "diary_question_answers": safe_list(result.get("diary_question_answers")),
        "event_cognitive_enhancements": safe_list(result.get("event_cognitive_enhancements")),
        "diary_cognitive_enhancements": safe_list(result.get("diary_cognitive_enhancements")),
    }
    logger.info(
        "分析流水线环节9完成: diary_id=%s, task_id=%s, event_calibration=%d, diary_calibration=%d, event_qa=%d, diary_qa=%d, event_enhancement=%d, diary_enhancement=%d",
        state.get("diary_id"),
        task_id,
        _count_event_inner_items(output["event_cognitive_calibration_analyses"], "cognitive_calibration_analyses"),
        _list_len(output["diary_cognitive_calibration_analyses"]),
        _count_event_inner_items(output["event_question_answers"], "question_answers"),
        _list_len(output["diary_question_answers"]),
        _count_event_inner_items(output["event_cognitive_enhancements"], "cognitive_enhancements"),
        _list_len(output["diary_cognitive_enhancements"]),
    )
    return output


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
    logger.info(
        "分析流水线开始: diary_id=%s, task_id=%s, diary_organized_id=%s, event_count=%d",
        diary_id,
        task_id,
        diary_organized_id,
        _list_len(structured_diary.get("events")),
    )
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
    logger.info("分析流水线图执行完成: diary_id=%s, task_id=%s", diary_id, task_id)

    # 清理 checkpoint
    await cleanup_checkpoint(task_id)
    logger.info("分析流水线 checkpoint 已清理: diary_id=%s, task_id=%s", diary_id, task_id)

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
    logger.info(
        "分析流水线完成: diary_id=%s, task_id=%s, mood=%s, event_tags=%d, diary_actions=%d",
        diary_id,
        task_id,
        analysis_result["mood"],
        _list_len(analysis_result["event_tags"]),
        _list_len(analysis_result["diary_action_suggestions"]),
    )

    return analysis_result
