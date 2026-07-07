# 分析流水线方案细则

> 基于已实现代码的技术方案文档，用于后续审视和细化。

## 1. 概述

分析流水线是整理流水线之后的独立阶段，由用户手动触发。基于整理后的结构化日记和原始文本，通过 4 环节 LangGraph 流水线生成心情、标签和日记分析五部分。

**指导思想**：日记分析的目标是帮助用户认清自己。

**拓扑结构**：

```
START → mood_tag_extract → core_analysis → calibration_suggest → analysis_check → END
```

- **环节 7**（mood_tag_extract）：心情 + 标签提取
- **环节 8**（core_analysis）：核心分析（情绪 / 行为 / 关注点）
- **环节 9**（calibration_suggest）：校准与建议（认知校准 / 可行动建议）
- **检查环节**（analysis_check）：分析内部检查，质量守门员

流水线构建使用 LangGraph `StateGraph(AnalysisState)`，4 个节点顺序执行，每个节点为 async 函数。

---

## 2. 输入数据

分析流水线的输入通过 `run_analysis_pipeline` 函数传入，包含以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `original_text` | `str` | 日记原文 |
| `structured_diary` | `dict` | 整理后的结构化日记 |
| `task_id` | `str` | 分析任务 ID（organize_tasks 表） |
| `diary_id` | `str` | 日记 ID |
| `user_id` | `str` | 用户 ID |
| `diary_organized_id` | `str` | 整理记录 ID |

**structured_diary 结构**：

```json
{
  "introduction": "引入段文本",
  "events": [
    {
      "title": "事件标题",
      "body": ["段落1", "段落2"],
      "feeling": ["感受1"],
      "reflection": ["反思1"]
    }
  ],
  "trivia": ["琐事1", "琐事2"],
  "plans": ["计划1", "计划2"]
}
```

**数据来源**：`structured_diary` 从 `diary_organized` 表和 `diary_events` 表组装。`diary_organized` 提供 `introduction`、`trivia`（JSON 反序列化）、`plans`（JSON 反序列化），`diary_events` 提供事件列表（按 `sort_order` 排序）。

**State 数据结构**（`AnalysisState`，TypedDict）：

```python
class AnalysisState(TypedDict, total=False):
    # 输入
    original_text: str
    structured_diary: dict
    task_id: str
    diary_id: str
    user_id: str
    diary_organized_id: str

    # 环节 7 产物
    mood: str
    event_tags: list

    # 环节 8 产物
    emotion_analysis: str
    behavior_analysis: str
    focus_analysis: str

    # 环节 9 产物
    cognitive_calibration: str
    actionable_suggestions: str

    # 检查环节产物
    analysis_check_log: list

    # 进度追踪
    current_step: str
```

---

## 3. 各环节设计

### 3.1 环节 7：心情 + 标签提取

**节点函数**：`mood_tag_extract`

**定位**：精确提取任务，从结构化日记中提取当天整体心情和事件级标签。

**Temperature**：0.3

**输入**：`original_text` + `structured_diary`

**输出**：

```json
{
  "mood": "心情短词",
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
}
```

#### Prompt 核心规则

**心情提取**：
1. 心情用一个短词表示当天整体情绪或状态，例如"疲惫""平静""烦躁""开心""低落""充实""焦虑""放松"
2. 必须有 structured_diary 或 original_text 中的明确线索支撑
3. 没有明确线索则填空字符串

**标签提取**：
1. 标签不是简单分类，而是为后续检索、AI 对话、人物画像、心路历程和知识沉淀提供入口
2. 标签类型固定为五类
3. 只输出事件级标签，不直接输出整篇日记级标签（日记级标签由所有事件级标签合并、去重后得到）
4. `event_tags` 必须与 `structured_diary.events` 一一对应，`title` 使用事件 title
5. 每个事件的 tags 都按五类输出，没有对应标签时输出空数组
6. 同一事件、同一类型下可以有多个标签，但不要重复
7. 优先提取 topic、person_object、psychological、knowledge；domain 只作为辅助粗分类，数量要少
8. 标签必须来自原文中的明确依据
9. 不生成原文没有依据的标签
10. 不生成空泛评价型标签（如"成长""感悟""重要""日常"）
11. 心情词不重复作为标签

**输入说明**：structured_diary 是主要依据，original_text 仅用于核对事实，不从 original_text 中挖掘 structured_diary 已经剔除的语言噪音。

