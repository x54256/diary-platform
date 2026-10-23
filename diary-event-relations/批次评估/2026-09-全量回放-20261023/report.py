"""从当前可编辑主稿与冻结来源生成交付评估；不连接数据库。"""
import json,csv,sys
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
from draft import read_draft
from workflow import load_package,check_rows,progress

def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def link(label,p):return f'[{label}](<{Path(p).resolve()}>)'
def pct(a,b):return f'{a/b:.1%}' if b else '—'
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ')for v in r)+' |'for r in rows])
def csvwrite(name,rows):
    with (ROOT/name).open('w',newline='')as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
state=load(ROOT/'execution.json');data=load(ROOT/'metrics.json');metrics=data['days'];ledger=[];checks=[]
for d,m in zip(state['days'],metrics):
    folder=Path(d['run_dir']);s,manifest=load_package(folder)
    _,rows=read_draft(folder/'关系结果.md',s,complete=True)
    check_rows(s,{'package_sha256':s['package_sha256'],'results':rows})
    assert progress(s,rows,manifest)['complete']
    assert len(s['completed_dependencies'])==len(checks)
    receipt=load(folder/'verification.json');assert receipt['package_sha256']==s['package_sha256'] and receipt['verified_against_database'] and not receipt['stored_in_database']
    checks.append({'date':d['date'],'run_dir':str(folder),'package_sha256':s['package_sha256'],'complete':True,'dependency_count':len(s['completed_dependencies']),'database_verified_at':receipt['verified_at']})
    m['initial_execution_wall_seconds']=d.get('original_wall_seconds',d['wall_seconds'])
    m['final_run_rebuilt']=bool(d.get('replayed_from'))
    m['final_run_wall_seconds']=d['wall_seconds']
    m['timing_note']='首次生成运行的区间；最终依赖重建耗时另列。首次区间不是纯模型推理时间，可能包含工具、复核、澄清等待。'
    for index,(pair,row)in enumerate(zip(s['pairs'],rows),1):
        assert row['pair_id']==pair['pair_id']
        if not row['relation']:continue
        r=row['relation'];a=s['events'][r['source_event']];b=s['events'][r['target_event']]
        ledger.append({'judged_on':d['date'],'pair_no':index,'pair_id':row['pair_id'],'relation_type':r['relation_type'],'certainty':r['certainty'],'source_event_id':a['id'],'source_date':a['diary_date'],'source_title':a['title'],'target_event_id':b['id'],'target_date':b['diary_date'],'target_title':b['title'],'description':r['description'],'source_evidence':r['source_evidence'],'target_evidence':r['target_evidence'],'draft_path':str(folder/'关系结果.md')})
    save(folder/'执行评估.json',m)
