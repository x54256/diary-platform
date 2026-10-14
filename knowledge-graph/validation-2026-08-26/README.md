# 第一层知识图谱实验资料

本目录只保留能够说明方案演变、实验参数、关键结果和人工确认答案的材料。原始日记、向量、模型原始响应、失败重试、测试库导出和重复中间结果已于 2026-10-14 清理。

## 当前方案

1. [事件要点提取技术方案](../../docs/知识库/第一层/第一层事件要点提取技术方案.md)
2. [事件关系识别技术方案](../../docs/知识库/第一层/第一层事件关系识别技术方案.md)
3. [事件关系实验记录](../../docs/知识库/第一层/第一层事件关系识别方案实验记录.md)
4. [事件要点试错记录](./试错记录.md)

## 实验证据

[实验索引](./实验索引.md)按问题列出保留的报告、结果摘要和人工标签。模型原始响应不作为长期设计资料；需要复测时使用固定提示、配置和新的隔离输出目录重新执行。

## 固定资产

- 事件要点最终提示：`backend/scripts/fixtures/event_point_baseline.json`
- 事件关系最终提示：`layer1_relation_batch_prompt_v4.txt`、`layer1_relation_blind_verify_v3.txt`、`layer1_relation_adjudicate_v3.txt`
- 关系固定回归样例：`layer1_relation_regression_v3.json`
- 未见样本人工确认标签：`unseen-blind-verify-20261014/confirmed-reference-labels.json`

实验数据只证明对应模型、提示、样本和参数下的结果。最终提示修改后未重新测试的指标，在文档中继续标记为历史指标。
