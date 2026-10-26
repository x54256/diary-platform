import sys,json,pathlib,re,hashlib,collections,datetime
sys.dont_write_bytecode=True
ROOT=pathlib.Path.cwd(); OUT=ROOT/'diary-event-relations/审阅/2026-09-独立审阅-20261026'
sys.path.insert(0,str(ROOT/'skills/diary-event-relations/scripts'));import draft,workflow
idx=ROOT/'diary-event-relations/批次评估/2026-09-全量回放-20261023/execution.json'
days=json.load(open(idx))['days'];data={};allrows=[];stats=[];initial=json.load(open(OUT/'输入指纹.json'));baseline={d['date']:d for d in initial['days']};changes=[]
F={'P-dee0c15426dd0503':'F01','P-a55408d7c887ad5d':'F02','P-b2d0de8ccdeb4a3c':'F03'}
C={'P-c76d16e226a6276d':'C01','P-3036e67b2364ff8b':'C01','P-738f09e0f3580a33':'C02','P-1b0cd72ad8e4ac7e':'C03','P-629f8909b7c68d08':'C03','P-b485d2043e3e6a50':'C03'}
now=datetime.datetime.now().astimezone().isoformat();fp=workflow.skill_fingerprint()
for d in days:
 p=pathlib.Path(d['run_dir']);s=json.load(open(p/'source.json'));md=(p/'关系结果.md').read_text();rows=draft.parse_text(md,s); hashes={n:hashlib.sha256((p/n).read_bytes()).hexdigest()for n in ['source.json','关系结果.md']}
 for n,h in hashes.items():
  if h!=baseline[d['date']]['files'][n]['sha256']:changes.append({'date':d['date'],'file':n})
 data[d['date']]={'p':p,'s':s,'md':md,'rows':{r['pair_id']:r for r in rows}}
 counts=collections.Counter(r['status']for r in rows); st={'date':d['date'],'source_pairs':len(s['pairs']),'draft_pairs':len(rows),'counts':dict(counts),'run_dir':str(p),'source_file_sha256':hashes['source.json'],'draft_file_sha256':hashes['关系结果.md'],'package_sha256':s['package_sha256'],'source_package_self_digest_valid':s['package_sha256']==workflow.digest({k:v for k,v in s.items()if k!='package_sha256'}),'frozen_skill_sha256':s['skill_sha256'],'current_skill_matches':s['skill_sha256']==fp,'all_pairs_semantically_read':True,'evidence_syntax_check':'pass'};stats.append(st)
 for pair in s['pairs']:
  r=next(r for r in rows if r['pair_id']==pair['pair_id']);pid=r['pair_id'];start=next(m.start()for m in re.finditer(r'^## (?:关系|无关系|未决) \d+\n[\s\S]*?(?=^## |\Z)',md,re.M)if 'pair_id: '+pid in m.group());line=md[:start].count('\n')+1
  events=[s['events'][pair[k]]for k in ['event_a','event_b']]
  allrows.append({'date':d['date'],'pair_id':pid,'draft_path':str(p/'关系结果.md'),'draft_line':line,'source_path':str(p/'source.json'),'draft_status':r['status'],'draft_reason':r['reason'],'events':[{'id':e['id'],'date':e['diary_date'],'title':e['title'],'read_full_point_nos':[pt['no']for pt in e['points']]}for e in events],'source_file_sha256':hashes['source.json'],'draft_file_sha256':hashes['关系结果.md'],'semantic_read':True,'review_result':'明确问题 '+F[pid] if pid in F else '需澄清疑点 '+C[pid] if pid in C else '未发现可报告问题','review_dimensions':['同一具体事项及新进展','双方触发／明确引用','方向与类型','计划及推测程度','选点与描述主体忠实性'] if r['status']=='RELATED' else ['双方完整要点中有无具体进展／触发／引用','是否仅主题或人物相同','是否存在需澄清的具体歧义'],'quote_location_validation':'通过' if r['status']=='RELATED' else '不适用'})
