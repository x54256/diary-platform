"""固定要点比较阈值与前五，只对候选并集判定一次；不写业务库。"""

import argparse
import asyncio
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import recheck_graph_quality as runner


def key(a, b):
    return '|'.join(sorted((a, b)))


def select_pairs(rows, events, threshold, top_k=5):
    selected = {row['pair_id'] for row in rows if row['same_day']}
    for current in events:
        eligible = [r for r in rows if r['current_id'] == current and not r['same_day']
                    and (threshold is None or r['similarity'] >= threshold)]
        eligible.sort(key=lambda r: (-r['similarity'], r['history_id']))
        selected.update(r['pair_id'] for r in eligible[:top_k])
    return selected


async def prepare(folder, reviewed_path=None):
    from services.model_runtime import resolve_model_setting
    source = runner.read(folder/'source.json')
    outcomes = {r['event_id']: r for r in runner.read(folder/'point-outcomes.json')}
    reviewed = runner.read(reviewed_path) if reviewed_path else {}
    if reviewed:
        assert reviewed['source_sha256'] == runner.baseline_hash(source), '独立原文核对清单来源不匹配'
    exceptions = {r['event_id']:r for r in reviewed.get('accepted_exceptions',[])}
    events = {}
    for event in source['events']:
        candidate = runner.read(folder/'points'/event['id']/'candidate.json')
        if not outcomes.get(event['id'], {}).get('passed'):
            exception = exceptions.get(event['id'],{})
            assert exception.get('candidate_sha256') == runner.baseline_hash(candidate) and exception.get('reason'), (
                '要点未通过，须先独立对照原文并提供冻结的实验输入清单：'+event['title'])
        events[event['id']] = {k: event[k] for k in ('id','title','diary_date')} | {'points': candidate['points']}
    out = folder/'calibration'
    cfg = resolve_model_setting('graph_embedding')
    assert cfg.model_name == 'qwen3.7-text-embedding-flash'
    # 向量接口按十个完整要点分批，避免超出渠道批量条数。
    units = [(eid, point) for eid,e in events.items() for point in e['points']]
    vectors = {eid: [] for eid in events}
    for start in range(0, len(units), 10):
        group = units[start:start+10]
        pool = {f'{eid}:{p["no"]}': {'points': [p]} for eid,p in group}
        result = await runner.vectors(cfg, pool, out/f'vectors-{start//10+1}.json')
        for eid,p in group:
            vectors[eid].append(result[f'{eid}:{p["no"]}'][0])
    rows = []
    for i,(a,b) in enumerate(combinations(events,2),1):
        current,history = sorted((a,b),key=lambda k:(events[k]['diary_date'],k),reverse=True)
        score = max(runner.cosine(u,v) for u in vectors[a] for v in vectors[b])
        rows.append({'pair_id': f'P{i:03}', 'event_a_id':a,'event_b_id':b,
                     'current_id':current,'history_id':history,'similarity':score,
                     'same_day':events[a]['diary_date']==events[b]['diary_date']})
    policies = {name:sorted(select_pairs(rows,events,threshold)) for name,threshold in
                [('threshold_0.5',0.5),('threshold_0.4',0.4),('top5_only',None)]}
    references = {key(r['event_a_id'],r['event_b_id']):r for r in runner.read(folder/'reference.json')}
    summary = {}
    for name,selected in policies.items():
        hits = [r for r in rows if r['pair_id'] in selected]
        positive = [r for r in hits if references.get(key(r['event_a_id'],r['event_b_id']),{}).get('expected_status')=='RELATED']
        summary[name] = {'candidate_pairs':len(hits), 'positive_covered':len(positive),
                         'positive_total':sum(r['expected_status']=='RELATED' for r in references.values()),
                         'unlabeled_candidate_pairs':sum(key(r['event_a_id'],r['event_b_id']) not in references for r in hits)}
    runner.baseline.save(out/'recall.json', {'events_sha256':runner.baseline_hash(events),
        'embedding_model':cfg.model_name,'rows':rows,'policies':policies,'summary':summary,
        'model_review_exceptions':reviewed.get('accepted_exceptions',[]),
        'input_scope':'独立召回实验，不覆盖原任务失败状态'})
    runner.baseline.save(out/'events.json',events)
    print(summary,flush=True)
    return events, rows, policies, references


