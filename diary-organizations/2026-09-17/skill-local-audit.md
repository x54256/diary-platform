# 09-17 日记整理通畅性漏检：本地证据核对

核对时间：2026-10-21。范围仅为 Skill 主文件、评估说明、E11／E19—E21 和当前整理稿；没有访问数据库，没有改动 Skill 或日记，也没有运行模型评估。本文件是网上调研的本地证据补充。

## 有限结论

现有证据更支持“交付没有达到已有规则”，不支持“Skill 没有要求检查通畅性”。规则明确要求每轮完整复读、检查指代和叙事衔接，并允许直接修正事实明确的表达问题。不过，文本结果不能证明当时完全没有复读，也不能证明失败来自提示词过长、注意力分配或模型能力。它只能证明检查未充分落实到交付结果。

## 规则是否缺失

- [SKILL.md 第 80 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:80)允许充分调整句式使内容自然通顺，而非机械保留口述结构。
- [第 95—100 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:95)明确规定每轮展示前复读当前完整稿、无疑问仍须检查、覆盖全部字段；第 97 行直接列出自然通顺、指代清楚、事件归拢、段落衔接和时间关系。
- [第 99 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:99)规定事实含义明确的表达问题直接修正，只有尚不能解决的关键疑问才提问。因此，“没有更多澄清问题”不能替代文稿检查。

## 实际交付的对应证据

| 当前稿位置 | 可观察问题 | 可得结论 |
|---|---|---|
| [第 107 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:107)：“所以没有和王振洲开会对” | “开会对”保留生硬口述结构，核对动作表达不完整。 | 与自然通顺要求不符，是较明确的表达漏检。可在不改变事实的范围内调整句式；具体补词仍需依据原文。 |
| [第 47 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:47)：“连搜都搜不到那个了” | “那个”在盆、赠送活动等候选对象间不够清楚。 | 指代清晰度没有充分解决；不能仅凭用户确认平台是叮咚就填入搜索对象。是否必须追加澄清取决于原文上下文和关键性，本次限定核对没有读取原文，不能判定具体答案。 |
| [第 85 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/diary-organizations/2026-09-17/整理稿.md:85)：“我不知道他们是不是脑残粉。就算是，每个人看问题的角度可能也不一样” | “就算是”到“角度不一样”的让步衔接不够自然。 | 有编辑改善空间，但不能仅据当前稿认定应改成“不管是不是”等确定逻辑；这需要对照原文，以免重写用户判断。 |

## 规则是否冲突

存在需要判断的边界，但不是无法执行的直接矛盾：

- [优先级第 35—40 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:35)把事实与完整性置于可读性之上；[第 87—89 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:87)禁止为连接句子补造因果、消解不确定性。这限制的是改动含义，不是禁止润色。
- [第 48 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:48)要求保留用户修改、仅改本轮涉及位置；[第 95—100 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/SKILL.md:95)同时要求全稿检查并保护指定修改范围。若用户明确要求“只改一处，其他不改”，检查不等于可任意重写；但本次用户只回答三处名称，现有材料未显示用户要求保留上述生硬句子。

这些边界可以解释为何某些疑点需要谨慎，却不能直接证明它们造成了此次漏检。

## 已有评估覆盖及其限度

- [evaluation.md 第 14 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/references/evaluation.md:14)明确：契约检查不证明模型实际遵守语义。[第 20 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/references/evaluation.md:20)要求记录实际模型、运行条件、输出及证据，未运行标为未运行。
- [第 25、30 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/references/evaluation.md:25)把通畅性与全文复读列为评估维度，并指向 E19—E21 和 E11。
- [E11，第 140—147 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/evals/cases.json:140)：保护用户当前稿及指定修改范围。
- [E19，第 223—231 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/evals/cases.json:223)：无疑问初稿仍需自然表达、归拢信息、保留事实。
- [E20，第 234—246 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/evals/cases.json:234)：用户回答后复读完整稿，不能机械拼接答案；与本次场景直接相关。
- [E21，第 249—262 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/evals/cases.json:249)：通顺不能成为补因果或覆盖用户保留决定的理由。

本次仅核对用例定义，未执行以上用例；不能把“有用例”写成“已通过评估”。已有材料也不足以证明该 Skill 相对无 Skill 基线、旧版本或其他提示词更易失败。要做此归因，需要依照[评估说明第 32 行](/Users/x5456/Documents/workspace/XDATA-Project/0个人/diary-platform/skills/diary-organizer/references/evaluation.md:32)使用相同用例和可比条件试跑。

## 版本证据边界

工作区与 Git 暂存区的差异显示，当前未暂存修改主要包含按日期执行 `find` 及澄清记录格式扩充；通畅性检查段和 E19—E21 并不在该差异中。暂存区也有完整复读段。但暂存区不是前次模型执行时的已验证快照，不能据此倒推出执行时逐字版本。尤其不能把后来新增的 `find` 和记录格式要求归因为此前文本漏检的原因。本结论以当前可核对规则及交付结果为限。
