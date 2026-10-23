# 已确认事件要点入库

使用本 Skill 的 `scripts/store_points.py`，在项目根目录执行，Python 为 `backend/venv/bin/python`（3.11）。脚本切换到 backend 加载 `.env`，可通过全局 `--backend-dir` 指定其他后端路径。

## 职责与存储

输入是本次数据库来源快照及已确认的 Markdown。脚本核对来源、解析要点、准备向量，再保存到现有 `graph_run_events`、`graph_event_points`。运行状态记为 `POINTS_READY`，任务记为 `SUCCEEDED`；来源正文、日记状态和事件有效入图标志不修改。

保存本篇全部事件的要点；来源和稿件须完整覆盖当前日记的事件顺序。当前入口不覆盖已有有效结果。内容核对和用户确认如实记录为 `SKILL_USER_CONFIRMED`，不再生成或改写要点。

任务由脚本同步推进，使用专属执行环境，保留执行权、租约和心跳，不交给应用默认 worker。候选和向量先保存在 checkpoint，全部准备完成后再以短事务写正式要点，避免保存半套结果。

## 稿件格式

```markdown
# 日期与说明（可选）

来源说明（仅在首个事件之前）。

## 事件：原标题

<!-- event_id: 真实来源事件UUID -->

### 1. 主旨

完整详情，可包含自然段。
```

事件 UUID、原标题及顺序须与 source.json 一致；每个事件从 1 连续编号。缺少 ID、重复 ID、空字段、未知结构标题、额外注释或代码围栏时停止，不猜配重名事件，不静默丢内容。必要时另存兼容稿，不覆盖历史文件。

## 1. 检查存储能力

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py schema
```

只读检查 `graph_runs` 是否接受 `POINTS_READY`。需要扩展时，在已授权的环境中执行：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py schema --write
```

仅执行固定的 `backend/migrations/051_event_points_ready.sql`：为现有状态约束新增 `POINTS_READY`，不新建表、不改动现有数据。事务锁保护并发，重复执行返回已支持；现有约束偏离预期则停止。普通 prepare/save 不自动迁移。

## 2. 只读预检

下面的 `RUN_DIR` 替换为实际运行目录：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py prepare \
  --source RUN_DIR/source.json \
  --markdown RUN_DIR/事件要点.md \
  --output RUN_DIR/入库包-仅要点.json
```

只读核对当前来源、用户归属、修订、完整事件范围、任务冲突、向量模型配置及输入预算，不调用外部服务。输出事件数、要点数及 confirmation_sha256。入库包绑定文字、文件及来源指纹、Skill 与向量配置指纹；不覆盖旧包，不含认证信息。

展示完整稿或链接和保存范围；用户已要求按当前稿保存时直接继续。指纹绑定内容版本，不能代替用户授权。

## 3. 复验或保存

默认只读复验：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py save RUN_DIR/入库包-仅要点.json
```

正式保存：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py save \
  RUN_DIR/入库包-仅要点.json --write --confirmed-sha256 CONFIRMED_SHA256
```

脚本同步准备向量并保存，不需要额外执行参数。向量沿用项目 `graph_embedding` 配置和模型标识，对完整 detail 请求 1024 维向量，验证有限数值及非零模长，保存实际调用审计。已知同用户、同日、同模型且详情完全相同的合法向量可复用，记录原运行和原要点 ID，不重复请求。

同包重试复用任务、候选身份及合法向量；超时进程的执行权可回收。保存前重新核对来源及当前候选与确认稿，事务中写入完整要点和向量；失败不保留半套正式结果。旧格式包拒绝写入，需生成新包。

## 4. 查询与恢复

```bash
backend/venv/bin/python skills/diary-event-points/scripts/store_points.py status RUN_DIR/入库包-仅要点.json
```

返回任务和运行 ID、状态、当前阶段、错误码、候选数、向量数、复用向量数、实际保存数及 stored。

- `stored=true` 且状态为 `POINTS_READY`：要点及向量已保存。
- 候选、向量已有部分结果：尚未完成全部保存。
- `FAILED`：核实实际错误后用同包保存命令恢复。

查询允许本地稿后续已修改，仍定位原包任务，也支持历史版本 2 入库包的状态查询。新包使用版本 3，完整保存全部事件；版本 2 包不能继续写入或恢复，须保留原包并重新预检，不能改指纹绕过检查。数据库、稿件或配置变化时重新预检并确认相应内容变化。连接或提交结果不确定时先查状态，不盲目重建任务。所有输出隐藏认证信息和数据库异常全文。

## 缺失事件的补充保存

已有有效运行但完整审阅稿中仍有未保存的事件时，使用 `scripts/supplement_points.py`。普通 `store_points.py` 仍拒绝覆盖已有有效要点，不能绕过它做整篇重建。补充脚本只支持原运行来源为 `EVENT_POINTS`、原任务已成功、稿件全部事件与当前数据库来源一致、现有要点逐字匹配且当前向量模型与原运行相同的情形。

输入清单为 JSON 数组，每项包含原 `run_id`、完整数据库 `source.json` 路径 `source`、已审阅完整稿路径 `markdown`。不需要重新提取文字，预检完整检查全部事件，只追加无运行节点、无正式要点的事件；部分保存、来源变更或旧内容不一致时停止，不覆盖补救。

```bash
backend/venv/bin/python skills/diary-event-points/scripts/supplement_points.py prepare --inputs INPUTS.json --output PACKET.json
backend/venv/bin/python skills/diary-event-points/scripts/supplement_points.py save PACKET.json
backend/venv/bin/python skills/diary-event-points/scripts/supplement_points.py save PACKET.json --write --confirmed-sha256 HASH
backend/venv/bin/python skills/diary-event-points/scripts/supplement_points.py status PACKET.json
```

默认只读。按已确认稿及用户授权执行正式保存；完整详情沿用冻结的 `graph_embedding` 服务生成 1024 维向量，不调用文字生成模型。每次实际向量请求以原运行的独立 `SUPPLEMENT_EMBED` 阶段归档，成功响应可用于同包恢复。不会重开原已成功任务、替换原运行或改变原要点身份。若自动审批要求明确外发目标与内容范围，先说明具体服务、要点范围和原因，再取得授权；已经取得的相同授权不重复询问。

全部向量就绪后，用一个事务复验并锁定用户、来源、原运行和原要点，追加所有日期的缺失节点及要点，更新 checkpoint 的 `point_work/vectors` 和独立 `point_supplements` 审计；失败全部回滚，同包保存幂等。原运行状态、原任务状态及原 `skill_relations` 保持。原运行已发布时仅让新增事件节点随该运行可见，不新增或修改关系边，记录新增事件尚未重新判断关系；原运行待发布时不设置有效入图标志。新增事件的关系识别仍走关系稿及用户整稿确认流程。

`status` 除新增要点数外，还检查原节点、要点文字、向量及原 checkpoint（扣除本次追加项）指纹保持一致。确认稿或脚本、向量配置变化须重新准备补充包；不覆盖旧包或用修改指纹的方式继续写入。

新补充包使用版本 2，来源仅包含事件身份与内容；历史包保持原样并支持 status 查询，继续写入须重新准备，不改旧包指纹。
