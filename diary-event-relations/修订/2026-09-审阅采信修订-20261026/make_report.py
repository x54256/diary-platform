import json,sys,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
import workflow as w
from draft import read_draft
state=w.read_json(ROOT/'execution.json');old=w.read_json(PROJECT/'diary-event-relations/批次评估/2026-09-全量回放-20261023/execution.json')
def link(t,p):return f'[{t}](<{Path(p).resolve()}>)'
def table(h,rs):return '\n'.join(['| '+' | '.join(h)+' |','| '+' | '.join(['---']*len(h))+' |']+['| '+' | '.join(str(x).replace('|','\\|').replace('\n',' ')for x in r)+' |'for r in rs])
newbydate={d['date']:d for d in state['days']};index=[];relations=[];checks=[]
for d in old['days']:
 updated=d['date']in newbydate;nd=newbydate.get(d['date'],d);folder=Path(nd['run_dir']);s=w.read_json(folder/'source.json');_,rows=read_draft(folder/'关系结果.md',s,complete=True)
 w.check_rows(s,{'package_sha256':s['package_sha256'],'results':rows})
 c=Counter(r['status']for r in rows)
 item={'date':d['date'],'diary_id':s['diary_id'],'run_dir':str(folder),'revised':updated,'current_draft':str(folder/'关系结果.md'),'pairs':len(rows),'counts':dict(c),'package_sha256':s['package_sha256'],'draft_sha256':hashlib.sha256((folder/'关系结果.md').read_bytes()).hexdigest(),'verified_in_this_revision':updated}
 if updated:
  w.load_package(folder);receipt=w.read_json(folder/'verification.json');assert receipt['package_sha256']==s['package_sha256'] and receipt['verified_against_database']and not receipt['stored_in_database'];item['database_verified_at']=receipt['verified_at'];item['top_k']=s['config']['top_k']
 index.append(item)
 for r in rows:
  if not r['relation']:continue
  rel=r['relation'];a=s['events'][rel['source_event']];b=s['events'][rel['target_event']]
  relations.append({'judged_on':d['date'],'pair_id':r['pair_id'],'source_event_id':a['id'],'target_event_id':b['id'],'source_date':a['diary_date'],'target_date':b['diary_date'],'source_title':a['title'],'target_title':b['title'],**rel,'draft_path':str(folder/'关系结果.md')})
