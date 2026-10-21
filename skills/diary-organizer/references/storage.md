# Markdown 转换与确认后入库

脚本位于本 Skill 的 `scripts/`。在项目根目录执行，使用 `backend/venv/bin/python`（Python 3.11）。保存脚本自行切换到 `backend` 加载 `.env`，支持用全局参数 `--backend-dir` 指定后端目录。

实际日记的工作目录固定为 `diary-organizations/YYYY-MM-DD/`，同一天的所有整理文件放在一起，修订时复用已有目录。下面命令以 `2026-09-23` 为例，执行时替换为目标日记所属日期；日期未知和同日多篇的情况遵循主 Skill 的工作目录规则。

## 支持的稿件格式

```markdown
原文已有的引入段，没有则省略。

## 事件：具体事件标题

完整正文第一段。

完整正文第二段，可保留原有编号步骤。

### 感受

核心感受及必要背景，没有则省略整个栏目。

### 反思与成长

核心认识及必要背景，没有则省略整个栏目。

### 重要性

MEDIUM：根据事件内容能够核对的影响依据。

## 琐事

- 一条琐事。

## 后续计划

- 一条计划，保留原有确定程度。
```

正文按空行分为字符串数组。感受、反思可用自然段或列表；琐事、计划须用列表，列表续行缩进。每个事件须有非空正文和重要性。空的顶层栏目可以省略。稿件不加额外的日期大标题、解释性标题或代码围栏；日期绑定在入库包中。

转换器严格识别上述标题，遇到未知标题、重复栏目、错误顺序、无正文事件、无效重要性等会停止，不丢弃后继续保存。正文所需的小节用普通文本，避免与结构标题冲突。脚本不判断语义保真和重要性判断是否恰当，须由用户阅读确认。

## 1. 整理前绑定来源并保存澄清记录

按日期处理项目日记时，先用用户名和包含年份的日记日期定位记录，默认用户名为 `x5456`：

```bash
backend/venv/bin/python skills/diary-organizer/scripts/store_diary.py find \
  --username x5456 --date 2026-09-23
```

该命令只读返回 `user_id`、`match_count` 和候选列表，每条包含 `diary_id`、日期、状态、原文字数、事件数；不输出正文或认证信息，排除其他用户及已删除记录。没有匹配时核对用户名和日期，不编造目标；多条匹配时展示候选并请用户选择，不自动取第一条；只有唯一匹配时才直接使用返回的 ID 继续导出。日期未明确年份时结合已知日记上下文确定，无法确定则询问。

项目日记核实目标日记及所属用户 ID 后，只读导出原文；即使仅在本地整理也可导出。`DIARY_UUID`、`USER_UUID` 替换为查询结果中的真实 ID：

```bash
backend/venv/bin/python skills/diary-organizer/scripts/store_diary.py export \
  --diary-id DIARY_UUID --user-id USER_UUID \
  --output diary-organizations/2026-09-23/原文.json
```

`export` 只核实归属与是否删除，不因已分析、来源锁或关联数据拒绝读取。输出中的 `capabilities.can_replace` 和 `reason` 只读报告当前是否支持整篇保存，不代表授权；`supports_event_patch` 当前为 false。已分析日记可以导出到本地整理，但仍不能绕过来源保护写回。只读导出时有运行任务也可能取得随后变化的版本，后续预检会重新核对来源指纹。

根据导出的原文整理。来源状态会参与后续预检，阻止把基于旧原文的稿件标记为最新修订。不能保存时在初稿前简短说明，继续交付本地稿。接入脚本前已经生成的稿件，先核对导出原文与实际使用原文，并保留已确认补充和用户直接修订。

