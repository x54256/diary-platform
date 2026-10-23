# 结果协议与修订

以 `read` 返回的 `package_sha256`、`pair_id`、事件别名及本事件内的要点序号为准，不靠标题映射 UUID。结果文件可以含本批或更少的已完成对，但每个事件对只出现一次，不加清单外的对。

```json
{
  "package_sha256": "read 返回的完整指纹",
  "results": [
    {
      "pair_id": "read 返回的事件对标识",
      "status": "RELATED",
      "reason": "同一预约之后实际就诊，出现新的检查结果。",
      "relation": {
        "source_event": "E001",
        "target_event": "E002",
        "relation_type": "后续事件",
        "certainty": "EXPLICIT",
        "source_evidence": [{"point_no": 1, "quote": "我预约了周五的检查。"}],
        "target_evidence": [{"point_no": 2, "quote": "今天按预约完成检查。"}],
        "description": "此前预约的检查得到执行，产生了新的检查结果。"
      }
    }
  ]
}
```

以上纯为格式示例，标识、引文与经历不能直接复制到真实结果。

- 顶层只接受 `package_sha256/results`。每项只接受 `pair_id/status/reason/relation`。
- 状态为 `RELATED/NO_RELATION/UNRESOLVED`。后两种 `relation=null`，理由说明未发现的具体联系或缺失的事实；不要遗漏这些对。
- 关系只接受示例中的七个字段；两端恰为该对指定事件。方向不取决于 `event_a/event_b` 的排列。
- 两侧证据为非空数组，`point_no` 是当前侧事件中实际存在的整数，不接受布尔值、字符串或重复序号。每段 `quote` 必须是对应 `detail` 中唯一出现的连续原文，不改写、不省略中间文字；多次出现时延长原文片段。
- `reason` 是过程记录，`description` 是关系表达；都须非空。引用存在、编号正确只能证明位置合法，不能证明关系成立、证据充分或描述忠实。

## 分批保存与恢复

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py record RUN_DIR --input CURRENT_BATCH_RESULTS.json
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py status RUN_DIR
```

`record` 校验整个传入文件后才原子合并本地结果；无效项不造成部分写入。不完整任务允许保存已完成对，`status.complete=false` 并列出未完成对及批次；`read --pending-only` 只读尚未完成的对。不能将程序缺失项自动补成无关系。

相同结果重复提交幂等，不重复创建旧版或使阅读稿失效。已有对的内容不同默认拒绝；核实用户修订或事实问题后显式更新：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py record RUN_DIR --input REVISED_RESULTS.json --replace
```

变更保留旧 `results.json`，旧阅读稿及身份导出另存为 `*-previous-*`。修改 JSON 后需要重新 `check/verify/render`。并发本地保存使用文件锁，不能把这个锁视为数据库发布互斥。

## 可编辑关系稿与转换

`关系结果.md` 是存在后的主稿。脚本直接解析此文件，`results.json` 仅为批次缓存；无需 Agent 将人工修改同步为 JSON。`render` 首次从完整缓存生成稿件，后续调用只校验当前稿、更新身份导出，不覆盖人工内容。稿件改动会直接影响 `status/check`、回放依赖和入库结果；格式错误时停止，不退回旧 JSON。

正文只保留关系及未决。无关系置于末尾 `<details>` 折叠区，仍是主稿的一部分，完整保存逐对依据；不再另列一张重复全部关系及证据的总表。来源、配对及方向标识放在隐藏注释中。程序严格检查注释、可见端点名称及日期一致，不能删掉标识后靠标题猜配。

```markdown
# 2026-09-10 事件关系

<!-- relations_format: 1; package_sha256: 本次完整来源指纹 -->

## 关系 1

<!-- pair_id: 本次P标识; source_event: E001; target_event: E002 -->

来源：2026-09-09｜预约检查
目标：2026-09-10｜完成检查
类型：后续事件
确定性：明确

### 关系说明

此前预约的检查得到执行。

### 来源证据

#### 要点 1

> 我预约了周五的检查。

### 目标证据

#### 要点 2

> 今天按预约完成检查。
```

以上仅为格式示例，实际指纹、配对标识、标题、序号和引文必须来自本次来源。确定性只接受“明确／推测”，分别映射 `EXPLICIT/SPECULATIVE`。关系说明为最终描述；需要保留不同的判断依据时，在说明后增加 `### 判断依据` 和理由，未列时以关系说明同时作为理由，避免重复文字。

每侧支持多个 `#### 要点 N`；每段连续原文的每一行均加 `> `，引用内的空行写为 `>`（也接受 `> `），避免编辑器清理行末空格后无法转换。短引不改字，程序校验其在该要点详情中唯一出现。引文中的 Markdown、竖线和空行保持原样，不能为解析方便改写来源。

未决格式：`## 未决 1`、仅含 `pair_id` 的隐藏注释、`事件甲：日期｜原标题`、`事件乙：日期｜原标题`、`### 判断依据` 及具体缺口。无关系同样结构，标题改为 `## 无关系 1`，放在以下区域，各类分别从 1 连续编号：

```markdown
<details>
<summary>无关系判断（N 对）</summary>

此处为完整无关系条目，数量须与 N 相符。

</details>
```

脚本拒绝未知栏目、额外代码围栏、非预期注释、重复事件对、端点错配和不合法引用。完整稿必须覆盖全部候选，不能把删除条目解释为无关系；要改变状态须显式改成相应格式。零候选只有日期与来源注释，零关系可只有未决或无关系区。

## 分批 Markdown 与离线转换

批次 Markdown 使用同一日期和来源注释，只列本批已判断事件对；`record` 允许部分覆盖：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py record RUN_DIR --markdown BATCH.md
```

重复对有不同内容时，核实后使用 `--replace`。批次合并保留旧缓存及旧完整稿，完成全部候选后 `render` 生成新完整稿。最终完整稿已有人工修改时直接编辑它，不从旧缓存重新生成。

单独转换不访问数据库、不调用模型、不改写 Markdown：

```bash
backend/venv/bin/python skills/diary-event-relations/scripts/workflow.py convert RUN_DIR --markdown RUN_DIR/关系结果.md --output RUN_DIR/关系结果.json
```

`convert` 要求完整覆盖，输出不覆盖已有文件。转换结果是派生产物，不是必须维护的第二份主稿。最终入库的 `prepare-storage` 自带相同解析，无需先执行 convert 或导入 JSON。

完整稿改动前保留旧文件，读取磁盘当前版本后核对来源及用户意见。新增事实超出要点时，先修订正式要点并新建来源，不能篡改冻结快照或指纹。已发布结果的改写仍属于重建，当前保存器不会覆盖已发布稿。

## 交付与整稿确认

向用户展示当前完整关系稿或可阅读链接，完成只读预检后等待整稿确认，再执行已约定的入库。用户明确说“按当前稿入库”同时表达当前稿确认及写入授权，无需重复询问；确认局部修改或回答澄清问题不代表整稿确认。确认后内容或范围变化须确认新版本。

事实澄清按 [澄清说明](clarifications.md) 执行。实际问题及回答放在独立 `澄清记录.md`，不把问答小节加入可解析关系稿。回答触及来源外事实时先走要点修订；明确跳过且缺口仍在则保留未决。完成澄清后展示当前完整稿，回答问题不算整稿确认。