#### 标签类型定义

| 类型 | 作用 | 示例 |
|---|---|---|
| domain | 粗粒度筛选日记 | 工作、生活、关系、健康、学习、娱乐 |
| topic | 串起长期反复出现的具体事项 | 日记管理、AI 开发、遛狗 |
| person_object | 串起具体人物、关系和重要对象 | 林萧鹏、田总、媳妇、达达 |
| psychological | 串起情绪、需求和内在模式 | 不确定性、控制感、遗憾、成就感 |
| knowledge | 串起学习内容、方法、概念和做事方式 | 软件工程、需求分析、项目管理 |

#### 容错处理

代码中对 AI 返回结果做了完整容错：
- `mood` 不是字符串时置为空字符串
- `event_tags` 不是 list 时置为空 list
- 遍历每个元素：跳过非 dict 元素，确保有 `title` 和 `tags` 字段
- `tags` 不是 dict 时置为空 dict
- 五类标签（domain / topic / person_object / psychological / knowledge）不是 list 时置为空 list

#### 待细化/待确认

- [ ] 当 structured_diary 没有 events（如纯琐事日记）时，event_tags 为空，是否需要额外生成日记级标签？
- [ ] domain 标签是否需要限定枚举值（当前是开放生成，示例为"工作/生活/关系/健康/学习/娱乐"）
- [ ] 同一标签名在不同事件中被归入不同 type 的情况如何处理（当前以首次出现的 type 为准 upsert）
- [ ] 标签是否需要长度限制（当前 Tag 模型 name 字段为 String(50)）

---

### 3.2 环节 8：核心分析

**节点函数**：`core_analysis`

**定位**：描述性和解释性分析，只分析当天日记，不做评判。

**Temperature**：0.5

**输入**：`original_text` + `structured_diary`

**输出**：

```json
{
  "emotion_analysis": "情绪分析文本",
  "behavior_analysis": "行为与决策分析文本",
  "focus_analysis": "关注点、需求与自我理解分析文本"
}
```

#### 三部分分析定义

**情绪分析（emotion_analysis）**：
- 分析用户在当天事件中的主要情绪、情绪变化路径和触发点
- 描述主要情绪及其变化
- 描述触发情绪变化的具体事实
- 情绪背后反映了什么被触动
- **禁止**：不用百分比量化，不做心理诊断，不把短期情绪说成长期状态，不写"你是一个情绪化的人"

**行为与决策分析（behavior_analysis）**：
- 分析用户当天面对事件时采取了什么行动、做了什么选择，以及体现出的当天应对方式
- 描述具体行为和选择
- 分析应对方式：主动推进、等待观察、寻求外部帮助，还是回避处理
- 行为带来了什么结果或影响
- **禁止**：不上升为长期人格，不写"你一直都是…"，不贴标签，不脱离当天事实分析行为模式

**关注点、需求与自我理解（focus_analysis）**：
- 分析用户当天真正被什么牵动，以及背后反映出的当下需求、期待、边界感、自我叙事和价值排序
- 用户真正关注的是什么
- 用户当下想要什么、害怕或抗拒什么
- 用户正在维护什么
- 用户对事件形成了什么理解，反映出看重什么
- **禁止**：不做心理诊断，不写长期人格结论，不写"你缺乏安全感""你很依赖认可"等诊断式表达，不替用户扩展到原文没有支撑的人生经历

#### 核心边界（5 条红线）

1. 只分析当天这篇日记，不引用当天以外的信息
2. 不做长期人格判断、心理诊断、贴标签
3. 较强推断必须写依据，依据来自当天结构化日记中的具体事件或事实
4. 只做描述性和解释性分析，不做评判
5. 不把推导写成绝对事实

#### 代码处理

返回值使用 `result.get("key", "") or ""`，确保 None 值也被转为空字符串。

#### 待细化/待确认

- [ ] 当 structured_diary 只有 introduction 和 trivia、没有 events 时，核心分析如何定位分析对象
- [ ] 三部分分析是否需要规定最小/最大字数范围，避免过于简短或过于冗长
- [ ] "较强推断"的判定标准是否需要给出更明确的指引（如：情绪归因算强推断还是弱推断）
- [ ] 环节 8 与环节 9 的边界：当分析中自然带出建议性内容时，是否会与环节 9 的可行动建议重复