先展示完整初稿和稿后问题；收到回答后展示完整修改稿及剩余问题，继续修订直至没有待澄清问题，再请用户确认最终稿。每轮更新 `整理稿.md`，并在同目录的 `澄清记录.md` 中按 [Skill 的澄清记录格式](../SKILL.md#澄清记录格式)分开记录推测修订与实际澄清问答，不记录用户直接改稿。区分已确认、跳过与待回答；不要把后续新认识记录成当时事实。该文档只在本地留存，不写审核日志表。

## 2. 单独转换（无需数据库）

```bash
backend/venv/bin/python skills/diary-organizer/scripts/markdown_to_json.py \
  diary-organizations/2026-09-23/整理稿.md --output diary-organizations/2026-09-23/整理结果.json
```

JSON 对齐项目流水线返回格式，含 `introduction`、`events`、`trivia`、`plans`；事件含 `title`、`body`、`feeling`、`reflection`、`importance`、`importance_reason`。总标题、摘要、地点留空，审核数组为空，均不伪造。

## 3. 只读预检并冻结入库包

```bash
backend/venv/bin/python skills/diary-organizer/scripts/store_diary.py prepare \
  --markdown diary-organizations/2026-09-23/整理稿.md \
  --clarifications diary-organizations/2026-09-23/澄清记录.md \
  --source diary-organizations/2026-09-23/原文.json \
  --output diary-organizations/2026-09-23/入库包.json
```

该步骤只读数据库，不触发原有 AI 整理；仍执行保存资格检查，受限时不生成入库包。入库包含结果、目标身份、数据库当前状态指纹、稿件和澄清记录的路径与指纹，返回 `confirmation_sha256`。已有输出文件不会被覆盖。重新预检使用新的文件名。

面向用户说明“只读预检通过，未写库，等待整篇最终确认”；用户已明确确认当前文件时不重复询问。不要把预检称为已保存。

所有修订及澄清记录更新完成后再预检。对用户说明：“准备将这份最终稿保存到某年某月某日日记，共 N 个事件；首次保存／替换现有 M 个事件。”展示稿件供阅读。在已约定入库的任务中，用户确认整篇最终稿“没问题”“可以了”后直接保存，无需另问是否允许入库；局部修改确认不算整篇最终确认。用户不必理解或手动操作指纹。

若用户确认后又修改了原文、稿件、澄清记录或旧整理结果，原包会失效。重新预检并确认变更，避免保存未经确认的内容。指纹用于绑定内容，不代替用户授权。

## 4. 核验或正式保存

默认仍只读：

```bash
backend/venv/bin/python skills/diary-organizer/scripts/store_diary.py save \
  diary-organizations/2026-09-23/入库包.json
```

取得上述整篇最终确认后，将 `CONFIRMED_SHA256` 替换为该包返回的指纹：

```bash
backend/venv/bin/python skills/diary-organizer/scripts/store_diary.py save \
  diary-organizations/2026-09-23/入库包.json --write --confirmed-sha256 CONFIRMED_SHA256
```

脚本校验所属用户、来源变化和当前状态；复用项目的分析／建图来源锁检查。仅允许未锁定的 `saved`、`organized` 日记；存在运行任务、分析记录、批注、事件收藏、事件标签或行动关联时停止整篇替换，不自动删除这些用户数据。

正式保存使用单个事务：创建已完成整理任务、新建或更新整理记录、替换无受保护关联的旧事件、递增整理修订号、保存事件重要性、更新日记状态并刷新关键词索引和语义索引待处理状态。语义向量由项目后台后续生成。旧审核记录随整理结果替换；原文保持不变，澄清更正只进入整理结果和本地澄清记录。

提交前读回事件，核对正文、派生字段和重要性；成功返回日记、整理记录、任务 ID 与事件数。再次使用同一个已提交包会因数据库状态变化停止，避免重复替换。连接或提交错误后先核对数据库状态，不盲目重试；不得输出连接串、密钥或包含这些信息的异常全文。

## 调用与环境

源文件保留在仓库 `skills/diary-organizer`。按路径读取执行可直接使用；若需要技能选择器或 `$diary-organizer`，先核实宿主注册情况。Codex 的仓库发现目录为 `.agents/skills`，可按需用链接指向当前源目录，不复制维护两份。本 Skill 的 `allow_implicit_invocation: false` 只控制隐式调用，不代表已经注册。本次工作不自动修改安装配置。

纯文本整理无需 Python 或数据库；转换只需 Python 标准库；项目导出、预检和保存使用 `backend/venv/bin/python` 及项目后端依赖、配置和数据库网络访问。人物资料已提供时直接使用，不额外联网读取。
