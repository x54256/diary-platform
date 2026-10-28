# 后续关系冗余检查：Skill内部必经步骤

初步事件对判断全部完成后，当前agent继续完成本节，不能把冗余候选交给用户独立审核，也不能只审几个样例。程序不调用外部模型；当前agent就是语义判断者。用户仍只确认最终完整关系稿。

## 1. 准备只读上下文

在项目根目录运行，`RUN_DIR`替换为本次真实目录：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py prepare RUN_DIR
```

要求初步结果完整且没有已经改成间接延续的条目。脚本读取当前用户、当前日期之前的有效正式要点和已发布后续边，排除本次当前运行，合并本批初步后续边。全部历史证据必须归属于有效事件和要点；来源或历史准入变化时停止，不静默忽略。

生成`redundancy-context.json`，包含完整初步判断、历史边和完整要点、候选边、替代路径及指纹。历史边以`H:真实关系UUID`标识，本批边以`C:pair_id`标识。只检查本批后续边，不修改历史边、召回或初轮语义结果。

输出`needs_review`、`pending_pair_ids`。没有替代路径的边保留初步结果。有替代路径只是需要语义复核，不能直接认定冗余。

## 2. 当前agent逐条完成语义复核

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py read RUN_DIR --pair-id PAIR_ID
```

返回待查直连、首次找到的路径、其端点完整要点和相关路径索引。路径索引默认每页50条，`next_index_offset`非空时用`--index-offset N`继续读取。不得将分页未读内容当作已核对。

还可按真实标识补读其他路径的完整边和完整事件：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py read RUN_DIR --edge-id EDGE_ID
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py read RUN_DIR --event-id EVENT_UUID
```

以待检查直连双方证据实际承接的事项为比较范围，检查事项、动作、对象、阶段与证据，不凭标题或事件图可达自动裁边。按以下顺序复核：

1. 读直连双方完整要点及所选证据，说明这条直连承接的具体事项；区分其中的子事项、行动安排或结果。不要求路径覆盖起点事件的全部要点。
2. 逐段读替代路径的关系说明、双方证据与完整要点，检查上述事项是否连续推进。一个事件或同一个要点可以包含多个事项；经过相同节点或引用同一要点，仍须检查前后边是否中途切换了事项。
3. 对照直连与路径，明确路径已覆盖什么、直连是否还有未覆盖的独立后续。仅覆盖其中一部分时，所读路径不足以替代整条直连。
4. 找到一条连续承接直连全部相关事项、且直连无额外独立承接意义的路径时，记为`INDIRECT_FOLLOWUP`。首条路径不充分时，按索引补读其他必要路径；完成必要检查后，仍有未覆盖的独立内容或各路径均切换事项时，记为`KEEP`。不能只因首条路径不充分就认定所有路径均不充分。

- 同一事项可以经历计划、实施、检查、补漏等阶段，也可以调整具体方案；动作、阶段或物品变化本身不构成保留直连的理由。须判断是否连续推进同一具体事项，以及直连是否另有独立内容。
- 允许分支和汇合，不能要求唯一前序。模型不审引发、提及的冗余，也不能顺便将它们过滤。
- 初步事实仍有关键歧义时，先按主Skill澄清并修订初步结果，然后重新准备；不能把未完成检查塞进KEEP来伪装完成。

部分承接、同一要点切换事项及正常阶段推进的边界，见[真实案例](examples.md#后续关系冗余的真实案例)。只迁移判断方法，实际任务仍须读取当前来源和路径。

模型输出文件格式：

```json
{
  "context_sha256": "prepare返回的真实指纹",
  "decisions": [
    {
      "pair_id": "本次待复核对标识",
      "decision": "INDIRECT_FOLLOWUP",
      "reason": "对照双方和路径证据所得的具体语义理由",
      "replacement_path": ["H:真实关系UUID", "C:真实pair_id"]
    }
  ]
}
```

`replacement_path`是单条路径的有序边ID，至少两条边，必须首尾连续、端点一致、不含自身且不成环。它表示模型已实际阅读并认可这条路径足以完整替代直连，不能只照抄程序输出而未审语义。`INDIRECT_FOLLOWUP`的`reason`须说明直连承接的事项、路径如何连续推进，以及为何没有额外独立内容；引用相关事件及要点编号说明依据。KEEP的`replacement_path`必须为`[]`，`reason`须指出路径未覆盖的独立事项或中途切换事项的节点及相关要点，说明为何保留。程序校验路径结构和理由非空，具体语义依据由agent核对。

可分批记录，脚本保留进度，但全部待复核对都必须有且只有一个当前决定：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py record RUN_DIR --input DECISIONS.json
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py status RUN_DIR
```

## 3. 程序检查最终保留路径，模型自动补审

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/redundancy.py finalize RUN_DIR
```

缺少任何决定就拒绝完成。所有拟过滤边同时排除后，每条模型认可的替代路径仍须完整保留。

若输出`repair_pair_ids`或finalize报“退回模型”，当前agent自行补读最终可用路径、修改该项认可路径，或恢复直连；修正决定时用`record --input ... --replace`，旧决定自动备份。继续检查直到`pending_pair_ids`和`repair_pair_ids`均为空。不需要用户逐条审核。

例如A→D首次找到A→B→D，但B→D也要过滤，模型应认可A→B→C→D并记录实际边ID。程序只验证模型认可的最终路径，不会擅自换一条未经语义审核的路径。

finalize保留原关系稿备份，输出`redundancy-final.json`和新的`关系结果.md`。间接延续以独立折叠区展示，包含理由及保留路径；不混成无关系。完整初步关系、证据和模型决定保存在复核归档中。

## 4. 最终交付和发布

完成后继续主流程`check/verify/render/prepare-storage`，展示最终完整关系稿、正式关系数及间接延续数。用户只确认这份完整稿，之后按已约定的授权保存。

新数据库运行自动标记`requires_redundancy_review=true`，未完成复核不能生成最终阅读稿或入库包。对旧运行显式执行本节后，也必须带完整复核报告才能准备新包。旧包历史查询保留兼容，不能声称它们已经执行本步骤。

独立入库包嵌入完整上下文和决定，不依赖本地复核文件仍存在。预检及正式事务重新检查整个冻结历史关系范围的新增、删除、证据和正式要点变化；不匹配就停止，不能沿用旧决定。

正式入库仅写RELATED边，INDIRECT_FOLLOWUP连同原始证据和替代路径归档至checkpoint。召回和初轮配对保持原样，正式关系表不新增类型或表。当前稿或来源变化需重新复核、预检；保留备份，不能改旧指纹继续保存。