---

### 3.3 环节 9：校准与建议

**节点函数**：`calibration_suggest`

**定位**：评判性与行动导向推导，依赖环节 8 的分析结果。

**Temperature**：0.5

**输入**：`original_text` + `structured_diary` + 环节 8 的分析结果（`analysis_result` 包含 `emotion_analysis` / `behavior_analysis` / `focus_analysis`）

**输出**：

```json
{
  "cognitive_calibration": "认知校准文本",
  "actionable_suggestions": "可行动建议文本"
}
```

#### 认知校准（cognitive_calibration）

识别用户对世界、他人、自己、事件因果的理解中是否存在明显认知偏差并温和纠正。

**规则**：
1. 识别过度概括、绝对化、事实支撑不足等问题
2. 区分情绪表达和事实可支持的结论
3. 对知识点、方法论的错误理解，如果有足够把握，可以直接指出并补充更准确理解
4. 信息不足时写"原文不足以判断该理解是否准确"
5. **禁止**：不否定用户感受、不站道德高地、依据不足时不强行纠错、不对专业知识胡乱纠正、不把认知校准写成行动建议

#### 可行动建议（actionable_suggestions）

给出 1-3 条低成本、具体、可执行的建议。

**规则**：
1. 给出 1-3 条建议
2. 建议必须低成本、具体、可执行
3. 使用"下次可以尝试…"这类建议式表达
4. **禁止**：不使用"你应该…"命令式表达、不输出空泛建议（鸡汤式表达）、不输出高成本建议（如辞职、结束关系等重大决策，除非原文明确表达相关打算）
5. 建议服务于下一次遇到类似情况时的具体行动

#### 待细化/待确认

- [ ] 认知校准和可行动建议是否可能为空（当天日记没有可校准/可建议的内容时），Prompt 未明确允许空值
- [ ] 知识点纠错的"足够把握"标准如何界定，是否需要引入置信度
- [ ] 高成本建议的边界：如用户日记中明确提到想辞职，是否就可以给出辞职相关建议
- [ ] 环节 9 的输入是环节 8 的输出，如果环节 8 的分析存在偏差，环节 9 是否会被级联影响（部分由检查环节兜底）

---

### 3.4 检查环节：分析内部检查

**节点函数**：`analysis_check`

**定位**：质量守门员，对环节 7/8/9 的全部产出做一轮检查，发现问题直接修正。

**Temperature**：0.3

**输入**：`original_text` + `structured_diary` + 全部分析结果（`analysis_result` 包含 `mood` / `event_tags` / `emotion_analysis` / `behavior_analysis` / `focus_analysis` / `cognitive_calibration` / `actionable_suggestions`）

**输出**：修正后的分析结果 + `analysis_check_log`

```json
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
```

#### 8 项检查

| 序号 | 检查项 | 说明 |
|---|---|---|
| 1 | 外部信息引用 | 是否引用了当天日记以外的信息（如历史日记、其他日期事件） |
| 2 | 长期人格判断 | 是否做了长期人格判断或贴标签（如"你是一个…的人""你总是…"） |
| 3 | 推断依据 | 较强推断是否缺少依据（推断必须写明依据来自哪个具体事件或事实） |
| 4 | 感受否定 | 认知校准是否否定了用户感受（如"你不应该感到…""这种感受不合理"） |
| 5 | 强行纠错 | 认知校准是否在依据不足时强行纠错（原文信息不足时应标注"不足以判断"） |
| 6 | 建议可执行性 | 可行动建议是否具体、低成本、可执行（不能是空泛鸡汤或高成本建议） |
| 7 | 命令式表达 | 是否出现命令式表达（如"你应该…""你必须…"） |
| 8 | 空泛建议 | 是否出现空泛建议（如"学会放下""接受自己""多沟通"等无具体行动的表述） |

#### 修正规则

1. 发现问题时直接输出修正后的对应字段内容
2. 没有问题的字段原样输出
3. 每个检查项记录检查结果：通过则 status 为"通过"，发现问题并修正则 status 为"已修正"
4. 只做一轮检查，修正后不重新检查
5. `analysis_check_log` 必须包含全部 8 个检查项

#### 代码处理

- `analysis_check_log` 不是 list 时置为空 list
- 5 个文本字段使用 `result.get("key", state["key"]) or ""`，确保修正值覆盖，同时处理 None 值
- mood 和 event_tags 不在检查环节的修正范围内（检查输入包含但输出不覆盖）

