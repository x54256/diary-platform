"""仅转换 agent 逐对人工判断，不自动生成关系或负例。"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def build(specs):
    state=json.loads((ROOT/'execution.json').read_text());day=state['days'][-1];s=json.loads((Path(day['run_dir'])/'source.json').read_text());results=[]
    for x in specs:
        a,b,status,reason,*rel=x
        matches=[p for p in s['pairs'] if {p['event_a'],p['event_b']}=={a,b}]
        assert len(matches)==1,(a,b)
        relation=None
        if status=='RELATED':
            typ,certainty,source,target,se,te,description=rel
            relation={'source_event':source,'target_event':target,'relation_type':typ,'certainty':certainty,'source_evidence':[{'point_no':n,'quote':q}for n,q in se],'target_evidence':[{'point_no':n,'quote':q}for n,q in te],'description':description}
        results.append({'pair_id':matches[0]['pair_id'],'status':status,'reason':reason,'relation':relation})
    assert len({r['pair_id']for r in results})==len(results)
    output=ROOT/(day['date']+'-decisions.json')
    if output.exists():
        old=json.loads(output.read_text());assert old['package_sha256']==s['package_sha256']
        ids={r['pair_id']for r in old['results']};assert not ids.intersection(r['pair_id']for r in results)
        results=old['results']+results
    output.write_text(json.dumps({'package_sha256':s['package_sha256'],'results':results},ensure_ascii=False,indent=2)+'\n')
    print('explicit decisions',len(results),'/',len(s['pairs']))
