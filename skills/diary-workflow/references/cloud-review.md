# 云端先保存、人工审阅后续接

仅当用户调用完整 diary-workflow 且 `DIARY_DATA_MODE=api` 时执行本分支。调用即授权本篇整理与后续三阶段在无待澄清问题时经 Agent 完整自查、预检后保存；不要求用户逐稿确认。本分支的保存时机优先于总入口和子 Skill 的逐阶段整稿确认规则。单独调用子 Skill、本地 db 模式保留其原确认规则。授权原话、目标身份和后续实际通知写入流程记录，不把自动保存记录成用户已看过整稿。`--confirmed-sha256` 仍用于绑定实际保存包，不作为人工审阅证明。

## 1. 首次整理

按 organizer 内容规则生成完整整理稿。事实疑问先澄清；没有问题时复读、自查并预检，使用对应包与指纹直接保存。展示保存结果和完整稿链接，明确告知用户“整理已入库，请在应用中审阅和修改，完成后告诉我继续”。保存成功必须结束本轮，不执行要点导出、提取或创建下游任务。

接口模式 `store_diary.py save --write` 的回执包含同一事务内的整理快照，客户端自动将其写入 `diary-workflows/YYYY-MM-DD/日记ID/state.json`，阶段为 `waiting_user_review`。该快照是对照人工修改的基线。保存回执丢失或本地记录写入失败时先检查数据库；不能因为本地失败而重新整篇写入。

## 2. 人工审阅门槛

`status.py` 在 API 模式将“已整理但未完成联动复查”的下一阶段标为 `review`。此时不得按 `database_next_stage` 越过审阅。用户询问状态、普通恢复、回答局部问题均不等于通知审阅完成。用户明确表示“改好了，继续”“审阅完了，继续”才开始联动复查。

既有整理结果缺少 state.json 时，先导出当前结果并核实用户实际审阅情况；不猜测已审阅。收到实际通知后可恢复记录，但缺少原基线时必须通读全部当前事件与后续计划，不声称已取得原修改差异。

## 3. 读取、比较及联动复查

API 模式使用 python3；本地模式将其换为 backend/venv/bin/python。所有 SOURCE/PATCH/PACKET 路径须替换为实际文件路径，输出使用新文件名。

```bash
python3 skills/diary-organizer/scripts/review_diary.py export --diary-id 日记ID --user-id 用户ID --output SOURCE.json
python3 skills/diary-workflow/scripts/review_state.py start --source SOURCE.json --user-message '用户实际通知原话'
```

读取 state.json 中 baseline 和当前 SOURCE，按稳定 event_id 比较事件标题、body、feeling、reflection，另比较日记级 plans、introduction、trivia。可将 baseline 原样另存文件，通过下列纯本地命令列出变动字段：

```bash
python3 skills/diary-organizer/scripts/review_diary.py diff --before BASELINE.json --after SOURCE.json
```

按 organizer 的[通用复查规范](../../diary-organizer/references/revision-review.md)审阅全部当前事件与整篇后续计划，重点核对变动影响。保护人工修改。事实依据充分的联动修订直接执行；有实际歧义时提问，未解决前不结束复查或进入要点。

需要修订时写 changes.json，仅包含实际改动：

```json
{"events":[{"event_id":"真实事件UUID","feeling":["第一项感受。","另一项独立感受。"],"reflection":["有来源依据的反思。"]}],"plans":["更新后仍符合本人意图的计划。"]}
```

允许 event_title、body、feeling、reflection 和日记级 plans；未提供的字段保持当前值。用户对文件正文的明确修改可通过 body 保存。新增、删除事件或变更引入与琐事超出该定点入口时，先明确变动范围并使用已支持的整理方式，不猜配 ID。保存仍受应用来源锁定约束。

```bash
python3 skills/diary-organizer/scripts/review_diary.py prepare --source SOURCE.json --changes changes.json --output PATCH.json
python3 skills/diary-organizer/scripts/review_diary.py save PATCH.json --write --confirmed-sha256 对应指纹
```

来源变更会阻止旧包覆盖。先查询实际结果，再重新导出、核对，不能盲目重试。无联动修改时不发起写入。联动保存后重新 export 得到最终 SOURCE-FINAL.json。

写复查记录 REVIEW.json，source_sha256 使用最终导出指纹，事件 ID 清单覆盖全部当前事件；conclusion 记录具体修改和无需修改的依据，不伪造用户回答：

```json
{"source_sha256":"最终来源指纹","reviewed_event_ids":["当前全部事件UUID"],"plans_reviewed":true,"pending_questions":[],"conclusion":"具体复查结论与修订说明"}
```

```bash
python3 skills/diary-workflow/scripts/review_state.py finish --source SOURCE-FINAL.json --report REVIEW.json
python3 skills/diary-workflow/scripts/status.py --diary-id 日记ID
```

finish 只记录真实完成的复查，程序校验不代替语义判断。状态为 ready_for_points 后，status 重新读取数据库完整快照；有新修改仍返回 review，须重新 start、复查、finish。临进入要点前再次检查进度，入库包也须复验最新来源。

## 4. 后续三阶段

从最终数据库来源重新导出并生成要点，完成自查及只读预检。要点 prepare 增加 `--workflow-authorized`，包与任务记录为 SKILL_WORKFLOW_AUTHORIZED，区别于人工逐稿确认。保存命令仍使用 --write 和本包指纹。

依次完成要点保存、关系全部判断与冗余复核及发布、分析与行动规划保存。无待澄清问题时直接自查、预检、保存并进入下一阶段，不以“需要继续吗”或等待整稿确认结束。每阶段仍生成完整可审阅稿与文件链接，保存实际回执并更新流程记录。遇事实疑问、来源冲突或技术失败时停止相关操作并说明原因，恢复沿用原任务和对应包。

## 外发授权

进入要点前使用 store_points.py embedding-config 读取实际服务地址、模型及完整详情输入范围。提前明确应用 API 接收哪些日记数据、向量服务接收全部要点详情；记录本任务对此具体目的地和范围的真实授权。相同授权可复用；有变动时重新核实。云端由应用服务端执行向量生成，本地也可显式配置 API 模式。不得用服务端转发掩盖外发目的地，不伪造授权、不绕过自动审批。若审批拒绝，报告具体操作和拒绝理由，取得所需授权后再继续。
