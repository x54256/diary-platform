import json,csv,statistics
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from collections import Counter
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[2]
load=lambda p:json.loads(p.read_text())
state=load(ROOT/'execution.json');audit=load(ROOT/'coverage-audit.json');data=load(ROOT/'metrics.json');days=data['days']
commands=[load(Path(c['log']))for c in state['commands']]
def link(p,label=None):return f'[{label or p.name}]({p.resolve()})'
def pct(a,b):return f'{a/b:.1%}'if b else '—'
# 按保存的 CLI 返回计算重复资料量，与实际宿主 token 严格区分。
for d in days:
    reads=[c for c in commands if c['args'][0]=='read'and c['args'][1]==d['run_dir']]
    eventchars=sum(sum(len(json.dumps(e,ensure_ascii=False,separators=(',',':')))for e in json.loads(c['stdout'])['events'])for c in reads)
    d['batch_event_chars_with_repetition']=eventchars
    d['repeated_event_chars']=eventchars-d['unique_event_payload_chars']
    d['event_text_repeat_multiplier']=eventchars/d['unique_event_payload_chars']if d['unique_event_payload_chars']else None
    relevant=[c for c in commands if (len(c['args'])>1 and c['args'][1]==d['run_dir'])or(c['args'][0]=='prepare'and d['diary_id'] in c['args'])]
    d['cli_seconds']=sum(c['seconds']for c in relevant)
    d['phase_seconds']=dict((phase,sum(c['seconds']for c in relevant if c['args'][0]==phase))for phase in ('prepare','status','read','record','check','verify','render'))
    d['decision_json_chars']=len((ROOT/(d['date']+'-decisions.json')).read_text())
    d['draft_chars']=len((Path(d['run_dir'])/'关系结果.md').read_text())
    (Path(d['run_dir'])/'执行评估.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
counts={k:sum(d[k]for d in days)for k in ('current_events','current_points','total_pairs','same_day_pairs','historic_pairs','related','no_relation','unresolved','historic_related','same_day_related','batches','cli_read_chars','unique_event_payload_chars','batch_event_chars_with_repetition','repeated_event_chars','decision_json_chars','draft_chars','wall_seconds','cli_seconds')}
buckets=Counter()
for d in days:buckets.update(d['recall_buckets'])
counts['recall_buckets']=dict(buckets)
counts['actual_host_input_tokens']=None;counts['actual_host_output_tokens']=None;counts['external_model_requests']=0;counts['embedding_requests']=0
counts['end_to_end_note']='wall_seconds 是各篇 prepare 启动至 render 结束的墙钟时间之和，含工具等待和本 agent 阅读判断；并非模型净推理时间，不含前置 skill 阅读、来源审计、篇间协调及本报告编写。'
data['totals']=counts
(ROOT/'metrics.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
with (ROOT/'metrics.csv').open('w',encoding='utf-8-sig')as f:
    fields=['date','current_events','current_points','history_events','batches','same_day_pairs','historic_pairs','related','historic_related','no_relation','unresolved','wall_seconds','cli_seconds','cli_read_chars','unique_event_payload_chars','event_text_repeat_multiplier','actual_host_input_tokens','actual_host_output_tokens','run_dir']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(days)
blocked=ROOT/'来源缺口';blocked.mkdir(exist_ok=True)
for r in audit['diaries']:
    if r['status']!='BLOCKED':continue
    filename=blocked/(r['date']+'-'+r['diary_id']+'.md')
    lines=[f"# {r['date']} 来源阻断记录",'',f"日记 ID：`{r['diary_id']}`",'',f"检查结果：{r['reason']}。",'',f"只读完整性审计耗时：{r['audit_seconds']:.4f} 秒；宿主 token 不可得。",'','本篇未进入语义配对；没有生成关系稿，不能把它计为零关系或语义未决。']
    if r.get('missing_events'):
        lines+=['',f"缺少 {len(r['missing_events'])} 个事件的正式要点运行覆盖：",'','| 事件 ID | 标题 | 原重要性 |','| --- | --- | --- |']
        for e in r['missing_events']:lines.append(f"| {e['id']} | {e['event_title']} | {e['importance']} |")
    lines+=['','补齐前置来源后，应按完整日期序列新建运行。当前后续运行没有纳入本篇作为历史，不能把后续运行称为完整九月回放。','',f"执行依据：{link(PROJECT/'skills/diary-event-relations/SKILL.md','事件关系 skill')} 要求“缺少正式要点时明确报告并先补齐，不静默跳过”。本次用户要求不入库，因此未补写正式要点、向量或关系。"]
    filename.write_text('\n'.join(lines)+'\n')
missing=sum(len(r.get('missing_events',[]))for r in audit['diaries'])
lines=['# 2026 年 9 月事件关系稿与执行评估','',f"本次读取数据库当前来源，逐篇审计 20 篇日记：6 篇完成本地关系识别，13 篇正式要点未覆盖全量事件（共缺 {missing} 个事件），另 1 篇无正式要点运行。**全月任务尚未完成**，没有用本地旧要点替代正式来源，也没有把来源失败记成无关系。",'',f"已完成篇目共 {counts['current_events']} 个事件、{counts['current_points']} 条正式要点，{counts['total_pairs']} 对候选全部有判断：{counts['related']} 条关系、{counts['no_relation']} 对无关系、{counts['unresolved']} 对语义未决。后续 4、引发 4、提及 2；全部为来源明确表达。没有数据库写入，没有重新生成向量或调用外部模型。",'','本轮按 09-02 → 09-10 → 09-13 → 09-23 → 09-25 → 09-29 顺序执行。每篇只接续本次实际完成的较早日期，未混入此前实验和已发布关系；首篇无历史。完整稿、无关系理由、真实身份映射及验证回执保存在各自独立运行目录。','',f"使用 {link(PROJECT/'skills/diary-event-relations/SKILL.md','diary-event-relations skill')}，固定指纹 `{days[0]['skill_sha256']}`。参数：相似度阈值 0.4、事件级前五、批次 12000 字符与最多 12 对；没有修改 skill 或召回配置。",'','## 逐篇结果','', '| 日期 | 当前事件 / 要点 | 历史事件 | 同篇 / 历史候选 | 关系 / 无关系 / 未决 | 墙钟秒 | 本地关系稿 |','| --- | ---: | ---: | ---: | ---: | ---: | --- |']
for d in days:
    lines.append(f"| {d['date']} | {d['current_events']} / {d['current_points']} | {d['history_events']} | {d['same_day_pairs']} / {d['historic_pairs']} | {d['related']} / {d['no_relation']} / {d['unresolved']} | {d['wall_seconds']:.1f} | {link(Path(d['run_dir'])/'关系结果.md','关系稿')} |")
lines+=['','每篇均完成 `read → 逐对语义判断 → record → check → verify → render`。`verify` 是只读核对数据库当时来源，不能解释为关系事实得到外部核实。稿件解析和引用位置校验均通过；这是当前 agent 的普通核对，没有独立审稿或用户真值标注。','', '## 耗时与 token 口径','',f"逐篇墙钟时间合计 {counts['wall_seconds']:.1f} 秒（{counts['wall_seconds']/60:.2f} 分钟）；其中可测的 {len(commands)} 次 skill CLI 子进程合计 {counts['cli_seconds']:.2f} 秒。只读全月来源审计另耗时 {audit['seconds']:.2f} 秒。",'',counts['end_to_end_note'],'','宿主没有向本次任务提供实际输入、输出、缓存或推理 token 用量及计费，相关字段保留 null（不可得），未填 0、未按字符换算 token 或费用。外部语言模型请求数、向量请求数均为 0，这不等于当前 Codex 对话没有消耗 token。','',f"20 批 CLI 完整语义输入合计 {counts['cli_read_chars']:,} Unicode 字符。该数来自保存的 `read` 返回值，包含原协议、重复事件及配对，不是宿主实际上下文总量。09-25 和 09-29 的读取展示按同运行事件身份去重，原始返回仍完整留档；宿主已存在的历史上下文、生成过程、工具封装与复读未计入该字符量。",'','| 日期 | 批数 | CLI 秒 | CLI 原始字符 | 批内事件字符（含跨批重复） | 去重事件字符 | 重复倍数 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
for d in days:lines.append(f"| {d['date']} | {d['batches']} | {d['cli_seconds']:.2f} | {d['cli_read_chars']:,} | {d['batch_event_chars_with_repetition']:,} | {d['unique_event_payload_chars']:,} | {d['event_text_repeat_multiplier']:.2f} |")
lines+=['','重复倍数只比较完全相同序列化口径的事件资料，不把配对、元数据计入；也不是可承诺的 token 节省率。每篇 `执行评估.json` 包含分阶段秒数、输入字符、稿件字符及来源指纹。','', '## 召回价值','',f"当前可执行范围内，历史全组合池有 {sum(buckets.values())} 对：入选 {buckets['selected']} 对，低于阈值 {buckets['below_threshold']} 对，达到阈值但排在前五以外 {buckets['top_k_excluded']} 对。筛选后历史候选占池的 {pct(buckets['selected'],sum(buckets.values()))}。这仅表示比较量缩减，不是召回率。",'',f"本 agent 在 {counts['historic_pairs']} 对历史候选中识别到 {counts['historic_related']} 条关系，候选关系产出率为 {pct(counts['historic_related'],counts['historic_pairs'])}；同篇 {counts['same_day_pairs']} 对识别到 {counts['same_day_related']} 条，产出率 {pct(counts['same_day_related'],counts['same_day_pairs'])}。关系产出率用来观察阅读成本与产物，不能称为准确率或真实召回率。",'','两条入选历史关系分别为：09-10 做咬合垫计划 → 09-25 取垫结果；09-25 再次回顾周三多邻国限制功能 → 09-23 功能发现。前者支持事项延续，后者检验记录日期与发生日期不同的提及方向。','',f"完整历史排序、分数、阈值／前五排除原因与候选判断映射见 {link(ROOT/'recall-ranking.csv','召回排序明细')}。未入选组合保持 `NOT_JUDGED`，没有自动填成无关系。",'','另抽查到两组值得人工标注的未入选事件对，证据与排名见独立的召回抽查记录。它们没有被加进冻结的正式候选清单；抽查既不是全组合审查，也不构成真实召回率的分母。','', '## 已发现的问题与建议','', '| 优先级 | 观测证据 | 后续优化方向 |','| --- | --- | --- |',f'| 1 | 20 篇仅 6 篇通过完整来源；13 篇缺 {missing} 个事件，1 篇无要点运行 | 先统一正式要点准入与关系 skill 全事件覆盖要求，补齐后重新从月初回放；不要调低来源检查来掩盖缺失 |','| 2 | 未入选池内出现与“朋友领证帮忙 → 婚后聚餐”相似的潜在跨主题联系，分数 0.3894、排名 10 | 建立人工全组合保留集，将阈值遗漏与前五遗漏分别评测；不要仅看已召回候选 |','| 3 | 09-25 共 102 对，其中同篇 66 对，历史 36 对 | 分开报告同篇比较和历史召回成本，防止把同篇正例当召回收益 |','| 4 | 多个日期反复读到很长的发布会、伴侣复盘内容，跨批重复明显 | 保留完整详情和严格配对，但探索运行内事件缓存、按共享端点编排；缓存必须绑定来源指纹 |','| 5 | 09-25 三批一次性显示触发工具输出截断；后续已从 source.json 补读 E015–E021 完整详情 | 单次展示分批限量，记录截断及补读，不把脚本字符预算当工具输出 token 保障 |','| 6 | 09-23 至 09-29 多次出现同主题不同经历的负例；实体相同并不保证具体联系 | 以逐对负例作为边界样本，重点看误连、泛指提及与同事项新进展；保留原事实，不围绕旧数量调答案 |','| 7 | 09-25 与 09-23 多邻国内容指向同一周三，未出现已实现的新状态 | 在评测中单列“重复回顾 / 新安排 / 执行结果”，检查提及方向与日期定位 |','| 8 | 宿主实际 token 不可得 | 后续若执行宿主支持 usage，按每篇和批次记录输入、输出、缓存、推理 token 与模型版本；本轮不补造数值 |','', '## 来源阻断清单','', '| 日期 | 日记 | 缺失事件数 | 原因与明细 |','| --- | --- | ---: | --- |']
for r in audit['diaries']:
    if r['status']=='BLOCKED':
        p=blocked/(r['date']+'-'+r['diary_id']+'.md')
        lines.append(f"| {r['date']} | `{r['diary_id']}` | {len(r.get('missing_events',[])) if r.get('runs') else '无运行'} | {link(p,r['reason'])} |")
lines+=['','这些来源失败未执行配对。其 `audit_seconds` 仅是只读检查耗时，不是完成 skill 识别耗时。09-20 的两篇使用 ID 区分，不把未整理那篇误选为已有运行的篇目。','', '## 可复查材料','',f"- {link(ROOT/'inventory.json','数据库月度日记与运行清单')}、{link(ROOT/'coverage-audit.json','全量来源检查及缺失事件')}。",f"- {link(ROOT/'execution.json','逐篇运行时间与命令索引')}；`command-*.json` 保存每次命令、起止时间、子进程耗时、完整输出及退出码。",f"- {link(ROOT/'metrics.json','结构化指标')}、{link(ROOT/'metrics.csv','逐篇指标表')}。",f"- 各运行目录中的 `source.json`、`B*.json`、`results.json`、`verification.json`、`resolved-results.json`、`关系结果.md`；主稿为关系交付来源，缓存不替代人工修订后的稿件。",f"- {link(ROOT/'环境与异常记录.md','环境、失败与补读记录')}、{link(ROOT/'召回抽查记录.md','未入选候选抽查')}。",'','所有日志均为本地文件。未改动现有业务代码、skill、旧实验和已发布关系；本次没有调用 `save`、迁移或数据库更新。',f"\n报告生成：{datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}。"]
(ROOT/'执行报告与稿件索引.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(counts,ensure_ascii=False,indent=2))
print('report',ROOT/'执行报告与稿件索引.md')
