# 事件来源导出与工作目录

## 统一设置

Skill 根目录的 `settings.json` 保存唯一的 `workspace_root` 设置，相对 Skill 根目录解析，与命令执行目录无关。本项目默认指向项目根目录 `diary-event-points/`；修改该设置影响后续导出，不自动搬动或覆盖历史任务。

每次导出创建：

```text
diary-event-points/YYYY-MM-DD/日记UUID/上海时间戳-随机后缀/
├── source.json       # 唯一数据库来源快照，含事件 ID 和选择范围
├── source.md         # 来源的阅读视图
├── run.json          # 来源指纹、事件清单、Skill 文件指纹
└── 事件要点.md       # 后续模型提取结果；导出脚本不生成语义要点
```

同日多篇按 UUID 区分，同篇多次处理按运行目录区分。只导出本次所需的事件正文、感受、反思及定位元数据，不导出账号认证信息、原始口述、引入、琐事或独立计划。

## 使用

从项目根目录执行，使用项目 Python 3.11 环境：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/export_events.py find \
  --username x5456 --date 2026-09-09

backend/venv/bin/python skills/diary-event-points/scripts/export_events.py export \
  --username x5456 --date 2026-09-09
```

日期有多篇时，先展示 `find` 返回的日记清单，再按用户选择执行：

```bash
backend/venv/bin/python skills/diary-event-points/scripts/export_events.py export \
  --username x5456 --diary-id 828580fd-50a7-4a15-9d80-7acfe7ec987e
```

- `--username` 必填，不能跨用户读取；不自动选择某个账号。
- `--date` 使用 `YYYY-MM-DD`，与 `--diary-id` 二选一。
- `export --event-id UUID` 可以重复指定，只提取所选事件；任何 ID 不属于目标日记时停止。
- 整篇导出全部事件。只有显式指定 `--event-id` 时才缩小生成范围，未选事件记录在 `excluded_events` 中；正式入库须另备整篇全部事件的来源和稿件。
- 后端位置需改变时在子命令前使用 `--backend-dir /绝对路径/backend`。脚本加载配置时临时切换到该目录，保证 `.env` 按后端目录解析，然后恢复原工作目录。不打印配置或数据库异常全文。
- PostgreSQL 使用可重复读、只读事务；SQLite 只用于隔离测试。脚本不提供任何数据库写入命令。

## 来源约束

仅导出未删除、属于指定用户、已有有效整理结果的日记。`is_dirty` 为真、整理来源修订号与原文修订号不一致、缺少整理结果、正文为空或数组格式错误时停止；不自动整理、不修库、不静默选旧稿。

正文、感受、反思从各自字段读取。字段为 JSON 字符串时先解析并确认是字符串数组；`body` 必须非空。字段读取失败不能逐字符拆开，也不能用标题代替正文。导出的快照及阅读视图只包含事件身份、顺序、正文、感受与反思。

导出使用同一数据库快照；任务期间以该冻结快照为依据，不重新查询后拼入另一版本。`source_sha256` 计算稳定来源内容，`run.json` 另记录来源文件和 Skill 文件的 SHA-256。指纹只能发现文件或版本变化，不证明语义忠实；本脚本不自动重新连接数据库判断快照是否仍为最新。

重复导出始终新建运行；原快照与历史要点不覆盖。脚本只生成确定性的来源文件，不能声称已经完成要点提取或模型核验。

## 既有本地试跑

早先从本地整理稿生成的 09-09 要点迁移至统一工作目录中该日记的 `legacy-local/`。它们仍属于本地稿来源的历史试跑，不能改写为新数据库运行的产物；其全部版本与原始指纹保留。需要按当前数据库重提取时，使用新导出的运行目录。