async def judge(folder, events, rows, policies, references):
    out = folder/'calibration'
    cfg = runner.language_config('relation_a','kimi-k3')
    fixtures = Path(__file__).parent/'fixtures'
    prompts = {'a':(fixtures/'layer1_relation_batch_prompt_v4.txt').read_text(),
               'b':(fixtures/'layer1_relation_batch_prompt_v4.txt').read_text(),
               'c':(fixtures/'layer1_relation_adjudicate_v3.txt').read_text()}
    selected = set().union(*(set(ids) for ids in policies.values()))
    pairs = [{k:r[k] for k in ('pair_id','event_a_id','event_b_id')} for r in rows if r['pair_id'] in selected]
    semaphore = asyncio.Semaphore(2)

    async def request(role, number, batch, candidates=None):
        async with semaphore:
            payload = runner.payload(batch,events)
            if candidates is not None:
                payload.pop('pairs')
                payload['disagreements'] = [{'pair':p,'candidate_1':candidates['a'][p['pair_id']],
                                             'candidate_2':candidates['b'][p['pair_id']]} for p in batch]
            data = await runner.baseline.call(cfg,prompts[role],payload,out,f'{role}-{number}',
                lambda d:runner.validate_result(d,batch,events))
            return role,data['results']

    tasks = [request(role,i//25+1,pairs[i:i+25]) for role in ('a','b') for i in range(0,len(pairs),25)]
    decisions = {'a':{},'b':{},'c':{}}
    for role,results in await asyncio.gather(*tasks):
        decisions[role].update({r['pair_id']:r for r in results})
    disagreements = [p for p in pairs if not runner.equivalent(decisions['a'][p['pair_id']],decisions['b'][p['pair_id']])]
    for i in range(0,len(disagreements),25):
        _,results = await request('c',i//25+1,disagreements[i:i+25],decisions)
        decisions['c'].update({r['pair_id']:r for r in results})
    final = {p['pair_id']:decisions['c'].get(p['pair_id'],decisions['a'][p['pair_id']]) for p in pairs}
    runner.baseline.save(out/'final.json',final)
    lookup = {key(r['event_a_id'],r['event_b_id']):r for r in rows}
    metrics = {}
    for name,selected in policies.items():
        tp=fp=fn=tn=unresolved=0
        for ref_key,ref in references.items():
            row = lookup[ref_key]
            actual = final[row['pair_id']]['status'] if row['pair_id'] in selected else 'NO_RELATION'
            expected = ref['expected_status']
            tp += expected=='RELATED' and actual=='RELATED'
            fn += expected=='RELATED' and actual!='RELATED'
            fp += expected=='NO_RELATION' and actual=='RELATED'
            tn += expected=='NO_RELATION' and actual=='NO_RELATION'
            unresolved += actual=='UNRESOLVED'
        unmarked = [row for row in rows if row['pair_id'] in selected and key(row['event_a_id'],row['event_b_id']) not in references]
        metrics[name] = {'true_positive':tp,'false_positive':fp,'false_negative':fn,'true_negative':tn,
                         'unresolved':unresolved,'unlabeled_related_pairs':[row['pair_id'] for row in unmarked if final[row['pair_id']]['status']=='RELATED'],
                         'candidate_pairs':len(selected),'reference_pairs':len(references),
                         'note':'确认标签只含关联状态，不代表类型、方向、描述全部通过；候选并集共用一次判定'}
    runner.baseline.save(out/'metrics.json',metrics)
    print(metrics,flush=True)


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--recall-only',action='store_true')
    parser.add_argument('--reviewed-inputs',type=Path,
                        help='独立原文核对后的冻结输入清单，仅限召回实验，不修改模型审核或正式任务状态')
    args=parser.parse_args()
    folder=args.folder.resolve()
    events,rows,policies,references=await prepare(folder,args.reviewed_inputs)
    if not args.recall_only:
        await judge(folder,events,rows,policies,references)


if __name__=='__main__':
    asyncio.run(main())
