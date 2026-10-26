import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
R=Path(__file__).resolve().parent
load=lambda p:json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def link(t,p):return f'[{t}](<{Path(p).resolve()}>)'
state=load(R/'入库执行清单.json');pub=load(R/'发布结果.json');v=load(R/'入库核验.json');before=load(R/'预检.json')
assert pub['database_written']and len(v['days'])==35 and v['relations']==332 and v['points_unchanged']
state.update(database_written=True,publication_committed_at=pub['committed_at'],verified_at=v['verified_at'],publication_receipt=str(R/'发布结果.json'),verification_receipt=str(R/'入库核验.json'))
bydate={d['date']:d for d in v['days']}
for d in state['days']:
 d.update(stored=True,database_verified=bydate[d['date']]);receipt=Path(d['draft']).parent/'入库回执-20261026.json'
 save(receipt,{'batch_manifest_sha256':pub['manifest_sha256'],'packet':d['packet'],**bydate[d['date']],'verified_at':v['verified_at']})
save(R/'入库执行清单.json',state)
monthly={}
for month in ('2026-09','2026-10'):
 ds=[d for d in v['days']if d['date'].startswith(month)];monthly[month]={'drafts':len(ds),'relations':sum(d['relations']for d in ds),'judgments':sum(d['archived_judgments']for d in ds)}
old_edges=sum(d['database_target']['relations']for d in before['days'])
summary={'months':monthly,'drafts':35,'relations':332,'judgments':2287,'no_relation':1952,'unresolved_archived':3,'evidence_rows':v['evidence'],'all_published':True,'original_target_relations':old_edges,'net_target_relation_increase':332-old_edges,'points_and_vectors_unchanged':True,'replaced_publications':{d['date']:d['old_publication_preserved']for d in v['days']if d['old_publication_preserved']},'model_api_calls':0,'committed_at':pub['committed_at'],'verified_at':v['verified_at'],'atomic_transaction_seconds':pub['seconds']}
save(R/'完成摘要.json',summary)
rows=['| 日期 | 状态 | 关系 | 归档判断 | 证据行 | 当前完整稿 |','| --- | --- | ---: | ---: | ---: | --- |']
for d in state['days']:
 x=bydate[d['date']];rows.append(f"| {d['date']} | PUBLISHED／已核验 | {x['relations']} | {x['archived_judgments']} | {x['evidence']} | {link('关系稿',d['draft'])} |")
report=f'''# 9月、10月关系稿入库完成报告

已按用户授权将全部35份当前关系稿发布入库，并在提交后逐篇只读核验成功。**9月20份、167条关系；10月15份、165条关系；合计332条关系、716行双方证据。**

全部2,287对判断已归档：332对有关系、1,952对无关系、3对未决。未决及无关系不创建边。零关系稿也已完成发布、归档，并设置当前事件入图状态。

## 保存和核验

- 35份稿在**一个数据库事务**中按日期保存，提交于 {pub['committed_at']}；事务用时 {pub['seconds']:.2f} 秒。提交后核验完成于 {v['verified_at']}。
- 按照当前Markdown正文生成版本2入库包，没有重新判断关系、重提要点或生成向量。入库脚本调用模型API次数为0。
- 本轮最终使用的稿件SHA-256与此前预检、授权范围一致。没有为了适配当前召回规则增删稿件判断，也没有篡改冻结来源。
- 9月9日旧发布0条关系、9月10日旧发布3条关系已替换为当前稿6条、5条。旧发布归档、旧关系及证据保存在对应checkpoint的 `skill_relations_history` 中，原入库包和本地备份也保留。
- 目标运行原有3条关系，本轮目标集合最终332条，净增329条；不能把332说成净增数。8月已发布结果未改写。
- 逐篇核对PUBLISHED状态、完整入库包指纹、Markdown快照、全部归档判断、每条关系的方向／类型／确定性／说明，以及每行证据的真实要点归属。数据库当前结果均与入库包逐项一致。
- 正式 `graph_event_points` 全用户行集摘要在准备前、事务内提交前、提交后完全一致；确认正式要点和向量未变化。

## 入库脚本能力

Skill文件版本差异不再阻塞现有稿件。此次补充了显式 `--replace-published` 与 `--accept-published-revisions`：用户明确授权时可在保留旧归档后替换同一运行的旧发布，并接受历史关系稿版本差异；默认仍拒绝覆盖。事件身份、事实来源、原文证据、用户隔离、活动任务互斥、历史已发布状态及匹配入库包指纹检查均保留。没有执行数据库schema迁移。

现有工程测试54项：50项通过、4项要求独立一次性PostgreSQL测试库而跳过。新增隔离测试覆盖替换归档、替换幂等、证据写入失败后旧边及归档一起回滚，以及替换仍拒绝已变化来源；skill结构检查通过。正式数据库本轮通过实际事务发布和后续只读逐项核验，未用于破坏性故障注入测试。

## 已核验稿件

{chr(10).join(rows)}

## 回执

{link('完成摘要',R/'完成摘要.json')} · {link('事务提交记录',R/'发布结果.json')} · {link('逐篇数据库核验',R/'入库核验.json')} · {link('独立入库包及稿件指纹清单',R/'入库执行清单.json')}

每篇运行目录另有 `入库回执-20261026.json`。原本地 `render` 导出中的 `stored_in_database:false` 表示该导出动作本身未发布；当前真实状态以本次数据库核验和回执为准，不靠改写旧导出来表示成功。

早期 `入库预检与阻塞清单.md` 是版本限制尚未移除时的历史预检记录；随后用户明确要求忽略旧版本验证并全部入库，本报告与最终回执为当前状态。原稿和历史预检文件保留。
'''
(R/'入库完成报告.md').write_text(report)
print(json.dumps(summary,ensure_ascii=False))