#### 待细化/待确认

- [ ] 检查环节不检查 mood 和 event_tags 的质量，是否需要增加对标签准确性的检查
- [ ] 检查环节的修正可能引入新的问题（如修正后反而丢失了有价值的分析），是否需要"回退"机制
- [ ] 8 项检查是否有优先级，当多项检查冲突时如何处理（如"不否定感受"与"识别认知偏差"的边界）
- [ ] `analysis_check_log` 是否需要持久化到数据库（当前仅保存在 State 中，未写入任何表）

---

## 4. 标签落库策略

分析完成后执行标签落库（`_persist_tags` 函数，同步 SQLAlchemy）。

### 执行步骤

1. **查询事件映射**：根据 `diary_organized_id` 查询该日记的所有 `DiaryEvent`，构建 `event_title → diary_event_id` 映射
2. **删除旧关联**：
   - 删除该日记的所有 `diary_tags` 关联（按 `diary_id`）
   - 删除该日记所有事件的 `event_tags` 关联（按 `diary_event_id IN (...)`）
3. **Upsert 标签**：
   - 按 `user_id + name` 去重查询 `Tag` 表
   - 已有标签：如果 `type` 为空则补填当前 type
   - 新标签：创建 `Tag(user_id, name, type)` 记录
   - 使用 `tag_cache` 字典缓存已处理的标签，避免重复查询
4. **创建事件级关联**：遍历 `event_tags`，通过事件标题匹配 `diary_event_id`，在 `event_tags` 表中创建 M:N 关联（先检查是否已存在）
5. **创建日记级关联**：所有标签 ID 去重后（`all_tag_ids` 集合），在 `diary_tags` 表中创建 M:N 关联

### 重新分析场景

- 先删旧关联再重建
- `tags` 表中的标签记录不删除（只删关联，不删标签本身）

### 容错

标签落库失败不影响分析结果返回。调用处使用 `try/except` 包裹，仅记录错误日志：

```python
try:
    _persist_tags(user_id, diary_id, diary_organized_id, analysis_result["event_tags"])
except Exception as e:
    logger.error("标签落库异常（不影响分析结果返回）: %s", e)
```

### 待细化/待确认

- [ ] 标签落库与分析结果存储不在同一个事务中，如果分析结果存储成功但标签落库失败，数据不一致如何处理
- [ ] 事件标题匹配依赖 `event_title == title`，如果整理环节修改了事件标题但分析环节用的是旧标题，会导致匹配失败
- [ ] 删除旧关联和创建新关联之间没有事务级别的原子性保证（当前整个 `_persist_tags` 在单个 session 中，commit 在最后）
- [ ] 标签的 type 字段以首次 upsert 时为准，后续如果同一标签在不同事件中被识别为不同类型，type 不会被更新

---

## 5. 结果存储

分析结果存入 `diary_analysis` 表（`_save_analysis_result` 函数）。

### diary_analysis 表结构

| 字段 | 类型 | 来源 |
|---|---|---|
| `id` | UUID PK | 自动生成 |
| `task_id` | UUID FK → organize_tasks.id | 分析任务 ID |
| `diary_organized_id` | UUID FK → diary_organized.id（unique） | 1:1 关联整理记录 |
| `mood` | String(50) | 环节 7 |
| `emotion_analysis` | Text | 环节 8（可能被检查环节修正） |
| `behavior_analysis` | Text | 环节 8（可能被检查环节修正） |
| `focus_analysis` | Text | 环节 8（可能被检查环节修正） |
| `cognitive_calibration` | Text | 环节 9（可能被检查环节修正） |
| `actionable_suggestions` | Text | 环节 9（可能被检查环节修正） |
| `analyzed_at` | DateTime | 分析时间 |
| `updated_at` | DateTime | 更新时间 |

### 重新分析

先删除该 `diary_organized_id` 的旧 `DiaryAnalysis` 记录，再创建新记录。

### 状态更新

同时更新 `diaries.status` 为 `analyzed`（`DiaryStatus.analyzed`）。

### 待细化/待确认

- [ ] `analysis_check_log` 当前未持久化，是否需要存入数据库以供后续审计
- [ ] 重新分析时，旧分析记录被物理删除，是否需要软删除或保留历史版本
- [ ] `diary_analysis` 表没有 `event_tags` 字段，事件级标签仅通过 `event_tags` 关联表存储，查询时需要 JOIN

