import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.argv=['batch.py','verify_all']
from batch import call
runs=json.loads((ROOT/'运行清单.json').read_text());receipts=[]
for item in runs:
 f=Path(item['run_dir']);state=call(['check',f]);receipt=call(['verify',f]);call(['render',f]);receipts.append({'date':item['date'],'state':state,'verification':receipt})
(ROOT/'最终复验.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2))
print(json.dumps({'verified_runs':len(receipts),'all_complete':all(x['state']['complete']for x in receipts),'all_database_verified':all(x['verification']['verified_against_database']for x in receipts)},ensure_ascii=False))
