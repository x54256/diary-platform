from pathlib import Path
from datetime import datetime,timezone
import json,sys,subprocess,collections,hashlib,shutil
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
SCRIPT=PROJECT/'skills/diary-event-relations/scripts/workflow.py';PYTHON=PROJECT/'backend/venv/bin/python'
sys.path.insert(0,str(SCRIPT.parent))
from draft import read_draft
receipt=json.loads((ROOT/'独立审核采纳记录.json').read_text());archive=Path(receipt['archive'])
for name in ['关系汇总.json','关系稿索引.md','十月关系稿.md']:
 shutil.copy2(ROOT/name,archive/(name.replace('.', '-更新前.',1)))
runs=json.loads((ROOT/'运行清单.json').read_text());counts=collections.Counter();types=collections.Counter();certainty=collections.Counter();rows=[];allrows={}
index=['# 十月事件关系稿索引','','已完成独立审核意见评估及修订；当前版本以本索引和运行清单为准。129事件、1086个既定候选；十月内部回放，同日完整比较，跨日相似度阈值0.4、Top 5召回。','','| 日期 | 候选 | 关系 | 无关系 | 未决 | 当前完整稿 |','|---|---:|---:|---:|---:|---|']
combined=['# 十月事件关系稿（阅读汇总）','','当前版本已按独立审核意见核实修订：105条关系（其中1条来源自述推测）、979个无关系判断、2条未决。仅本地稿件，未发布关系。全部无关系依据及机器身份信息见每日主稿。','',f"[逐项采纳判定]({ROOT/'独立审核采纳判定.md'})",'']
for run in runs:
 folder=Path(run['run_dir']);s=json.loads((folder/'source.json').read_text());md,data=read_draft(folder/'关系结果.md',s)
 check=subprocess.run([str(PYTHON),str(SCRIPT),'check',str(folder)],cwd=PROJECT/'backend',capture_output=True,text=True)
 assert check.returncode==0,check.stdout+check.stderr
 status=json.loads(check.stdout);assert status['complete']
 assert len(data)==len(s['pairs'])==status['total_pairs']
 c=collections.Counter(x['status'] for x in data);counts.update(c)
 for row in data:
  allrows[(run['date'],row['pair_id'])]=row
  if row['status']=='RELATED':types[row['relation']['relation_type']]+=1;certainty[row['relation']['certainty']]+=1
 verification=json.loads((folder/'verification.json').read_text());assert verification['verified_against_database'] and verification['package_sha256']==s['package_sha256']
 rows.append({'date':run['date'],'pairs':len(data),'counts':dict(c),'run_dir':str(folder),'verification':verification,'markdown_sha256':hashlib.sha256(md.encode()).hexdigest()})
 index.append(f"| {run['date']} | {len(data)} | {c['RELATED']} | {c['NO_RELATION']} | {c['UNRESOLVED']} | [关系结果]({folder/'关系结果.md'}) |")
 combined += ['## '+run['date'],'',f"[每日完整稿]({folder/'关系结果.md'})",'']
 for line in md.split('<details>')[0].splitlines():
  if line.startswith('# ') or line.startswith('<!-- relations_format:'):continue
  combined.append('##'+line if line.startswith('#') else line)
 combined+=['']
assert counts=={'RELATED':105,'NO_RELATION':979,'UNRESOLVED':2}
assert certainty=={'EXPLICIT':104,'SPECULATIVE':1}
# Verify modifications precisely; every other pair must stay as parsed from the previous current Markdown.
modified={(x['date'],x['pair_id']):x for x in receipt['decisions']}
old=json.loads((archive/'原运行清单.json').read_text())
for run in old:
 folder=Path(run['run_dir']);s=json.loads((folder/'source.json').read_text());_,data=read_draft(folder/'关系结果.md',s)
 for before in data:
  key=(run['date'],before['pair_id']);after=allrows[key]
  if key in modified:assert after==modified[key]['after']
  else:assert after==before,('范围外变化',key)
notes=['# 独立关系审核意见采纳判定','','主代理逐项重读磁盘当前关系主稿及双方完整要点后作出以下决定。11项实质意见全部采纳；C01采纳为来源自己提出的推测联系。没有把审核意见直接当事实，没有借第三事件补证。','','| 项目 | 决定 | 判断与实施 |','|---|---|---|']
for d in receipt['decisions']:
 notes.append(f"| {d['issue_id']} | {d['decision']} | {d['reason']} |")
notes += ['', '修订结果：新增7条关系（6条明确、1条推测）；收窄5条关系说明，原类型和方向保留；2条原未决不变。当前总数105关系、979无关系、2未决，1086候选均完整。','', 'R01只把“当天会从4S店开车来”的出行条件作为安排理由，不把修车完成的结果倒置为先前计划的原因。R03仍为挑选计划，R05只写AI声称做好，R06不把重复付款写成收货原因。C01保留本人未明原因及游戏玩腻的另一可能，不升级为确定因果。','', '5处说明覆盖不足采用删除非必要从句的方式，保留最小充分证据；没有为保留无关细节堆叠要点，也没有改动正式要点。','',f"修订前主稿、主稿解析、原运行清单与前后逐项记录：[备份及执行回执]({archive/'执行回执.json'})。受回放依赖影响，从10月10日起共11个日期新建运行，完整来源、候选、召回、配置与旧运行完全相同。全部check/verify/render成功；其他判断逐条核验未变化。",'',f"[当前关系阅读汇总]({ROOT/'十月关系稿.md'}) · [每日当前稿]({ROOT/'关系稿索引.md'})",'']
(ROOT/'独立审核采纳判定.md').write_text('\n'.join(notes))
(ROOT/'关系稿索引.md').write_text('\n'.join(index)+'\n');(ROOT/'十月关系稿.md').write_text('\n'.join(combined)+'\n')
report={'completed_at':datetime.now(timezone.utc).isoformat(),'revision':'独立审核意见采纳后','days':15,'current_events':129,'pairs':sum(r['pairs'] for r in rows),'same_day_pairs':571,'cross_day_recalled_pairs':515,'counts':dict(counts),'relation_types':dict(types),'certainty':dict(certainty),'stored_in_database':False,'rows':rows}
(ROOT/'关系汇总.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
points=PROJECT/'diary-event-points/批次评估/2026-10-20261023'
log=f"\n## 独立关系审核采纳修订完成\n\n{report['completed_at']}：用户要求评估审核意见并执行采信修改。主代理核实采纳R01–R11，C01按来源自述推测采纳；新增7边、收窄5说明。当前105关系、979无关系、2未决。10月10日起11个日期依赖链新建并只读数据库复验，保留旧稿。逐条核验范围外判断未改；未写关系数据库、未改要点或Skill。\n"
with (points/'流程留痕.md').open('a') as f:f.write(log)
completion=points/'完成报告.md';text=completion.read_text();shutil.copy2(completion,archive/'完成报告-更新前.md')
update=f"# 当前修订状态（独立关系审核采纳后）\n\n已评估并采纳11项实质审核意见，另将C01保留为来源自述推测。当前为**105条关系、979个无关系判断、2处未决**，覆盖1086候选；原300要点及向量入库结果不变。关系仍仅本地稿。\n\n[采纳判定与实施依据]({ROOT/'独立审核采纳判定.md'}) · [当前关系稿]({ROOT/'十月关系稿.md'})\n\n以下保留首次完成时的历史记录；其中98条关系是该轮修订前统计，最新统计以上文及关系汇总.json为准。\n\n---\n\n"
completion.write_text(update+text)
print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
