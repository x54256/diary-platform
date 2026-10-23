"""人工逐对判断的序号转换器；没有默认负例或模型调用。"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def emit(negative,positive=(),unresolved=()):
    state=json.loads((ROOT/'execution.json').read_text());d=state['days'][-1];s=json.loads((Path(d['run_dir'])/'source.json').read_text());rows=[]
    for raw in negative.strip().splitlines():
        if not raw.strip():continue
        number,reason=raw.split(' ',1);p=s['pairs'][int(number)-1];rows.append({'pair_id':p['pair_id'],'status':'NO_RELATION','reason':reason,'relation':None})
    for number,reason in unresolved:
        p=s['pairs'][number-1];rows.append({'pair_id':p['pair_id'],'status':'UNRESOLVED','reason':reason,'relation':None})
    for number,src,tgt,typ,certainty,se,te,desc,reason in positive:
        p=s['pairs'][number-1]
        def evidence(alias,values):
            out=[]
            for no,quote in values:
                detail=next(x['detail']for x in s['events'][alias]['points']if x['no']==no)
                assert detail.count(quote)==1,(alias,no,quote)
                out.append({'point_no':no,'quote':quote})
            return out
        relation={'source_event':src,'target_event':tgt,'relation_type':typ,'certainty':certainty,'source_evidence':evidence(src,se),'target_evidence':evidence(tgt,te),'description':desc}
        rows.append({'pair_id':p['pair_id'],'status':'RELATED','reason':reason,'relation':relation})
    assert len(set(x['pair_id']for x in rows))==len(rows)
    out=ROOT/(d['date']+'-decisions.json')
    if out.exists():
        old=json.loads(out.read_text());assert old['package_sha256']==s['package_sha256'];assert not set(x['pair_id']for x in rows)&set(x['pair_id']for x in old['results']);rows=old['results']+rows
    out.write_text(json.dumps({'package_sha256':s['package_sha256'],'results':rows},ensure_ascii=False,indent=2)+'\n')
    print('EXPLICIT',len(rows),'/',len(s['pairs']))