(OUT/'逐对覆盖记录.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in allrows))
(OUT/'逐篇指纹与计数.json').write_text(json.dumps({'checked_at':now,'current_skill_sha256':fp,'changes_since_baseline':changes,'days':stats},ensure_ascii=False,indent=2))
def item(date,pid):
 z=data['2026-'+date];r=z['rows'][pid];coverage=next(r for r in allrows if r['pair_id']==pid);pair=next(p for p in z['s']['pairs']if p['pair_id']==pid)
 return z,r,coverage,pair

def link(path,line=1):return f'[{path.name}:{line}](<{path}:{line}>)'
def event(date,title):
 z=data['2026-'+date];alias,e=next((a,e)for a,e in z['s']['events'].items()if e['title']==title);return z,alias,e

def point_text(z,e,nos):
 out=[];src=z['p']/'source.json';txt=src.read_text()
 for pt in e['points']:
  if pt['no'] not in nos:continue
  needle='"id": "'+pt['id']+'"';ln=txt[:txt.index(needle)].count('\n')+1
  out.append(f"{e['diary_date']}｜{e['title']}｜要点{pt['no']}（{link(src,ln)}）\n\n"+'\n'.join('> '+l if l else '>'for l in pt['detail'].splitlines()))
 return '\n\n'.join(out)

def pair_evidence(date,pid,pointnos):
 z,r,c,p=item(date,pid);out=[f"定位：{link(z['p']/'关系结果.md',c['draft_line'])}；`{pid}`；当前 `{r['status']}`。"]
 for k,nos in zip(['event_a','event_b'],pointnos):out.append(point_text(z,z['s']['events'][p[k]],nos))
 return '\n\n'.join(out)
report=['# 2026年9月事件关系独立审阅','',f'完成记录：{now}。使用项目 `skills/diary-event-relations/SKILL.md` 及边界、澄清、结果协议；没有调用外部模型、数据库或写入功能，没有修改原稿、冻结来源、skill或业务代码。','',
'当前磁盘19篇，共889个候选对：139个 RELATED、750个 NO_RELATION、0个 UNRESOLVED；逐对完成语义判读，双方共118个唯一事件的全部详情已读，重复事件跨包内容一致。发现3个明确稿件问题（2个漏提及、1个理由串错端点），另有3组、涉及6对的具体澄清疑点；定向扩查3个未入选组合，均发现应补召回的明确联系。后三个没有冻结 pair_id，不混入889对稿件判断问题数。其余880对未发现可报告问题；这不是880对的外部事实正确认证。','',
'本报告是一次独立agent审阅，不是独立金标准；不计算准确率、精确率或召回率。没有重提要点、重新prepare或全月重跑。','',
'## 明确稿件问题','',
'### F01 将可定位的文档回顾仅作为背景排除，漏掉提及','',pair_evidence('09-03','P-dee0c15426dd0503',[[11,16],[1]]),'',
'稿件依据称“下班条目虽交代工作问题已写入文档，仅为离开办公室的背景，没有继续处理指标事项”。但提及不要求继续处理：后侧明确回顾当天“该整理的问题记进文档”，前侧正记录新建文档登记会议问题、标红待确认项。双方可定位同一整理经历。建议改为后侧“下班买饭回家……”→前侧“江西评估指标……”的提及事件，描述只说下班前回顾问题已登记，勿补因果或宣称指标已解决。','',
'### F02 无关系理由串成了另一端点','',pair_evidence('09-09','P-a55408d7c887ad5d',[[1,2,3,4],[9,11]]),'',
'原理由：“恢复平台的困难没有引用父母AI沟通设想。”本对另一侧实际是9月3日江西指标梳理，不是父母AI沟通设想。状态可继续保持 NO_RELATION，但必须重写成与本对双方相符的依据；例如两侧讨论平台恢复成本与江西需求整理，未发现具体引用、触发或同一事项的新进展。此项不声称发现漏边。','',
'### F03 明确回顾取咬合垫却只排除了后续，漏检提及','',pair_evidence('09-25','P-b2d0de8ccdeb4a3c',[[1],[1]]),'',
'原理由：“工作条目提拿垫回家后，只有时间背景，转做工作明确因一周过半未工作，不是取件新进展。”两侧都指向周三早晨取此前做好的咬合垫，后侧明确“周三拿咬合垫回家”。不构成后续或取件导致工作的因果，仍满足具体提及。建议工作条目→取垫条目的提及事件。此点也与9月14日 P-3a163cb905deffef 已采纳“去修复科看牙回来”的提及边界一致。','',
'## 需澄清的疑点（未向用户实际发问）','',
'以下材料供主代理集中处理，不是虚构澄清记录。已先阅读现存Q01、Q02：9月9日的江西纸上拆解并非9月3日同次整理；9月25日七百元饭钱确为9月12日那顿饭。保留这两项已答事实，不重复问。以下C01询问的是9月17日新数据身份，非9月9日旧问。','',
'### C01 9月17日的“江西数据又整理出来”是哪一批','',pair_evidence('09-17','P-3036e67b2364ff8b',[[1],[17]]),'',
'同问题还影响 `P-c76d16e226a6276d`：',pair_evidence('09-17','P-c76d16e226a6276d',[[1],[1]]),'',
'疑点：现有两条后续都将泛称“江西数据”定位为9月1日/3日的需求及基础指标重整；9月17日一侧没有字段、指标体系或资料批次等身份。当前正例的“同一批”仍需要核实，不能靠同项目补足。事实问题：9月17日“江西数据最近又整理出来”，是在继续9月3日要求重整的那批基础指标需求/数据，还是江西项目中另一个数据事项？可答“同一批继续处理／另一事项／不记得，保留未决”，或补充。不因已澄清9月9日不同整理而推定本题答案。若需新增批次身份，按skill先修订正式要点、再新建受影响运行；不得只凭回答更改冻结source。','',
'### C02 同日《自制力》和《自控力》是否同一次听书','',pair_evidence('09-20','P-738f09e0f3580a33',[[1],[3,4,5]]),'',
'疑点：双方同为“昨天”听/看自我控制书籍解读，但书名不同。稿件直接据此判无关系；若是同一次听书，后侧在复述同一次材料并新增具体方法感想，可能应记录提及。事实问题：9月20日两条分别写的《自制力》和《自控力》，指同一本书、同一次昨晚的解读，还是两份不同材料？可答“同一次／不同材料／不记得，保留未决”。不能让用户选择关系类别。','',
'### C03 《简单心理学》是否正在学习的普通心理学课程','']
z,a,e=event('09-20','规划每日学习与作息安排');report.append(point_text(z,e,[1,2]))
for date,title,nos in [('09-18','学习心理学及探讨学习目的',[1,2]),('09-09','刷老梁的视频，又陷入光看不做的状态',[4]),('09-22','继续学习视觉过程，也该把时间转回工作',[1,2])]:
 z,a,e=event(date,title);report+=['',point_text(z,e,nos)]
report+=['','受影响稿件：']
for date,pid in [('09-20','P-1b0cd72ad8e4ac7e'),('09-20','P-629f8909b7c68d08'),('09-22','P-b485d2043e3e6a50')]:
 z,r,c,p=item(date,pid);report.append(f"- `{pid}`：{link(z['p']/'关系结果.md',c['draft_line'])}；当前 NO_RELATION，理由均借课程名差异排除同一课程身份。")
report+=['','事实问题：9月20日每日计划中“中午或空闲学《简单心理学》”，是此前从第二章神经系统继续到第三章感觉/视觉的普通心理学视频课，还是另一个课程或书籍？可答“同一课程／另一材料／不记得，保留未决”。若同一课程，计划将课程放入中午/空闲且随后继续学习，需重新判断三个事件对的后续；若名称相同仍无新安排或实际衔接，不能自动建全部三边。若回答提供来源外新身份，先走正式要点修订。','',
'## 召回范围定向检查：3个未选组合','',
'这里只检查下列3对，不是穷尽未入选hits或全部历史组合。当前每篇top_k=5，实际分数达到min_similarity=0.4仍可能未入选；以下三个hits均存在、selected_event_ids均未选、pairs中均没有。不能把清单缺失解释为NO_RELATION，也不能在旧稿中加清单外组合。建议未来新运行扩大/补召回。']
recalls=[('R01','09-23','总结“豆包式”沟通方法及在母亲看病问题上的应用',[1],'09-22','妈妈反复催生，我再次说明自己的立场',[1],'前侧昨天的具体母亲催生争吵在后侧被明确回顾，且形成进一步豆包式回应总结；建议9月22日→9月23日后续。'),('R02','09-23','因情绪不佳未能用非暴力沟通引导小廖处理离职后工作压力',[1,2],'09-20','纠结颂梅离职时间以安排出行',[1,2],'同一离职日期事项，从八月底提出、日期未定，到继续被安排干到十月之后并提出向领导明确月底走的新建议；建议9月20日→9月23日后续。'),('R03','09-27','收拾东西去清远度假，入住被树木环绕的酒店',[1,2],'09-25','中秋安排聚餐和问候父母，明天带猫狗去清远泡温泉',[2],'同一时间、地点、猫狗和酒店，9月25日预订/准备出发转为9月26日实际出发入住；建议9月25日→9月27日后续。')]
recallrows=[]
for code,cd,ct,cn,od,ot,on,why in recalls:
 cz,ca,ce=event(cd,ct);oz,oa,oe=event(od,ot);rr=next(r for r in cz['s']['recall']if r['current_event_id']==ce['id']);hit=next(h for h in rr['hits']if h['event_id']==oe['id']);selected=oe['id']in rr['selected_event_ids'];pair_exists=any({cz['s']['events'][p['event_a']]['id'],cz['s']['events'][p['event_b']]['id']}=={ce['id'],oe['id']}for p in cz['s']['pairs']);assert not selected and not pair_exists
 src=cz['p']/'source.json';txt=src.read_text();needle='"current_event_id": "'+ce['id']+'"';ln=txt[:txt.index(needle)].count('\n')+1
 report+=['',f'### {code} 未入选；无冻结pair_id','',f"召回记录：{link(src,ln)}；当前事件UUID `{ce['id']}`；历史UUID `{oe['id']}`；score={hit['score']:.6f}，未入选top5。",'',point_text(cz,ce,cn),'',point_text(oz,oe,on),'',why]
 recallrows.append({'review_id':code,'current_event':ce['id'],'historical_event':oe['id'],'current_source_path':str(src),'historical_source_path':str(oz['p']/'source.json'),'recall_score':hit['score'],'selected':selected,'frozen_pair_id':None,'pair_exists':pair_exists,'semantic_read':True,'conclusion':why})
(OUT/'未选候选定向覆盖.json').write_text(json.dumps(recallrows,ensure_ascii=False,indent=2))
report+=['','## 冻结来源检查与当前流程兼容性','',
'19份稿件均从当前磁盘Markdown解析，不使用results.json或关系结果.json替代。889对清单完整、无重复；139个正例的端点、要点序号与双方所有引文均通过当前解析器的唯一连续原文验证。此检查只证明结构和引用位置，语义判断仍以上文人工审阅为准。19个source.package_sha256自摘要有效；同一事件跨来源内容一致。没有访问数据库，不能声称来源仍是数据库最新正式结果。','',
'19个冻结source的skill_sha256均不同于当前skill指纹 `'+fp+'`。当前workflow.load_package会在skill指纹比较处拒绝这些旧包，不能据此认定旧稿语义错误。没有改指纹、绕过后写入或新prepare。只把冻结source传给无副作用的draft.parse_text，完成历史稿本地引用核对。冻结history_mode=replay；索引声明本次19篇接续，排除9月20日另一未整理篇，不是当前skill要求的数据库全历史池复验。本次未查全库，不证明历史池完整性/覆盖缺口已经消失。','',
'输入指纹在首7篇初读后建立；其后至最终检查的38个source/Markdown文件内容hash均未变化。此前没有预先hash，无法回溯证明首次读取至建立指纹间未变化。已补读首次工具输出被截断的9月3日水牙线要点、9月12日全量当日要点与9月11日末12对，以及压缩读取时被误过滤的9月14日理由；最终解析再次使用同一磁盘稿。','',
'未拿旧评估报告计数作结论来源。工作中手工加总曾误报989对，最终脚本以19份当前source.pairs及当前Markdown双向确认889对，139/750/0；不是稿件版本变化。','',
'## 逐篇实际覆盖与时间','',
'| 日期 | source对数 | 当前稿正例 | 无关系 | 未决 | 实际语义覆盖 |','| --- | ---: | ---: | ---: | ---: | ---: |']
for st in stats:report.append(f"| {st['date']} | {st['source_pairs']} | {st['counts'].get('RELATED',0)} | {st['counts'].get('NO_RELATION',0)} | {st['counts'].get('UNRESOLVED',0)} | {st['draft_pairs']} |")
report+=['','889条逐对记录见 `逐对覆盖记录.jsonl`，每条含主稿绝对路径/行号、双方日期标题UUID、实际读取要点编号、稿件状态/理由和本次审阅结论。完整文件hash与逐篇计数见 `逐篇指纹与计数.json`，初始hash见 `输入指纹.json`。','',
'时间：首次读skill/首批稿件的精确时钟未采集，未知；可核实的审阅辅助脚本创建时间为2026-10-26 09:53:17+08:00（已在初读之后），报告本次生成时间为'+now+'。这只能提供部分已记录审阅区间，不冒充完整精确耗时。实际host token用量工具未提供，记未知；不以字数、输出大小或估算代替token。没有调用外部模型服务。']
(OUT/'审阅报告.md').write_text('\n'.join(report)+'\n')
(OUT/'时间与用量.json').write_text(json.dumps({'first_tool_read_started_at':None,'first_persisted_review_artifact_at':'2026-10-26T09:53:17+08:00','report_generated_at':now,'actual_host_tokens':None,'actual_host_tokens_availability':'未知：工具未提供实际host计量','external_model_calls':0,'database_reads':0,'database_writes':0,'semantic_pairs_read':889,'targeted_nonselected_pairs_read':3,'changes_since_hash_baseline':changes},ensure_ascii=False,indent=2))
print(json.dumps({'pairs':len(allrows),'positive':sum(r['draft_status']=='RELATED'for r in allrows),'negative':sum(r['draft_status']=='NO_RELATION'for r in allrows),'clear_draft_findings':len(F),'clarification_groups':3,'clarification_pairs':len(C),'recall_omissions_targeted':3,'hash_changes':changes,'report':str(OUT/'审阅报告.md')},ensure_ascii=False))