totals=Counter()
for i in index:totals.update(i['counts'])
assert sum(totals.values())==1030 and totals['RELATED']==156 and totals['UNRESOLVED']==3
w.write_json(ROOT/'当前稿件索引.json',{'generated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'scope':'19篇；8篇新修订运行+11篇保留旧稿，不意味着未改11篇已按当前数据库历史规则重跑','totals':dict(totals),'days':index})
w.write_json(ROOT/'当前关系汇总.json',relations)
# 实际提问材料及实际回答，来源不修改。引文由冻结要点读取；问题显示词句保存在本次记录。
questions=[
 {'id':'C01','state':'已解决','question':'9月17日是在继续处理9月3日要求重整的这批基础指标需求和数据，还是江西项目中的另一事项？这与已确认的9月9日另一次纸上整理不是同一个问题。','answer':'江西项目的另一事项','options':['继续处理这批基础指标数据','江西项目的另一事项','不记得，保留未决'],'points':[('2026-09-03','江西评估指标和数据反复出问题，梳理文档留痕并划清工作边界',17),('2026-09-17','江西数据工作准备明早再和同事对一下',1)],'effect':'两对RELATED改为NO_RELATION，仅撤除同一批事项的推断，不改正式要点。'},
 {'id':'C02','state':'已解决','question':'两处书名不同，但都说昨天听书。指同一本书的同一次解读，还是不同材料？','answer':'同一本书、同一次解读','options':['同一本书、同一次解读','不同材料','不记得，保留未决'],'points':[('2026-09-20','学习普通心理学并建立知识联系',1),('2026-09-20','规划每日学习与作息安排',3)],'effect':'一对NO_RELATION改为RELATED／提及；身份消歧后仍使用双方原要点证据，不改书名。'},
 {'id':'C03','state':'待回答','question':'这里的《简单心理学》指同一门普通心理学课程，还是另一门课或书？','answer':None,'options':['同一门普通心理学课程','另一门课或书','不记得，保留未决'],'points':[('2026-09-09','刷老梁的视频，又陷入光看不做的状态',4),('2026-09-18','学习心理学及探讨学习目的',1),('2026-09-20','规划每日学习与作息安排',2)],'effect':'三对原NO_RELATION先改为UNRESOLVED；不因名称差异排除，也不擅认同一课程。'}]
allpoints={}
for i in index:
 s=w.read_json(Path(i['run_dir'])/'source.json')
 for e in s['events'].values():allpoints[(e['diary_date'],e['title'])]=e
clar=['# 审阅后澄清记录','','本文件记录本轮实际提出的三项问题，用户仅回答前两项；不代表整稿确认或入库授权。','','提问使用交互工具，日期／标题、要点编号和以下相关详情在题内展示；本记录保留材料与选项。C03题内第二章名称使用单引号排版，以下按来源原字展示。','']
for q in questions:
 clar+=['## '+q['id']+'（'+q['state']+'）','']
 for date,title,n in q['points']:
  e=allpoints[(date,title)];pt=next(p for p in e['points']if p['no']==n);clar+=[f'{date}｜{title}｜要点 {n} 原文：','']+['> '+line if line else '>'for line in pt['detail'].splitlines()]+['']
 clar+=['问题：'+q['question'],'','实际选项：'+'／'.join(q['options']),'','用户原话：'+(q['answer']or'待回答'),'','采用方式：'+q['effect'],'']
clar+=['仍待回答：C03。当前整稿未获入库确认，本轮没有入库。','']
(ROOT/'澄清记录.md').write_text('\n'.join(clar));w.write_json(ROOT/'澄清状态.json',questions)
for date in ['2026-09-17','2026-09-20','2026-09-22']:
 folder=Path(newbydate[date]['run_dir']);(folder/'澄清记录.md').write_text('\n'.join(clar))
# 继承旧记录，避免把已回答Q01/Q02遗失在当前运行之外。
for d in state['days']:
 previous=Path(d['old_run_dir'])/'澄清记录.md'
 if previous.exists():
  target=Path(d['run_dir'])/'澄清记录.md'
  if not target.exists():target.write_text(previous.read_text())
  else:target.write_text(target.read_text()+'\n## 前次运行记录（原样保留）\n\n'+previous.read_text())
changes=w.read_json(ROOT/'已有候选修改记录.json');pool=w.read_json(ROOT/'新增配对与事件.json');judgments=w.read_json(ROOT/'新增候选逐对判读.json')
keys=['F01','F02','F03','C01','C02','C03']
adoption=[['F01','采信并修改','下班条目明确回顾已将问题记进文档；新增下班条目→江西文档的提及。'],['F02','采信并修改','无关系理由串成父母AI沟通，改成实际两端：平台恢复动力与江西需求。'],['F03','采信并修改','工作条目明确回顾周三取咬合垫回家；新增工作条目→取垫的提及，不补因果。'],['C01','经回答采信并修改','用户确认9月17日为另一事项，撤除接到9月1日、3日旧需求的两条后续。'],['C02','经回答采信并修改','用户确认同书同次解读，新增每日安排→听书知识联系的提及。'],['C03','采信存在歧义，保留未决','《简单心理学》是否此前课程尚未回答，三对暂列未决；不是确认漏边。'],['R01','采信并补入新运行','母亲催生争论→次日豆包式回应总结，后续事件。'],['R02','采信并补入新运行','离职日期未定→继续工作压力及明确离职建议，后续事件。'],['R03','采信并补入新运行','清远可带宠物酒店预订及计划→实际出发入住，后续事件。']]
manifestrows=[[i['date'][5:],'新修订'if i['revised']else'保留旧稿',i['pairs'],i['counts'].get('RELATED',0),i['counts'].get('NO_RELATION',0),i['counts'].get('UNRESOLVED',0),link('完整稿',i['current_draft'])]for i in index]
report=f'''# 9 月关系稿：审阅采信与修订

已复核独立审阅报告，并将采信项落实到 **8 篇新运行**，保留原稿及其冻结来源。当前19篇索引共 **1,030 对：156 对有关系、871 对无关系、3 对未决**；未入库。

原889对中新增3条提及、撤除2条误连、修正1条理由、将3条有身份歧义的负例改为未决。召回补全带来的141对新增候选已逐对读完双方完整要点，得到16条有关系、125条无关系；其中包括报告R01～R03，另外13条来自扩大召回后的实际新增判断。没有把新增项默认填为负例。关系总数从139变为156，不代表准确率提升幅度。

## 报告逐项评估

{table(['项','结论','依据与执行'],adoption)}

三组召回遗漏的事实联系成立，但不应直接塞入旧冻结候选。已在新数据库来源运行中纳入它们。C01两条原后续缺少同一事项身份，用户确认是另一事项后撤边；C02只做听书身份消歧，仍由双方原文支撑提及。C03尚待回答，不能猜名称或要求用户决定关系类别。

## 当前完整稿索引

{table(['日期','版本','候选','关系','无关系','未决','当前完整稿'],manifestrows)}

上述8篇为本轮完成 `check → verify → render` 的新稿，使用当前skill指纹及数据库全部较早正式要点池。其余11篇保留已有稿，未冒称本轮重新复验数据库或按新历史规则全量重跑。9月20日另一个尚无正式要点的saved日记仍不纳入。

## 来源与范围控制

8篇新运行均逐项比较旧端点事件的完整内容，已复用的526对端点内容、要点及身份全部一致，重绑别名后保留未被本轮修改的判断。新来源覆盖数据库全历史，包括8月有正式要点的事件；新稿不再依赖旧replay稿的结论指纹。历史覆盖检查同时列出37篇7月8日至8月29日已整理但没有正式要点的日记，属于本次9月修订范围外；未补提取，不把它们算作已覆盖，详情保留在execution.json各日history_selection.gaps中。旧源、旧主稿、旧索引和独立审阅报告均不覆盖。

为保留原审核候选并纳入指定遗漏，每篇运行的top-k分别为 `{json.dumps({d['date'][5:]:d['top_k']for d in state['days']},ensure_ascii=False)}`，相似度阈值仍为0.4。配置仅绑定这些新运行，未修改skill全局settings。不是宣称这些参数已被证明最优。

## 验证和留痕

8篇新稿完成清单覆盖、关系端点、要点编号、唯一连续原文引文校验及只读数据库复验；主稿与派生身份映射均来自本轮最终判断。旧11篇仅对磁盘当前稿解析并汇总。结构校验不能替代独立事实真值。

首次本地只读连接受沙箱拒绝后按权限流程重试成功；不是数据库服务故障。没有写正式要点、向量、关系表，也没有修改skill或业务代码。实际宿主token仍不可得，记录为未知。

{link('逐项修改前后记录',ROOT/'已有候选修改记录.json')} · {link('141对新增判读',ROOT/'新增候选逐对判读.json')} · {link('澄清详情及回答',ROOT/'澄清记录.md')} · {link('执行和来源范围',ROOT/'execution.json')} · {link('校验调用日志',ROOT/'workflow-log.json')} · {link('当前稿件索引JSON',ROOT/'当前稿件索引.json')} · {link('当前全部关系JSON',ROOT/'当前关系汇总.json')}

本报告生成于 {datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}。本轮来源准备开始于 {state['started_at']}，新稿校验完成于 {state.get('finished_at')}；包含阅读、语义判断、澄清和重建，不标为纯推理耗时。
'''
(ROOT/'采信评估与修订索引.md').write_text(report)
print(dict(totals));print('revised',len(state['days']),'relations',len(relations),'existing_changes',len(changes))
