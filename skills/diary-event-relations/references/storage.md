# 完整入库包与关系发布

识别、修订、准备入库包和默认预检均不写数据库。正式保存采用短事务，不调用模型、不重新提取或保存要点和向量。以下命令在项目根目录执行，`RUN_DIR`、`PACKET` 和 `HASH` 替换为实际路径及输出指纹。

## 准备与预检

完成全部事件对并交付当前 `关系结果.md` 后执行；该文件是实际转换来源，缺失或解析失败时不会使用旧 JSON 缓存：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py prepare-storage RUN_DIR --markdown RUN_DIR/关系结果.md --username x5456
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py save PACKET --username x5456
```

第一条直接解析 Markdown 并校验全部事件对、端点和证据，再生成 `入库包-事件关系-指纹.json`，并只读复验当前数据库。第二条再次预检；没有 `--write` 不会保存。检查 `ready_to_publish`、`skill_source_supported`。`missing_published_dependencies` 为兼容旧调用保留，固定为空，不再用于阻止入库。输出文件不覆盖已有包，可以用 `--output` 指定新路径。来源变化须新建识别运行；结果修订则重新生成入库包，旧包保持不变。

版本 2 的包另含完整 Markdown 快照及原始文字 SHA-256，解析结果必须与包内判断逐项一致。正文、引文或格式变动均改变稿件／完整包指纹；语义内容变动另改变最终结果指纹。包中只记录稿件路径用于追溯，正式保存使用包内已冻结全文，独立包不依赖本地稿仍存在。改稿后必须重新 prepare-storage，以新包对应的稿件执行保存。

包包含用户与当前日记／运行身份、候选和完整来源快照、原始判断、映射真实 UUID 的全部判断、引用原文及 Unicode 码点偏移、要点详情指纹、规则版本和发布依赖。保存时仅需此 JSON、项目脚本和数据库，不读取原识别目录或回放依赖的本地目录。文件中的本地路径仅保留来源追踪用途。

- `source_package_sha256`：冻结事实、召回清单、规则和回放来源版本。
- `results_sha256`：来源指纹加按事件对排序的最终判断；绑定类型、方向、理由、描述、双方真实身份及证据。修订其中任何内容都会改变它。
- `storage_sha256`：绑定整个独立入库包，包括用户定位及依赖。哈希检测变化，不证明语义正确，也不代替授权。

结果来源映射：关系表使用长度适配现有字段的 `SKILL_AGENT`；checkpoint 保留完整来源 `SKILL_AGENT_REVIEW`。旧 `AGREEMENT`、`ADJUDICATED` 保持有效。

## 整稿确认

完成当前稿及只读预检后，展示完整稿或文件链接、目标日期、关系数量与发布依赖范围，等待用户确认。只有用户确认当前整稿（在已约定入库任务中），或明确要求按当前稿入库，才执行正式写入；已有确认与授权不重复询问。局部确认、澄清回答、讨论设计或要求开发不视为整稿确认。确认后稿件内容或入库范围变化，须重新预检并确认变化后的版本。指纹绑定稿件版本，不代表用户已经确认；未回复、默认选中或超时不算确认。

## 迁移与正式保存

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py schema
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py schema --write
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py save PACKET --username x5456 --write --confirmed-sha256 HASH
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py storage-status PACKET --username x5456
```

`schema` 默认只读；`schema --write` 执行固定迁移 `backend/migrations/052_skill_event_relations.sql`，可重复执行，旧约束偏离预期则停止。正式环境执行迁移和保存须在用户授权范围内；已经明确授权的操作无需再次索取同一授权。入库包准备不能隐含授权写入。

保存前锁定用户及来源行，拒绝活动图谱／整理任务，重新检查用户、来源修订、全部事件、要点和向量。默认当前目标须是 `POINTS_READY`；已发布同一包时幂等返回。用户明确要求以当前稿替换已发布稿时，准备、预检和保存均加 `--replace-published`：同一事务先将旧发布归档、旧关系和证据保存到 checkpoint 的 `skill_relations_history`，再替换关系；失败整体回滚。没有此参数仍拒绝覆盖。

旧回放稿默认要求历史发布的来源及结果指纹一致。用户明确接受历史稿版本差异时，可在准备、预检和保存中加 `--accept-published-revisions`；这只放宽历史关系判断的版本匹配，仍要求历史运行已发布、归属和日期合法、数据库事件／要点／向量与本稿来源一致。实际采用的参数写入新发布归档，不修改冻结来源。

一个事务内完成：

1. `RELATED` 写 `graph_event_relations`，双方要点写 `graph_relation_evidence`。
2. 在原 checkpoint 上增加 `skill_relations`，保留完整冻结快照、全部判断、理由、引用位置、结果与包指纹、依赖及关系 ID。`NO_RELATION` 和 `UNRESOLVED` 归档，不创建边。
3. 设置当前事件入图标志，将当前运行发布为 `PUBLISHED`。要点、向量、原任务状态及日记状态不重写。

任何一步失败全部回滚。`storage-status` 读取实际 checkpoint 确认同包是否已保存，允许规则后续变化后的历史查询。原 `render` 的 `stored_in_database:false` 表示本地导出本身不发布，实际数据库状态以此查询为准。替换仅支持当前同一运行的已有 Skill 发布，不自动重建要点运行或覆盖另一有效已发布运行。

历史版本 1 入库包保留并支持 `storage-status` 查询，不再允许直接写入；新写入使用版本 2。经用户授权替换旧发布时，从当前 Markdown 生成新包，旧归档保留在发布历史中，不篡改原入库包。

Skill 文件指纹仅保留追溯，不要求与当前版本一致，不因 Skill 改动拒绝准备入库包、预检或保存。包自身完整性、协议格式、来源及数据库状态检查仍执行；旧运行不会自动获得新规则的候选。