---

## 6. 断点续跑机制

- 复用整理流水线的 `AsyncPostgresSaver` checkpointer（`get_checkpointer()` 函数）
- `thread_id` 使用分析任务的 `task_id`（与整理流水线天然隔离，因为分析任务有独立的 task_id）
- 每个节点执行完 LangGraph 自动保存 State 快照到 PostgreSQL
- 失败后重新触发分析，LangGraph 自动从断点恢复（已完成节点的输出已在 State 中）
- 分析成功后清理 checkpoint（`cleanup_checkpoint(task_id)`）

### 待细化/待确认

- [ ] 断点续跑时，如果环节 7 已完成但环节 8 失败，重跑时 `_update_step` 是否会再次更新环节 7 的进度（当前每个节点开头都会调用 `_update_step`）
- [ ] checkpoint 清理失败时的处理策略（当前 `cleanup_checkpoint` 在 `run_analysis_pipeline` 中 await，如果失败会抛异常）

---

## 7. 进度追踪

通过 `organize_tasks.current_step` 字段追踪进度，前端轮询机制复用整理流水线的方案。

每个节点函数开头调用 `_update_step(task_id, step_value)` 更新进度。

| current_step 值 | 对应环节 | 说明 |
|---|---|---|
| `mood_tag_extracting` | 环节 7 | 心情与标签提取 |
| `core_analyzing` | 环节 8 | 核心分析 |
| `calibrating` | 环节 9 | 校准与建议 |
| `analysis_checking` | 检查环节 | 分析质量检查 |

分析任务的 `organize_tasks.task_type` 为 `"analyze"`（整理任务为 `"organize"`），通过 `task_type` 区分任务类型。

---

## 8. 与设计文档的对应关系

| 设计文档章节 | 本文档对应 | 代码位置 |
|---|---|---|
| 分析流水线详细设计 | 第 1 节概述 | `services/analysis_pipeline.py` |
| 分析 State 数据结构 | 第 2 节输入数据 | `AnalysisState` TypedDict |
| 环节 7 详细设计 | 第 3.1 节 | `mood_tag_extract()` |
| 环节 8 详细设计 | 第 3.2 节 | `core_analysis()` |
| 环节 9 详细设计 | 第 3.3 节 | `calibration_suggest()` |
| 分析内部检查机制 | 第 3.4 节 | `analysis_check()` |
| 标签落库策略 | 第 4 节 | `_persist_tags()` |
| 日记分析五部分定义 | 设计文档"日记分析"章节 | `DiaryAnalysis` 模型 |
| Prompt 局限性与改进 | 第 9 节 | 各 Prompt 常量 |

---

## 9. Prompt 局限性分析与改进方向

本节对 4 个环节的 Prompt 做系统性审视，识别当前设计中的结构性局限和具体不足，并提出可能的改进方向。

### 9.1 跨环节共性问题

#### 9.1.1 过度依赖"不要…"禁令，缺少正面示例

**现象**：4 个 Prompt 中大量使用"不要/不写/不做/禁止"等否定式指令来划定边界。统计如下：

| Prompt | 否定式规则数 | 肯定式规则数 |
|---|---|---|
| MOOD_TAG_PROMPT | 4 条（规则 8/9/10/11） | 7 条 |
| CORE_ANALYSIS_PROMPT | 7 条（核心边界 + 各部分禁止项） | 约 10 条 |
| CALIBRATION_PROMPT | 7 条（规则 5/6/7/8/9 + 建议规则 4/5/6） | 7 条 |
| ANALYSIS_CHECK_PROMPT | 间接引用前 3 个 Prompt 的禁令 | — |

**问题**：
- LLM 对否定指令的遵从度天然低于肯定指令（"不要想白熊"效应）
- 禁令只告诉模型"不能做什么"，没有展示"应该怎么做"，模型需要自行推断正面行为
- 多个禁令叠加时，模型可能过度保守，产出过于平淡的分析

**改进方向**：
- 为每类禁令配套 1 个正面示例（好的输出）和 1 个反面示例（违规输出），形成对比教学
- 将高频违反的禁令升级为带示例的核心规则

#### 9.1.2 全链路无 Few-shot 示例

**现象**：4 个 Prompt 均未提供输入→输出的完整示例。

