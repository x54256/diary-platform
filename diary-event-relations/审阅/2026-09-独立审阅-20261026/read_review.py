import json,pathlib,sys,re
ROOT=pathlib.Path(__file__).resolve().parents[3]
days=json.load(open(ROOT/'diary-event-relations/批次评估/2026-09-全量回放-20261023/execution.json'))['days']
for d in days:
 if d['date'][8:] not in sys.argv[1:]: continue
 p=pathlib.Path(d['run_dir']);s=json.load(open(p/'source.json')); print('\nDAY',d['date'],'RUN',p)
 for a,e in s['events'].items():
  if e['diary_date']!=d['date']:continue
  print(a,e['title'])
  for pt in e['points']:print('p'+str(pt['no']),pt['detail'])
 print('DRAFT')
 for i,l in enumerate((p/'关系结果.md').read_text().splitlines(),1):
  if l.strip() and not l.startswith(('###','<details>','</details>','<summary>','# 2026','<!-- relations_format')):print(str(i)+':'+l)