assert len(metrics)==19 and len(ledger)==139
save(ROOT/'final-check.json',{'checked_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'checks':checks,'note':'离线复核当前主稿、证据、配对覆盖、指纹及完整依赖链；沿用本轮各运行刚完成的只读数据库核验回执。'})
save(ROOT/'metrics.json',data);save(ROOT/'relations.json',ledger)
csvwrite('relations.csv',[{**r,'source_evidence':json.dumps(r['source_evidence'],ensure_ascii=False),'target_evidence':json.dumps(r['target_evidence'],ensure_ascii=False)}for r in ledger])
csvwrite('daily-metrics.csv',[{k:v for k,v in m.items()if not isinstance(v,(dict,list))}for m in metrics])
logs=[load(Path(c['log']))for c in state['commands']]
bycmd=defaultdict(lambda:{'calls':0,'seconds':0,'failed':0})
for c in logs:
    x=bycmd[c['args'][0]];x['calls']+=1;x['seconds']+=c['seconds'];x['failed']+=bool(c['exit_code'])
assert not any(c['args'][0] in ('save','migrate','schema')for c in logs)
counts={k:sum(m[k]for m in metrics)for k in ['current_events','current_points','total_pairs','same_day_pairs','historic_pairs','related','no_relation','unresolved','same_day_related','historic_related','cli_read_chars','batches']}
recalls=list(csv.DictReader((ROOT/'recall-ranking.csv').open()));buckets=Counter(r['bucket']for r in recalls)
wall=(datetime.fromisoformat(state['finished_identification_at'])-datetime.fromisoformat(state['started_at'])).total_seconds()
rawchars=sum(len(json.dumps(json.loads(c['stdout']),ensure_ascii=False,separators=(',',':')))for c in logs if c['args'][0]=='read' and not c['exit_code'])
fresh_events={}
for p in sorted(ROOT.glob('*-fresh.json')):
    for a,e in load(p)['events']:fresh_events[e['id']]=e
freshchars=sum(len(json.dumps(e,ensure_ascii=False,separators=(',',':')))for e in fresh_events.values())
summary={'scope':'2026年9月19篇已整理日记；按日期逐篇回放，不含无正式事件要点运行的09-20另一篇日记','counts':counts,'relation_types':data['relation_types'],'certainty':dict(Counter(r['certainty']for r in ledger)),'started_at':state['started_at'],'finished_identification_at':state['finished_identification_at'],'identification_end_to_end_seconds':wall,'cli_all_attempts_seconds':sum(c['seconds']for c in logs),'cli_by_command':dict(bycmd),'cli_read_chars_all_attempts':rawchars,'cli_read_chars_final_active_runs':counts['cli_read_chars'],'unique_fresh_event_count':len(fresh_events),'unique_fresh_source_json_chars':freshchars,'recall_buckets':dict(buckets),'actual_host_input_tokens':None,'actual_host_output_tokens':None,'actual_host_reasoning_tokens':None,'actual_host_cached_tokens':None,'actual_host_cost':None,'token_note':'本会话没有逐调用用量接口；未知值留null。字符数不是token，账户额度百分比也不能替代本任务实际用量。','additional_model_api_calls':0,'embedding_generation_calls':0,'actual_recall_rate':None,'actual_precision':None,'quality_note':'候选产出率是本轮agent判断分布；没有独立金标准，不能据此计算准确率或召回率。','database_written':False,'skill_sha256':metrics[0]['skill_sha256'],'generated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
save(ROOT/'summary.json',summary)
indexrows=[]
for d,m in zip(state['days'],metrics):
    indexrows.append([m['date'][5:],m['current_events'],m['current_points'],m['total_pairs'],m['related'],m['no_relation'],m['unresolved'],f"{m['initial_execution_wall_seconds']:.1f}s",f"{m['final_run_wall_seconds']:.1f}s" if m['final_run_rebuilt'] else '同首次',link('关系稿',Path(d['run_dir'])/'关系结果.md')])
main=f'''# 9 月日记关系稿与执行评估

已完成 **19 篇已整理日记、118 个事件、338 个正式要点**的逐篇回放。889 对候选全部给出显式判断：**139 对有关系、750 对无关系、0 对未决**。未入库，未修改日记、正式事件要点或 skill。

用户两次澄清均已处理：9 月 3 日与 9 月 9 日江西整理是不同事项，对应两对候选不建立关系；9 月 12 日与 9 月 25 日七百元饭钱属于同一顿饭，建立“提及事件”关系，保留未转款状态。

## 范围与阅读入口

9 月共有 20 篇日记。本轮覆盖有正式要点的 19 篇；9 月 20 日另一篇仍为 saved、没有正式事件要点运行（`fa916775-76aa-4701-883d-c4267cf2bc97`），按此前范围排除。不是漏处理，也不把它记作完成。日期缺口不等于缺少日记。13 篇此前缺少 LOW 要点的日记本轮来源审计均通过。

{link('139 条关系总览',ROOT/'关系总览.md')} · {link('召回评估与优化建议',ROOT/'召回评估.md')} · {link('澄清汇总',ROOT/'澄清汇总.md')} · {link('环境与异常记录',ROOT/'环境与异常记录.md')}

下表链接指向**最终当前稿**，每篇都保留有关系、无关系与未决栏，以及逐对判断依据；有关系项附方向和双端原文证据。后续人工修改以各篇 `关系结果.md` 为准，汇总文件是本次交付快照。

{table(['日期','事件','要点','候选','有关系','无关系','未决','首次运行区间','最终重建区间','当前稿'],indexrows)}

首次区间包括该次工具、判断与复核，非纯推理耗时；部分运行经澄清或证据修订重建，最终重建只复用经完整内容相等核验的语义判断，不能当作从零判断速度。两列不能相加代表总耗时。

## 耗时与 token

记录区间为 {state['started_at']} 至 {state['finished_identification_at']}，**{wall/60:.2f} 分钟**。这是关系识别至最终校验的端到端时间，包含澄清、修订和依赖重建；报告生成耗时另由文件时间及 `generated_at` 留痕。全部 {len(logs)} 次工作流调用合计 {summary['cli_all_attempts_seconds']:.2f} 秒。

实际宿主输入、输出、缓存、推理 token 和费用均无法从本会话取得，已明确留 `null`。没有用字符数或账户使用额度冒充 token。当前最终运行批次读取 {counts['cli_read_chars']:,} 个 JSON 字符，含历史事件重复；全部尝试含重建共 {rawchars:,} 字符。它们是 CLI 返回负载，**不等于发送给模型的完整输入，也不等于实际 token**。另外留存了去重显示的 {len(fresh_events)} 个事件的完整来源与字符统计，供后续接入真实计量后对照。

{table(['命令','次数','累计秒','失败次数'],[[k,v['calls'],f"{v['seconds']:.3f}",v['failed']]for k,v in bycmd.items()])}

## 验证与复现

19 篇均完成 `check → verify → render`；最终又离线核验当前主稿、来源与 skill 指纹、配对完整性、连续原文引证及完整历史依赖链。只读数据库核验回执均匹配最终来源包。核验保证来源一致与格式约束，不代替人工事实正确率评估。

每个最终运行目录含来源包、冻结候选、批次、可编辑主稿、核验回执、派生 JSON 和 `执行评估.json`。旧稿、失败日志和被替换的运行保留，不能混作当前结果。

{link('最终校验清单',ROOT/'final-check.json')} · {link('逐篇指标 CSV',ROOT/'daily-metrics.csv')} · {link('汇总 JSON',ROOT/'summary.json')} · {link('关系 JSON',ROOT/'relations.json')} · {link('全部历史排名 CSV',ROOT/'recall-ranking.csv')} · {link('逐条命令索引',ROOT/'execution.json')} · {link('来源覆盖审计',ROOT/'coverage-audit.json')}

skill 指纹：`{summary['skill_sha256']}`。本轮未优化或改写 skill；建议与执行事实分开记录。当前执行记录脚本仅用于本轮评估。
'''
(ROOT/'执行报告与稿件索引.md').write_text(main)
lines=['# 关系总览','',f'当前快照共 {len(ledger)} 条，实际判断与原文证据请打开对应日记主稿。总览不作为新的关系写入来源。','']
for d in state['days']:
    rs=[r for r in ledger if r['judged_on']==d['date']]
    lines += ['## '+d['date'],'',link('完整关系稿及证据',Path(d['run_dir'])/'关系结果.md'),'']
    lines += [table(['候选序号','类型','来源（日记日期）','目标（日记日期）','关系说明'],[[r['pair_no'],r['relation_type'],r['source_date'][5:]+' '+r['source_title'],r['target_date'][5:]+' '+r['target_title'],r['description']]for r in rs]) if rs else '本篇没有满足条件的关系。','']
(ROOT/'关系总览.md').write_text('\n'.join(lines))
recall=f'''# 召回评估与后续优化线索

本轮按日期接续历史，配置固定为相似度阈值 0.4、每个当前事件最多 5 个历史候选；同篇事件全部两两枚举。批次上限 12 对、12,000 字符。没有额外生成 embedding 或调用独立模型 API；语义判断由本会话 agent 完成。

## 实测分布

{table(['范围','检查对数','有关系','候选关系产出率'],[['同篇全部配对',counts['same_day_pairs'],counts['same_day_related'],pct(counts['same_day_related'],counts['same_day_pairs'])],['历史召回候选',counts['historic_pairs'],counts['historic_related'],pct(counts['historic_related'],counts['historic_pairs'])],['总计',counts['total_pairs'],counts['related'],pct(counts['related'],counts['total_pairs'])]])}

完整历史比较池共 {len(recalls):,} 对：{buckets['selected']} 对入选，{buckets['below_threshold']:,} 对低于阈值，{buckets['top_k_excluded']:,} 对达到阈值但被 top-5 截断。未入选的 6,014 对没有在本任务中逐对完成语义判断，CSV 中记为 `NOT_JUDGED`，不是“无关系”。历史池只含本轮已完成的更早日记，不涵盖 9 月外所有真实历史。

{table(['关系类型','条数'],data['relation_types'].items())}

这些数值衡量审核工作量和本轮判断的产出，**不是准确率、召回率或完整真值集**。判定人与报告作者为同一 agent，用户仅对两项歧义做了澄清；没有独立双人标注。正例的明确／推测分布为 `{json.dumps(summary['certainty'],ensure_ascii=False)}`。

## 有用的召回及边界

- LOW 要点补齐后，能够覆盖游戏进展、Excel 漏表、出行计划和就医等具体事项；应先做来源完整性门禁，再比较算法收益。不能把本轮 139 条与旧 6 篇样本的 10 条直接当作 skill 性能提升，来源、历史池与覆盖范围均不同。
- 9 月 22 日“下周一帮忙朋友领证”的计划能衔接 9 月 29 日回顾的实际婚事帮忙与婚后聚餐。历史回放使计划与落实形成直接证据链。
- 父亲就医从犹豫、咨询 AI、劝说到骨科就诊、预约核磁可以区分进展；预约不能写作核磁已经完成。
- 江西同项目的两次整理，经用户确认是不同事项，不能仅凭项目名建立关系。饭钱的菜系记忆不一致则需要结合原文消歧，不能因小字段不同直接判为两顿。
- 重复课程、游戏与就医产生较密的直接关系。每条都需两端证据，不能靠传递性自动补边；后续可独立测量密集关系对回顾检索的边际价值。

## 建议优先级及验证方式（本轮不改 skill）

1. **接入真实计量**：每次模型调用记录 model、请求 ID、input/output/cached/reasoning tokens、起止时间及费用依据；继续把 CLI、用户等待、语义判断与重建分别计时。无计量时保留未知值。
2. **候选召回实验**：从阈值下方、top-5 截断以及同项目误召回各分层抽样，先人工建立有证据的金标准，再比较阈值和 top-k。旧样本提示的 0.3899、0.3894 边界只作为待核查线索，不能直接补关系或宣称漏召回已解决。需同时报告召回增益、负例成本、token 和重复边比例。
3. **同篇筛选实验**：当前 374 对只产出 35 条，低于历史候选产出率。可测试轻量预筛选，但应保留全枚举对照，测量被筛掉的真关系，避免只优化吞吐。
4. **澄清提问提供原文**：同时展示双方日期、事件标题、相关完整要点、冲突位置与待判断边界。首次江西提问未展示内容导致一次无效往返；这是已发生的交互成本。
5. **证据与流程门禁**：保持同侧 point_no 唯一、短引连续匹配。还需检查引文是否足以支持主体、事项、计划或完成状态；单纯字符串匹配通过不足以保证说明被支撑。前一篇未完成时不得准备下一篇。
6. **减少依赖修订重建成本**：本轮因上游稿件修订产生 23 个被替换运行。可测试把明确的待澄清点集中展示，并保留不可变来源、结论版本和完整性门禁；复用必须先证明事件、配对、配置与召回内容完全一致，不能悄悄覆盖旧包。

{link('逐个历史命中及过滤原因',ROOT/'recall-ranking.csv')} · {link('异常与修订记录',ROOT/'环境与异常记录.md')}。下一轮应使用相同来源快照和独立金标准做对照，而非跨不同样本比较总关系数。
'''
(ROOT/'召回评估.md').write_text(recall)
clar='''# 澄清汇总

两项均已回答，0 项待用户回复。用户回答仅用于关系消歧，没有改写原始日记或正式要点。

## Q01 江西整理

争议：9 月 3 日登记会议问题、新建文档，与 9 月 9 日把江西项目要做的事一步步写到纸上，是否同一次整理。

第一次提问未充分展示原文，用户指出“你要给我看看内容呀，不给我看内容我咋判断”。随后展示双方相关要点再提问，用户回答：

> 不同的事情，但是都是江西项目，不是同一次整理

处理：9 月 9 日第 26、44 对由 UNRESOLVED 改为 NO_RELATION。项目一致不足以证明事件衔接；不据此新增其他关系。随后按 skill 指纹与依赖规则重建后续包。

## Q02 七百元饭钱

争议：9 月 25 日提到“该给她七百饭钱还未转”，是否是 9 月 12 日带哒哒去、吃青蟹和鸭子、花七百多且准备转钱给颂梅的同一顿饭；两处菜系回忆不一致。

展示双方原文后，用户回答：

> 是同一顿饭

处理：9 月 25 日第 126 对由 UNRESOLVED 改为 RELATED／提及事件，方向为后来的费用回顾指向此前吃饭事件。描述保留未转款状态，不修正菜系，也不声称已转账。
'''
for date in ('2026-09-09','2026-09-25'):
    d=next(d for d in state['days']if d['date']==date);clar+='\n'+link(date+' 当前稿',Path(d['run_dir'])/'关系结果.md')+' · '+link('该运行澄清记录',Path(d['run_dir'])/'澄清记录.md')+'\n'
(ROOT/'澄清汇总.md').write_text(clar)
issues='''# 环境、异常与修订记录

## 环境和权限

后端脚本使用 `backend/venv/bin/python`（Python 3.11），未使用不兼容的 `.venv`。实际来源审计、prepare、verify 通过 skill 的只读数据库适配器执行；涉及网络权限的命令按流程以只读范围执行。没有打印认证数据，也没有数据库保存、schema 或迁移操作。输出仅写入本地工作区。

本轮技能与业务代码均未修改。仓库原有业务改动不属于本任务。评估脚本和报告不是生产功能或新的 skill 版本。

## 已发生的问题

1. 9 月 10 日首次 record 因同侧重复 point_no 被拒绝。将同一要点的两段摘引改成一段连续原文后通过。该失败原样保存在 command 日志中。
2. 上述失败后，早期 shell 未使用失败即停止，导致 9 月 11 日提前 prepare，漏掉尚未完成的 9 月 10 日历史依赖。没有基于该错误包交付语义结果；废弃该包，完成前一篇后重建，并为本轮 runner 加入“此前篇全部 complete”门禁，后续链式命令失败即停。
3. 9 月 11 日判断草稿引用 point_no 错位，辅助检查发现。回看证据后，相关方法论／部署候选判为仅同主题、无足够事件关系，没有为了通过格式检查而硬凑正例。
4. 9 月 12 日判断草稿的摘引跳过中间文字，辅助检查发现非连续引文。改用真实连续短引后再正式记录。
5. 终核发现部分摘引过短，虽能原文匹配，但不足以完整支撑说明的主体、事项或行动。仅对相关候选补足连续证据，保留修订前稿与修订清单；随后重新 check、verify、render，并重建受影响依赖。
6. 两项歧义经用户消歧。江西首次提问缺少展示内容，造成额外往返，已作为 skill 改进样例保留。

## 重建与复用边界

Q01 修订后先重建后续依赖；终核证据扩充及 Q02 解答后再次按依赖顺序重建。复用先前逐对判断前，逐字段比较 `events、pairs、config、skill_sha256、recall` 完全一致；仅更新来源包指纹。原包不覆盖，旧稿和旧结果保留。最终主稿通过全部校验，汇总只统计当前 19 个运行，旧尝试计入总 CLI 开销。

本轮有 23 个被替换运行记录，其中包括提前 prepare 的错误包与正常修订依赖包；不能把 23 都算作语义失败。唯一正式工作流非零退出为上述同侧重复要点错误；辅助检查阶段的问题发生在正式 record 之前。

所有 command-NNN.json 保留真实命令、时间、退出码和输出。宿主 token 不可得，不把未采集数据伪造为精确值。首次运行耗时与重建耗时分别记录，整体墙钟区间包含思考、工具、澄清及复核，未提供纯推理速度。
'''
issues+='\n'+link('具体终核修订清单',ROOT/'终核修订记录.json')+' · '+link('所有尝试与废弃运行索引',ROOT/'execution.json')+' · '+link('最终依赖检查',ROOT/'final-check.json')+'\n'
(ROOT/'环境与异常记录.md').write_text(issues)
print(json.dumps({'counts':counts,'wall_seconds':wall,'cli_seconds':summary['cli_all_attempts_seconds'],'buckets':dict(buckets),'all_read_chars':rawchars,'fresh':len(fresh_events),'final_checks':len(checks),'report':str(ROOT/'执行报告与稿件索引.md')},ensure_ascii=False))
