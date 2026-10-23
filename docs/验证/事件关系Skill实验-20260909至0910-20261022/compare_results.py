"""离线检查三个判断产物并比较；不连数据库，不将一致性当作语义正确。"""
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def read(name):return json.loads((ROOT/name).read_text())

def validate(rows,pairs,events):
    errors=[]
    ids=[r.get('pair_id') for r in rows]
    if Counter(ids)!=Counter(pairs.keys()):errors.append('结果ID与完整55对不一一对应')
    for r in rows:
        pid=r.get('pair_id')
        if pid not in pairs:continue
        p=pairs[pid]
        if r.get('status') not in ('RELATED','NO_RELATION','UNRESOLVED'):errors.append(pid+':非法状态')
        if not isinstance(r.get('reason'),str) or not r['reason'].strip():errors.append(pid+':缺理由')
        rel=r.get('relation')
        if r.get('status')!='RELATED':
            if rel is not None:errors.append(pid+':非RELATED带关系')
            continue
        if not isinstance(rel,dict):errors.append(pid+':缺关系');continue
        endpoints={rel.get('source_event_id'),rel.get('target_event_id')}
        if endpoints!={p['event_a_id'],p['event_b_id']}:errors.append(pid+':端点不属于该对');continue
        if rel.get('relation_type') not in ('后续事件','引发事件','提及事件'):errors.append(pid+':关系类型错误')
        if rel.get('certainty') not in ('EXPLICIT','SPECULATIVE'):errors.append(pid+':确定性错误')
        if not isinstance(rel.get('description'),str) or not rel['description'].strip():errors.append(pid+':描述为空')
        for side in ('source','target'):
            nums=rel.get(side+'_point_nos')
            valid={p['no'] for p in events[rel[side+'_event_id']]['points']}
            if not isinstance(nums,list) or not nums or any(type(n)is not int for n in nums):
                errors.append(pid+':非法证据');continue
            if len(set(nums))!=len(nums) or not set(nums)<=valid:errors.append(pid+':证据不属于端点')
    return errors

def canonical(r,description=False):
    if r['status']!='RELATED':return (r['status'],)
    x=r['relation']
    out=(r['status'],x['source_event_id'],x['target_event_id'],x['relation_type'],x['certainty'],
         tuple(sorted(x['source_point_nos'])),tuple(sorted(x['target_point_nos'])))
    return out+(x['description'].strip(),) if description else out

def run():
    data=read('batch-input.json');pairs={p['pair_id']:p for p in data['pairs']};events={e['id']:e for e in data['events']}
    outputs={};summary={}
    for key,name in [('pair','pair-results.json'),('pool_one','pool-one-results.json'),('pool_two','pool-two-results.json')]:
        rows=read(name)['results'];errs=validate(rows,pairs,events)
        summary[key]={'errors':errs,'counts':dict(Counter(r['status'] for r in rows))}
        outputs[key]={r['pair_id']:r for r in rows}
    differences=[]
    for pid in pairs:
        rs=[outputs[k][pid] for k in outputs]
        if len({canonical(r) for r in rs})>1:
            differences.append({'pair_id':pid,'results':{k:v[pid] for k,v in outputs.items()}})
    old_diffs=[pid for pid in pairs if canonical(outputs['pool_one'][pid],True)!=canonical(outputs['pool_two'][pid],True)]
    summary['pool_disagreements_old_exact_description']=old_diffs
    summary['three_way_structured_disagreements']=[d['pair_id']for d in differences]
    ref={r['pair_id']:r for r in read('root-reference-before-results.json')['results']}
    for key,rows in outputs.items():
        summary[key]['status_diff_from_root_clear_reference']=[pid for pid,r in ref.items()
            if r['review_scope']=='CLEAR' and r['status']!=rows[pid]['status']]
    (ROOT/'comparison.json').write_text(json.dumps({'summary':summary,'differences':differences},ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
