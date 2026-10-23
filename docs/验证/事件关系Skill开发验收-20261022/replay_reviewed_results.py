"""把此前已审阅的实验结果用于新工具工程回归；不生成新的语义判断。"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'skills/diary-event-relations/scripts'))
import workflow as w


def run(folder):
    reference=ROOT/'docs/验证/事件关系Skill实验-20260909至0910-20261022'
    snapshot,_=w.load_package(folder)
    old=w.read_json(reference/'source.json')
    old_events={e['id']:e for e in old['events']}
    for event in snapshot['events'].values():
        old_points=old_events[event['id']]['points']
        w.require([{k:p[k]for k in ('id','no','summary','detail')}for p in event['points']]==old_points,
                  '正式要点身份或内容与既有参照不同，不能复用旧结论')
    prior=w.read_json(reference/'final-results.json')['results']
    old_pairs=w.read_json(reference/'batch-input.json')['pairs']
    bykey={tuple(sorted((p['event_a_id'],p['event_b_id']))):next(r for r in prior if r['pair_id']==p['pair_id'])for p in old_pairs}
    aliases={e['id']:a for a,e in snapshot['events'].items()}
    rows=[]
    for pair in snapshot['pairs']:
        key=tuple(sorted((snapshot['events'][pair['event_a']]['id'],snapshot['events'][pair['event_b']]['id'])))
        old_row=bykey[key]
        row={'pair_id':pair['pair_id'],'status':old_row['status'],'reason':old_row['reason'],'relation':None}
        if old_row['relation']:
            rel=old_row['relation'];row['relation']={k:rel[k]for k in ('relation_type','certainty','description')}
            for side in ('source','target'):
                alias=aliases[rel[side+'_event_id']];row['relation'][side+'_event']=alias
                row['relation'][side+'_evidence']=[{'point_no':n,'quote':next(p['detail']for p in snapshot['events'][alias]['points']if p['no']==n)}for n in rel[side+'_point_nos']]
        rows.append(row)
    filename=Path(folder)/'reviewed-regression-input.json'
    w.write_json(filename,{'package_sha256':snapshot['package_sha256'],'results':rows})
    state=w.record(folder,filename)
    w.write_json(Path(folder)/'regression-origin.json',{'kind':'ENGINEERING_REGRESSION_NOT_NEW_SEMANTIC_EVALUATION',
        'reference_results':str(reference/'final-results.json'),'reference_sha256':w.digest(prior),
        'point_identity_and_content_matched':True,'database_mutation':False})
    print(json.dumps(state,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run_dir',type=Path)
    run(parser.parse_args().run_dir)
