import json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
load=lambda p:json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
publication=load(ROOT/'发布结果.json');verification=load(ROOT/'入库核验.json');state=load(ROOT/'入库执行清单.json')
assert publication['database_written'] and verification['relations']==335 and verification['unresolved']==0
bydate={d['date']:d for d in verification['days']}
changed={'2026-09-20','2026-09-22'}
for d in state['days']:
 d.update(stored=True,database_verified=bydate[d['date']])
 if d['date']in changed:
  folder=Path(d['draft']).parent;p=folder/'入库回执-20261026.json';backup=folder/'入库回执-20261026-C03修订前.json'
  if p.exists()and not backup.exists():shutil.copyfile(p,backup)
  save(p,{'batch_manifest_sha256':publication['manifest_sha256'],'packet':d['packet'],**bydate[d['date']],'verified_at':verification['verified_at'],'confirmation':'确认，按两份新稿更新入库'})
state.update(verified_at=verification['verified_at'],latest_publication_receipt=str(ROOT/'发布结果.json'),latest_verification_receipt=str(ROOT/'入库核验.json'))
save(ROOT/'入库执行清单.json',state)
oldbatch=PROJECT/'diary-event-relations/入库/2026-09至10-20261026'
p=oldbatch/'入库执行清单.json';backup=oldbatch/'入库执行清单-C03修订前.json'
if not backup.exists():shutil.copyfile(p,backup)
save(p,state)
revision=PROJECT/'diary-event-relations/修订/2026-09-审阅采信修订-20261026'
p=revision/'当前稿件索引.json';idx=load(p)
for d in idx['days']:
 if d['date']in changed:d.update(current_draft_matches_publication=True,pending_publication_reason=None,published_storage_sha256=bydate[d['date']]['storage_sha256'])
save(p,idx)
p=revision/'澄清状态.json';questions=load(p)
for q in questions:
 if q['id']=='C03':q.update(state='已解决并入库',answer='同一门普通心理学课程',effect='三对逐项复核为后续事件；用户确认两份新完整稿后原子更新入库，数据库35份稿335条关系、0对未决，旧发布归档保留。')
save(p,questions)
record='\n\n## C03 新整稿确认与入库完成\n\n用户整稿确认原话：确认，按两份新稿更新入库。\n\n两篇已在同一事务替换保存，旧发布归档保留。提交时间：'+publication['committed_at']+'；只读核验时间：'+verification['verified_at']+'。9月20日18条、9月22日14条，35份当前稿合计335条关系、0对未决。正式要点和向量未变。本项已解决并入库，无待回答问题。\n'
for p in [revision/'澄清记录.md']+[Path(d['draft']).parent/'澄清记录.md'for d in state['days']if d['date']in changed]:
 with p.open('a')as f:f.write(record)
links='\n'.join('- ['+d['date']+' 当前完整稿（'+str(d['relations'])+' 条）](<'+d['draft']+'>)'for d in state['days']if d['date']in changed)
summary={'drafts':35,'relations':335,'unresolved':0,'judgments':verification['judgments'],'evidence_rows':verification['evidence'],'changed_dates':sorted(changed),'added_relations':3,'months':{'2026-09':{'drafts':20,'relations':170},'2026-10':{'drafts':15,'relations':165}},'committed_at':publication['committed_at'],'verified_at':verification['verified_at'],'old_publications_preserved':True,'points_and_vectors_unchanged':True}
save(ROOT/'完成摘要.json',summary)
report=f'''# C03 澄清后的入库完成报告

用户已确认两份变更后的完整稿。9月20日、9月22日已在同一事务更新入库，原发布归档、原关系及证据保留在各自checkpoint的 `skill_relations_history` 中。

- 9月20日：16→18条关系，原2对未决已解决。
- 9月22日：13→14条关系，原1对未决已解决。
- 全部35份稿：**335条关系、0对未决**；其中9月20份170条、10月15份165条。
- 2,287对完整判断均已归档；正式关系证据722行。

课程身份回答仅用于消除称呼歧义，三对依据各自原要点分别判断：重新开始课程到形成具体学习时段、学完第二章后进一步安排时段、形成安排后继续学习视觉。未把课程安排写成已执行，也未声称后来仅在安排时段学习。未修改正式要点、原文或向量。

提交于 {publication['committed_at']}。随后独立只读核验全部35份的PUBLISHED状态、包与稿件指纹、完整判断、关系方向／类型／确定性／说明及双方真实证据，均与当前包一致。正式要点和向量的数据库行集摘要在事务前后及核验时一致。

## 当前稿与回执

{links}

[全量数据库核验](<{ROOT/'入库核验.json'}>) · [提交记录](<{ROOT/'发布结果.json'}>) · [完成摘要](<{ROOT/'完成摘要.json'}>) · [三对修改前后](<{ROOT/'修改记录.json'}>)

上一份332条关系／3对未决的入库报告属于修订前历史状态，保留原报告、原包和核验记录。本报告为课程澄清后的最新状态。
'''
(ROOT/'入库完成报告.md').write_text(report)
# 保留原预检与报告正文，仅追加最新状态入口，避免旧“待确认”文字被误认成当前状态。
for p in [ROOT/'澄清处理与新稿索引.md',oldbatch/'入库完成报告.md']:
 old=p.read_text();note='> 后续状态更新：C03已获整稿确认并入库，当前35份稿335条关系、0对未决。详见 [最新入库回执](<'+str(ROOT/'入库完成报告.md')+'>)。\n\n'
 if not old.startswith(note):p.write_text(note+old)
print(json.dumps(summary,ensure_ascii=False))
