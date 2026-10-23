import json,csv,statistics
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parent
state=json.loads((ROOT/'execution.json').read_text())
all_current={};snapshots=[]
for day in state['days']:
    s=json.loads((Path(day['run_dir'])/'source.json').read_text());snapshots.append((day,s))
    all_current.update({e['id']:e for e in s['events'].values()if e['run_id']==s['current_run_id']})
metrics=[];recalls=[];types=Counter()
for day,s in snapshots:
    rows=json.loads((Path(day['run_dir'])/'results.json').read_text())['results']
    # 交付后评估直接读取主稿解析结果，避免未来人工修改时继续采信旧缓存
    import sys
    sys.path.insert(0,str(ROOT.parents[2]/'skills/diary-event-relations/scripts'))
    from draft import read_draft
    _,rows=read_draft(Path(day['run_dir'])/'关系结果.md',s,complete=True)
    bypair={r['pair_id']:r for r in rows}
    byids={frozenset((s['events'][p['event_a']]['id'],s['events'][p['event_b']]['id'])):bypair[p['pair_id']]for p in s['pairs']}
    cross=[r for p in s['pairs'] if (r:=bypair[p['pair_id']]) and s['events'][p['event_a']]['diary_date']!=s['events'][p['event_b']]['diary_date']]
    actual=[e for e in s['events'].values()if e['run_id']==s['current_run_id']]
    counts=Counter(r['status']for r in rows);types.update(r['relation']['relation_type']for r in rows if r['relation'])
    stats=Counter()
    for c in s['recall']:
        for rank,h in enumerate(c['hits'],1):
            selected=h['event_id']in c['selected_event_ids'];result=byids.get(frozenset((c['current_event_id'],h['event_id'])))
            bucket='selected'if selected else 'below_threshold'if h['score']<s['config']['min_similarity'] else 'top_k_excluded'
            stats[bucket]+=1
            recalls.append({'date':day['date'],'current_event_id':c['current_event_id'],'current_title':all_current[c['current_event_id']]['title'],'historic_event_id':h['event_id'],'historic_date':all_current[h['event_id']]['diary_date'],'historic_title':all_current[h['event_id']]['title'],'rank':rank,'score':h['score'],'bucket':bucket,'status':result['status']if result else 'NOT_JUDGED','relation_type':result['relation']['relation_type']if result and result['relation']else None})
    raw_chars=sum(r['input_chars'] for r in day['reads'])
    unique_chars=sum(len(json.dumps({'id':a,'title':e['title'],'diary_date':e['diary_date'],'occurred_on':e.get('occurred_on'),'points':[{k:p[k]for k in ('no','summary','detail')}for p in e['points']]},ensure_ascii=False,separators=(',',':')))for a,e in s['events'].items())
    for r in rows:
        if r['relation']:
            pass
    item={'date':day['date'],'diary_id':day['diary_id'],'run_dir':day['run_dir'],'package_sha256':s['package_sha256'],'skill_sha256':s['skill_sha256'],'current_events':len(actual),'current_points':sum(len(e['points'])for e in actual),'history_events':len(s['recall'][0]['hits'])if s['recall']else 0,'batches':len(json.loads((Path(day['run_dir'])/'run.json').read_text())['batches']),'total_pairs':len(rows),'same_day_pairs':len(rows)-len(cross),'historic_pairs':len(cross),'related':counts['RELATED'],'no_relation':counts['NO_RELATION'],'unresolved':counts['UNRESOLVED'],'historic_related':sum(r['status']=='RELATED'for r in cross),'same_day_related':sum(r['status']=='RELATED'for r in rows)-sum(r['status']=='RELATED'for r in cross),'historic_relation_yield':sum(r['status']=='RELATED'for r in cross)/len(cross)if cross else None,'recall_buckets':dict(stats),'cli_read_chars':raw_chars,'unique_event_payload_chars':unique_chars,'wall_seconds':day['wall_seconds'],'actual_host_input_tokens':None,'actual_host_output_tokens':None,'database_written':False,'database_verified_at':json.loads((Path(day['run_dir'])/'verification.json').read_text())['verified_at']}
    metrics.append(item)
(ROOT/'metrics.json').write_text(json.dumps({'days':metrics,'relation_types':dict(types),'note':'候选命中由本 agent 语义判断，不是准确率；未建立全量真值集，召回率未知。字符量不是实际 token。'},ensure_ascii=False,indent=2)+'\n')
with (ROOT/'recall-ranking.csv').open('w')as f:
    w=csv.DictWriter(f,fieldnames=list(recalls[0]));w.writeheader();w.writerows(recalls)
print(json.dumps(metrics,ensure_ascii=False,indent=2))
print('types',dict(types))
print('spotcheck')
for r in recalls:
 if (r['date']=='2026-09-29' and r['current_title'].startswith('参加')and r['historic_title'].startswith('国庆'))or(r['date']=='2026-09-25' and r['current_title'].startswith('梳理')and r['historic_title'].startswith('和王振州')): print(json.dumps(r,ensure_ascii=False))
