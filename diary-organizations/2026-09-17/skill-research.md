# 日记整理 Skill 通畅性漏检调查

调查日期：2026-10-21。范围：本次日记整理执行记录、Skill 的复读规则及评估用例，以及公开的一手研究。没有修改 Skill、日记稿或数据库；没有做新版提示词对照试跑。

## 结论

本次有直接证据支持的结论是：执行没有达到 Skill 已明确规定的通畅性标准。不能把问题归因于 Skill 没写检查要求。

Skill 的检查方式仍有改进空间：它列出了检查维度，但检查结果主要依赖模型自己的判断。可以尝试让检查更具体、更容易发现问题，再通过语义评估验证。公开研究支持这种改进方向，但不能证明它必然解决本次中文日记任务，也不能证明当前模型失败的内部机制。

## 本地一手证据

- [组织最终表达](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:80)允许充分调整句式，使内容自然通顺；保真并不要求保留残缺的口述句式。
- [交付前复读检查](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:93)已要求每轮重读完整稿，并检查自然通顺、指代、事件归属、段落衔接和时间关系，不能只看语法成立。
- [修改范围约束](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:48)要求只改本轮涉及的位置；[复读范围](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:95)又要求每轮检查完整稿。两者有解释空间，应区分用户明确限定修改范围和一般澄清后的全文质量检查；但它无法解释初稿已经存在的生硬句子。
- [当前稿](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:107)仍有“所以没有和王振洲开会对”，属于没有充分改写的口述表达。根据原文已有“对一下”的动作，可写成“所以今天没能和王振洲一起对一下，准备明天早上再对”，不必追问，也不必补造新事实。
- [当前稿](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:47)的“那个”指代不够明确；但原文本身含混，不能为了清楚就擅自指定为沥水盆或赠送活动。是否必须追问，应按关键性判断，不能把保留不确定性本身认定为违规。
- [当前稿](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:85)的“就算是”衔接较生硬，但仍可理解为退一步讨论不同视角，并不足以断言存在逻辑矛盾。上一轮回复将不同性质的问题并列举出，区分不够准确。
- [E19—E21](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/evals/cases.json:223)已经覆盖无疑问初稿、澄清后完整稿复读，以及不得为通顺补因果。存在用例不代表本次已经运行并通过这些用例。
- [保存说明](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/references/storage.md:39)明确脚本不判断语义保真；本次转换和预检通过不能证明文稿通畅。

当前 Skill 的日期定位说明相较本次早先读取时已有变化；本调查对复读规则的归因以会话中早先已实际读取的相同要求为依据，不把后来的定位功能视为当时已有。

## 网上研究

### 1. 自检有效性取决于反馈质量

[Self-Refine（2023），第 2、4 节](https://arxiv.org/html/2303.17651v2)将生成、反馈和修改分成步骤，并要求反馈指出具体片段和可采取的动作。其消融实验发现，具体反馈通常优于泛泛反馈；文中也记录反馈错误、忽略反馈和修改引入新问题的情况。

对本项目的启发：检查时应找到具体有问题的表达，再决定直接改写、保留不确定性或澄清；不能把“已复读”当成质量证明。这是应用建议，尚未在本项目实测。

### 2. 不能把自我纠错当作可靠保证

[Large Language Models Cannot Self-Correct Reasoning Yet（2023，2024 修订）](https://arxiv.org/abs/2310.01798)报告，在其推理任务与模型条件下，没有外部反馈的自纠错可能无效甚至退步。

[When Can LLMs Actually Correct Their Own Mistakes?（TACL 2024）](https://arxiv.org/abs/2406.01297)进一步区分自评、外部反馈和训练条件，并指出已有研究的实验设置可能高估自纠错效果。

这些结果不能直接证明现代模型不会润色中文日记；它们支持的是避免承诺“只要加一条自检要求就一定可靠”。

### 3. 多项约束需要分别评估

[ComplexBench（NeurIPS 2024）](https://arxiv.org/abs/2407.03978)发现其受测模型在多约束组合上仍有明显不足，并采用规则增强的评估方式。

[DeCRIM（EMNLP 2024）](https://aclanthology.org/2024.findings-emnlp.458/)把要求拆成约束，由 Critic 定位何时、何处需要修改，在其基准上提高了指令遵循表现。

对本项目的启发：保真、通畅、计划提取、重要性和保存状态应分别核对，不能以格式通过替代其他维度。Critic 是一种可测试方案，不代表必须增加代理或固定调用次数。

### 4. 长上下文是可能风险，尚非本次根因

[Lost in the Middle（2023）](https://arxiv.org/abs/2307.03172)在多文档问答与键值检索中观察到相关信息位置影响表现。

它支持关注规则在长上下文中的可用性，但未研究本项目的日记润色；不能据此断言“Skill 太长就是根因”，也不能保证把条款移到末尾就有效。

## 建议的最小改进与验证

1. 保留现有保真和通畅标准，把复读动作简化为可执行的检查顺序：先检查句子与指代，再检查事件内时间和转折，最后核对标题及派生字段是否与正文一致。
2. 发现问题时定位具体文字：事实明确就改写；事实不明确则保持其不确定程度，只有关键疑问才提问。无需向用户输出内部检查过程或新增日常审计文件。
3. 若调整修改范围条款，明确“不得覆盖用户指定保留内容”与“澄清后仍须检查全文”的区别，防止把局部改名误当成免除全文检查。
4. 把本次残缺句式作为脱敏回归素材，并在原有 E19—E21、E11 上比较原版与候选版；使用可比模型和输入条件，多次运行并逐项检查。评估者核对具体产物，不能只采信模型自称检查完成。
5. 同时记录表达改善和保真退步；任何方案若变得通顺却新增动机、因果或对象，仍属失败。

尚未验证：缩短 Skill、增加示例、独立 Critic 或检查顺序改动，在本项目中哪一种最有效。当前没有足够证据给出通过率、归因比例或保证。