**问题**：
- 模型对输出风格、深度、长度的理解完全依赖规则描述，缺少具象锚定
- 不同次执行时，输出风格和质量的方差较大
- 对于"描述性分析"vs"评判"这类微妙边界，纯文字规则难以精确传达

**改进方向**：
- 为环节 7 提供 1-2 个标签提取示例（覆盖不同日记类型）
- 为环节 8 提供 1 个完整分析示例（含情绪/行为/关注点三部分），作为风格和深度的锚定
- 为环节 9 提供认知校准 + 建议的正反例各 1 个
- 示例可以从 `temp/` 目录的日记样例中构造

#### 9.1.3 "明确线索/依据"表述模糊

**现象**：多个环节使用"明确线索支撑""明确依据""足够把握"等表述，但未定义判定标准。

| 出处 | 模糊表述 |
|---|---|
| MOOD_TAG_PROMPT 规则 2 | "必须有…明确线索支撑" |
| MOOD_TAG_PROMPT 规则 8 | "标签必须来自…明确依据" |
| CORE_ANALYSIS_PROMPT 边界 3 | "较强推断必须写依据" |
| CALIBRATION_PROMPT 规则 3 | "如果有足够把握" |

**问题**：
- 模型对"明确"的判断标准可能与用户预期不一致
- "较强推断"vs"一般推断"的边界未定义，模型无法区分何时需要标注依据

**改进方向**：
- 为"明确线索"给出操作性定义：如"原文中有直接描述情绪的词语或行为表现"
- 为"较强推断"给出判定规则：如"从行为推导心理动机属于强推断，从行为描述行为属于描述"

#### 9.1.4 无输出长度/格式指引

**现象**：4 个 Prompt 均未对输出文本的长度、段落结构做指引。

**问题**：
- 环节 8 的三个分析字段可能产出 1 句话也可能产出 5 段话，质量不稳定
- 环节 9 的认知校准和建议没有长度约束，可能出现过于冗长的校准或过于简短的建议
- 前端展示时，过长或过短的分析都会影响用户体验

**改进方向**：
- 为每个文本字段增加长度指引，如"情绪分析 100-200 字，分 1-2 个自然段"
- 为可行动建议增加格式指引，如"每条建议用序号标注，每条 30-80 字"

### 9.2 环节级具体问题

#### 9.2.1 环节 7：心情 + 标签提取

**问题 1：心情"短词"定义不精确**

Prompt 给出示例"疲惫""平静""烦躁""开心"等，但未限定长度。模型可能输出"有点累""还不错"等非短词表述。

**改进方向**：明确限定为 2-4 个字的词语，或提供候选词表。

**问题 2：标签类型边界模糊**

- `topic`（具体事项）与 `domain`（领域）的区分：如"项目管理"是 topic 还是 domain？
- `psychological`（心理主题）与环节 8 情绪分析的边界：如"焦虑"是标签还是分析内容？
- `knowledge`（知识点）与 `topic` 的区分：如"AI 开发"是知识还是主题？

**改进方向**：为容易混淆的边界给出判定规则，如"如果是对某项具体技术/方法的学习和理解，归 knowledge；如果是正在做的事项本身，归 topic"。

**问题 3：未说明 trivia 和 plans 的标签处理**

Prompt 只说 event_tags 与 events 一一对应，但 structured_diary 中还有 trivia 和 plans。这两部分是否需要提取标签？当前设计是不提取，但可能导致计划中提到的重要事项（如"下周要给田总汇报"）缺少标签覆盖。

**改进方向**：明确 trivia 和 plans 不参与标签提取，或增加 trivia_tags / plans_tags。

**问题 4：标签数量无指引**

每个事件每种类型的标签数量没有上下限指引。模型可能为单个事件输出 10 个 topic 标签，也可能全部输出空数组。

**改进方向**：给出建议范围，如"每个事件每种类型 0-3 个标签，整篇日记总计不超过 15 个标签"。

#### 9.2.2 环节 8：核心分析

**问题 1：三部分的分析边界不够清晰**

情绪分析、行为分析、关注点分析在概念上有交叉：
- "用户因项目延期而焦虑"——是情绪分析还是行为分析？
- "用户在意同事的评价"——是情绪触发点还是关注点/需求？

模型在实践中可能将同一内容在三部分中重复表述。

