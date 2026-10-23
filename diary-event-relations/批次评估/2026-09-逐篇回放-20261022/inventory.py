import sys,json
from pathlib import Path
sys.path.insert(0,str(Path('skills/diary-event-relations/scripts').resolve()))
from db_source import connection,list_diaries
with connection(Path('backend').resolve()) as conn:
    data=list_diaries(conn,'x5456')
data['diaries']=[d for d in data['diaries'] if str(d['diary_date']).startswith('2026-09-')]
print(json.dumps(data,ensure_ascii=False,indent=2,default=str))
