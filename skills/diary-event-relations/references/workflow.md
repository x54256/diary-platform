# 数据库来源与识别工作流

在项目根目录执行，使用 Python 3.11：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py find --username x5456 --date 2026-09-09
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py prepare --username x5456 --date 2026-09-09
```

日期与 `--diary-id UUID` 二选一。同日多篇须先展示 `find` 清单再按 ID 定位；`find` 同时列出每篇的有效运行 ID，多个有效要点运行时，`prepare --run-id UUID` 明确选择。`--backend-dir /绝对路径/backend` 是脚本的全局参数，放在子命令前。

`prepare` 统一从数据库读取当前用户、早于当前日记日期的所有有效正式要点运行（`POINTS_READY` 或 `PUBLISHED`），无月份或最近天数限制。历史不要求已发布或已有关系稿，不接收 `--history-mode`、`--completed-run`。已有旧模式稿件保留为历史记录。

每篇有正式要点的历史日记必须有唯一有效运行；多个运行、过期来源或非法向量时明确失败。已整理但尚无正式要点的日期记入 `history_selection.gaps` 和完整覆盖清单；用户指定处理范围内的缺口先补齐，范围外只报告，不擅自扩展任务。仅保存、尚未整理的日记不属于历史事件池。来源包冻结全部历史运行清单及完整事件／要点／向量指纹，`history_selection` 给出实际范围与覆盖数量。

当前日及历史运行均使用全部来源事件；当天完整两两比较，历史事件共同参与相似度召回。旧运行若缺少部分事件要点，明确报告缺失并先补齐，不将部分覆盖当作全量成功。来源文件只保留事件身份、顺序、内容及向量指纹。

召回读取完整详情的已有向量，校验 1024 维、有限数值、非零模长和同模型标识。精确余弦计算后，先按历史事件聚合最大要点组合得分，再按相似度降序、事件 ID 升序取前 K 个历史事件；当前配置 `top_k=6`、最低相似度 `min_similarity=0.4`，另将事件对相似度大于或等于 `retain_all_min_similarity=0.5` 的全部历史事件纳入，不受K截断。两部分取并集并按事件ID去重，继续按得分降序、事件ID升序排列；每个当前事件分别召回。0.4至0.5之间的事件仅通过Top 6进入；0.5包含边界值。当天事件完整两两比较。候选相似度不是关系证据。向量不输出给 agent，不调用向量或语言模型服务。

当前实现以受用户和日期过滤的历史数据在 Python 中精确计算，适合当前个人库；不使用近似索引或提前截断要点。历史量增大时需评估内存与耗时，再改为数据库内精确计算，不静默改成近似召回。

## 多日处理与来源复验

每天独立从数据库准备来源，不依赖前一天的本地关系稿。按日期完成判断、核对和数据库复验后继续；历史关系稿的修订不会改变其他日期的要点召回资格。

`verify` 重新查询全部历史准入范围并比较清单和完整内容指纹，包含未被召回的事件。新增、删除、失效要点或向量变化会要求新建运行。识别完成只表示本地稿完成，不设置入图标志，也不发布关系。

## 运行文件

每次 `prepare` 都新建独立目录，不覆盖之前的任务：

```text
diary-event-relations/YYYY-MM-DD/日记UUID/上海时间戳-后缀/
├── source.json               # 真实身份、完整所涉要点、来源指纹、候选及规则版本
├── run.json                  # 批次清单、不可变文件哈希、准备时间
├── B001.json ...             # 事件别名、完整要点、指定事件对；无向量数组
├── results.json              # record 合并的批次缓存
├── verification.json         # verify 成功后的时点复验记录
├── results-backup-*.json     # 追加或替换前的旧版（已有结果时）
├── resolved-results.json     # render 导出的事件/要点 UUID 和引用位置
└── 关系结果.md               # 可编辑完整主稿，脚本直接解析入库
```

候选清单与来源快照绑定整个任务；Skill 文件指纹仅用于追溯，不与当前文件比较，也不因说明、设置或脚本变化而拒绝旧运行。旧运行继续使用其冻结候选和配置，需要应用新召回规则时另建运行。稿件生成后优先读取其解析结果；不存在才使用分批 JSON，格式错误不会降级使用缓存。哈希用于检测内容变化，不代替语义核验或用户授权。

## 读取与预算

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py status RUN_DIR
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py read RUN_DIR --batch B001 --pending-only
```

`settings.json` 的 `max_batch_chars=12000`、`max_pairs_per_batch=12` 是初始显示保护值，不是已证明最优的批大小。计量紧凑 JSON 的 Unicode 字符数（不是字节或 Token），批内去重事件；超限关闭当前批再继续。单对仍超限则准备失败，不创建半套目录；在新运行前调整设置或报告当前预算不能容纳，不截断。工具仍发生显示截断时补读完整批次文件的缺失部分，不能根据可见的一半作答。

## 完成与数据库复验

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py check RUN_DIR
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py verify RUN_DIR
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py render RUN_DIR
```

`check` 仅检查本地冻结包、依赖和全部配对是否已处理；不证明数据库仍是最新。`verify` 重新只读核对本包涉及的数据库运行、来源、完整要点身份和内容及向量指纹；它核对全部历史准入与内容指纹，但不重新执行召回，也不保证复验后未来不会变化。成功时记录复验时点；再次复验失败则移除旧成功记录。`render` 明确注明复验时点或尚未执行数据库复验。如果需要纳入之后新增的历史事件，应新建运行。

PostgreSQL 查询在可重复读、只读事务中进行；SQLite 只用于隔离测试，启用 `query_only`。本页识别命令均不写数据库；入库写操作另见 [入库协议](storage.md)，不启动原分析管线。网络权限错误按项目权限流程处理；异常不回显连接串、SQL 参数或认证信息。

稿件结构及不访问数据库的转换命令见 [结果协议](results.md#可编辑关系稿与转换)。`render` 不覆盖已有人工稿；`prepare-storage --markdown ...` 从当前稿件转换，不要求 Agent 同步 JSON。