**改进方向**：为每部分划定独占边界，如"情绪分析只描述情绪本身和触发事实，不做归因；关注点分析负责归因到需求和价值排序"。

**问题 2：未处理特殊日记类型**

- 纯琐事日记（无 events，只有 trivia）：三部分分析缺乏分析对象
- 极短日记（原文不足 50 字）：分析可能比原文还长，显得过度解读
- 纯记录型日记（无情感色彩）：情绪分析可能强行编造情绪

**改进方向**：在 Prompt 中增加特殊场景指引，如"当结构化日记不包含事件时，基于 trivia 和 plans 进行分析，并降低分析深度"或"当原文信息不足以支撑某部分分析时，该字段填写'当天日记信息较少，暂无该维度分析'"。

**问题 3："描述性 vs 评判"的边界微妙**

"你今天选择了回避"是描述，"你选择了回避，这可能不是最佳方式"是评判——但"你的回避让问题变得更复杂"呢？这是描述结果还是隐含评判？

当前 Prompt 只给出原则（"只做描述性和解释性分析，不做评判"），没有给出边界案例的判定指引。

**改进方向**：增加 2-3 个边界案例，标注哪些是描述、哪些是评判、哪些是可以接受的解释性分析。

#### 9.2.3 环节 9：校准与建议

**问题 1：无"无需校准/无建议"的退出机制**

Prompt 要求输出认知校准和可行动建议，但未说明当天日记不存在认知偏差或无需建议时如何处理。模型可能为了"完成任务"而强行找出问题或编造建议。

**改进方向**：明确允许空值，如"如果当天日记没有明显的认知偏差，cognitive_calibration 写'当天表达的认知理解与事实基本一致，无需校准'。如果无合适建议，actionable_suggestions 写'当天暂无具体建议'"。

**问题 2："低成本"缺乏操作性定义**

"低成本"对不同用户含义不同：对程序员来说"写一段代码验证想法"是低成本，对其他人可能不是。

**改进方向**：给出更具体的框架，如"低成本 = 不需要改变当前生活/工作结构，可以在 10 分钟内完成的一次性行动"。

**问题 3：认知校准与建议的内容可能重叠**

认知校准中"指出更准确的理解"很容易滑向"建议你这样想"，与可行动建议产生重复。虽然规则 9 说"不把认知校准写成行动建议"，但认知层面的校准本身就隐含行动方向。

**改进方向**：明确分工——认知校准只回答"你的理解是否准确"，可行动建议只回答"下次可以做什么"。在 Prompt 中增加约束："认知校准中不得出现'可以尝试''建议'等行动导向词汇"。

#### 9.2.4 检查环节

**问题 1：自我审查的固有盲区**

检查环节使用同一模型（同 temperature 0.3）审查自己前几轮的输出。模型倾向于认为自己之前的输出是合理的，审查力度有限。

**改进方向**：
- 使用不同的 system prompt 角色设定（当前已做到，"审核助手"vs"分析助手"），但可以进一步强化差异化人设
- 考虑使用不同模型或不同 temperature 做检查（如更低的 temperature 以获得更严格/确定性的判断）
- 长远可考虑引入第二个模型做交叉审查

**问题 2：8 项检查存在重叠**

- 检查项 6（建议是否具体可执行）、7（是否命令式表达）、8（是否空泛建议）都聚焦于建议质量，可以合并为一项"建议质量综合检查"
- 检查项 4（感受否定）和 5（强行纠错）都聚焦于认知校准的分寸，也存在重叠

重叠导致模型在多个检查项中重复评估同一内容，增加"通过"的概率（因为已经在前一项检查中调整过了）。

**改进方向**：将 8 项精简为 5 项，合并同类检查：
1. 外部信息引用
2. 长期人格判断 / 贴标签
3. 推断依据充分性
4. 认知校准分寸（合并原 4 + 5）
5. 建议质量（合并原 6 + 7 + 8）

**问题 3：不检查 mood 和 event_tags**

检查环节接收了 mood 和 event_tags 作为输入，但输出中不包含这两个字段的修正。这意味着标签提取和心情提取的错误无法被检查环节发现和修正。

**改进方向**：增加对 mood 和 event_tags 的检查项，如"心情是否有原文依据""标签是否与事件内容匹配"。

### 9.3 改进优先级建议

按"对输出质量影响程度"和"实施成本"综合排序：

| 优先级 | 改进项 | 影响 | 成本 |
|---|---|---|---|
| P0 | 增加 Few-shot 示例（环节 7 + 8） | 高：显著稳定输出质量和风格 | 中：需要构造和筛选样例 |
| P0 | 明确"无需校准/无建议"退出机制 | 高：消除强行输出问题 | 低：仅改 Prompt |
| P1 | 细化标签类型边界和判定规则 | 高：提升标签准确性 | 低：仅改 Prompt |
| P1 | 增加输出长度/格式指引 | 中：稳定输出篇幅 | 低：仅改 Prompt |
| P1 | 合并重叠检查项 + 增加标签检查 | 中：提升检查有效性 | 低：仅改 Prompt |
| P2 | 为禁令配套正反例 | 中：提升规则遵从度 | 中：需要构造示例 |
| P2 | 操作化"明确线索""较强推断"等模糊概念 | 中：减少模型自由裁量空间 | 低：仅改 Prompt |
| P2 | 特殊日记类型处理指引 | 中：覆盖边界场景 | 低：仅改 Prompt |
| P3 | 检查环节使用不同模型/参数 | 中：突破自我审查盲区 | 高：涉及架构变更 |
| P3 | 引入用户个性化上下文 | 中：提升分析针对性 | 高：需要用户画像支持 |

---

## 附录：数据流总览

```
用户触发分析
    │
    ▼
run_analysis_pipeline()
    │
    ├── 构建 AnalysisState
    │   ├── original_text ← diaries.original_text
    │   ├── structured_diary ← diary_organized + diary_events 组装
    │   ├── task_id ← 新建 organize_tasks 记录（task_type=analyze）
    │   ├── diary_id / user_id / diary_organized_id
    │
    ├── LangGraph 执行
    │   ├── mood_tag_extract  → mood, event_tags
    │   ├── core_analysis     → emotion_analysis, behavior_analysis, focus_analysis
    │   ├── calibration_suggest → cognitive_calibration, actionable_suggestions
    │   └── analysis_check    → 修正上述结果 + analysis_check_log
    │
    ├── cleanup_checkpoint()  ← 清理断点数据
    │
    ├── _persist_tags()       ← 标签落库（try/except，失败不阻塞）
    │
    └── _save_analysis_result() ← 存入 diary_analysis + 更新 diaries.status
```

---

## 附录：各环节 Prompt 全文

> **存储位置**：所有 Prompt 以 Python 字符串常量的形式内联定义在 `backend/services/analysis_pipeline.py` 中，分别为 `MOOD_TAG_PROMPT`、`CORE_ANALYSIS_PROMPT`、`CALIBRATION_PROMPT`、`ANALYSIS_CHECK_PROMPT`。
>
> **版本化策略（当前）**：Prompt 随代码版本管理，修改 Prompt 需提交代码变更。当前没有独立的 Prompt 版本控制机制，每次 Prompt 变更通过 Git commit 记录。
>
> **版本化策略（建议）**：后续如 Prompt 迭代频率增高，可考虑将 Prompt 抽取到独立文件（如 `backend/prompts/analysis/` 目录）或数据库表中，支持运行时切换版本和 A/B 测试，与代码逻辑解耦。

### A. 环节 7 Prompt：心情 + 标签提取

**常量名**：`MOOD_TAG_PROMPT`
**Temperature**：0.3

```text
你是一个日记心情与标签提取助手。请根据结构化日记和原始文本，提取当天整体心情和事件级标签。

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
}
```

### B. 环节 8 Prompt：核心分析

**常量名**：`CORE_ANALYSIS_PROMPT`
**Temperature**：0.5

```text
你是一个日记分析助手。请根据结构化日记和原始文本，进行描述性和解释性分析。

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
}
```

### C. 环节 9 Prompt：校准与建议

**常量名**：`CALIBRATION_PROMPT`
**Temperature**：0.5

```text
你是一个日记分析助手。请基于结构化日记、原始文本和核心分析结果，进行认知校准并给出可行动建议。

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
}
```

### D. 检查环节 Prompt：分析内部检查

**常量名**：`ANALYSIS_CHECK_PROMPT`
**Temperature**：0.3

```text
你是一个日记分析审核助手。请对照原始日记和结构化日记，审核分析结果（环节 7/8/9 的全部产出），发现问题直接修正。

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

analysis_check_log 必须包含全部 8 个检查项。
```
