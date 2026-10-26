"""只读核对已整理日记、正式要点与本地关系稿覆盖；不补处理、不写库。"""
import json,sys,re,hashlib,collections
from pathlib import Path
from datetime import date,datetime,timezone
PROJECT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT/'skills/diary-event-relations/scripts'))
from db_source import connection,query,load_run,object_value,array,run_identity
from workflow import WorkflowError,load_package,saved_results,progress
from draft import read_draft
# Prefer explicitly delivered current manifests, not a historical directory chosen by name.
declared={}
october=PROJECT/'diary-event-relations/批次评估/2026-10-20261023/运行清单.json'
if october.exists():
 for r in json.loads(october.read_text()):declared[r['date']]=str(Path(r['run_dir']))
september=PROJECT/'diary-event-relations/批次评估/2026-09-全量回放-20261023/执行报告与稿件索引.md'
if september.exists():
 for path in re.findall(r'\]\(<([^>]+/关系结果\.md)>\)',september.read_text()):
  f=Path(path).parent
  if (f/'source.json').exists():s=json.loads((f/'source.json').read_text());declared.setdefault(s['diary_date'],str(f))
# Inventory all other drafts so newly processed dates outside the old batch are discoverable.
drafts=collections.defaultdict(list)
for f in (PROJECT/'diary-event-relations').glob('2026-*/*/*/source.json'):
 try:
  s=json.loads(f.read_text());day=s.get('diary_date','')
  if '2026-09-01'<=day<'2026-11-01':drafts[(s['diary_id'],s['current_run_id'])].append((f.parent,s))
 except (ValueError,KeyError):continue
report={'checked_at':datetime.now(timezone.utc).isoformat(),'username':'x5456','read_only_database':True,'date_from':'2026-09-01','date_to':'2026-10-31','diaries':[]}
try:
 with connection(PROJECT/'backend') as conn:
  users=query(conn,'SELECT id FROM users WHERE username=:name',{'name':'x5456'});assert len(users)==1
  uid=str(users[0]['id'])
  diaries=query(conn,'''SELECT d.id,d.diary_date,d.status,d.is_dirty,d.content_revision,
    o.organized_at,o.updated_at AS organized_updated_at,o.id AS organized_id,o.source_content_revision,o.structured_revision
    FROM diaries d LEFT JOIN diary_organized o ON o.diary_id=d.id
    WHERE d.user_id=:uid AND d.deleted_at IS NULL AND d.diary_date>=:start AND d.diary_date<:end
    ORDER BY d.diary_date,d.id''',{'uid':uid,'start':date(2026,9,1),'end':date(2026,11,1)})
  for d in diaries:
   day=str(d['diary_date']);did=str(d['id']);events=query(conn,'SELECT id,event_title,body,feeling,reflection,sort_order,is_in_graph FROM diary_events WHERE diary_organized_id=:oid ORDER BY sort_order,id',{'oid':str(d['organized_id'])}) if d['organized_id'] else []
   event_ids={str(e['id']) for e in events}
   source_valid=bool(d['organized_id']) and d['status'] in ['organized','analyzed'] and not d['is_dirty'] and d['content_revision']==d['source_content_revision']
   content_errors=[]
   for e in events:
    try:
     body=array(e['body']);assert body and any(x.strip() for x in body)
     array(e['feeling']);array(e['reflection'])
    except (WorkflowError,AssertionError):content_errors.append(str(e['id']))
   row={'date':day,'diary_id':did,'diary_status':d['status'],'organized_exists':bool(d['organized_id']),'organized_valid':source_valid,'is_dirty':d['is_dirty'],'content_revision':d['content_revision'],'organized_source_revision':d['source_content_revision'],'structured_revision':d['structured_revision'],'organized_at':str(d['organized_at']),'organized_updated_at':str(d['organized_updated_at']),'event_count':len(events),'invalid_event_content_ids':content_errors,'in_graph_event_count':sum(bool(e['is_in_graph']) for e in events),'runs':[]}
   runs=query(conn,'SELECT id,status,task_id,error_code,checkpoint,source_snapshot FROM graph_runs WHERE diary_id=:did AND user_id=:uid ORDER BY created_at,id',{'did':did,'uid':uid})
   for run in runs:
    rid=str(run['id']);nodes=query(conn,'SELECT event_id FROM graph_run_events WHERE run_id=:rid',{'rid':rid});pts=query(conn,'SELECT event_id,count(*) AS n FROM graph_event_points WHERE run_id=:rid GROUP BY event_id',{'rid':rid})
    counts={str(p['event_id']):p['n'] for p in pts};missing=event_ids-set(counts)
    item={'run_id':rid,'status':run['status'],'error_code':run['error_code'],'nodes':len(nodes),'points':sum(counts.values()),'missing_point_events':[{'event_id':str(e['id']),'title':e['event_title']} for e in events if str(e['id']) in missing],'extra_point_event_ids':sorted(set(counts)-event_ids),'valid_points':False}
    current_data=None
    if run['status'] in ['POINTS_READY','PUBLISHED']:
     try:
      current_data,vectors=load_run(conn,uid,rid);item['valid_points']=True;item['validated_vectors']=len(vectors)
     except WorkflowError as exc:item['points_validation_error']=str(exc)
    relations=query(conn,'SELECT count(*) AS n FROM graph_event_relations WHERE run_id=:rid',{'rid':rid})[0]['n'];cp=object_value(run['checkpoint']);archive=cp.get('skill_relations')
    item['stored_relation_count']=relations;item['relations_published']=run['status']=='PUBLISHED';item['skill_relations_archive']=bool(archive)
    if archive:
     ar=object_value(archive);results=ar.get('results',[]);item['archived_judgments']=dict(collections.Counter(x.get('status') for x in results));item['archived_candidate_count']=len(results)
    if item['valid_points']:
     options=drafts.get((did,rid),[]);preferred=declared.get(day)
     options.sort(key=lambda x:(str(x[0])==preferred,str(x[0])),reverse=True)
     draft_checks=[]
     for folder,s in options:
      if not (folder/'关系结果.md').exists():continue
      check={'run_dir':str(folder),'declared_current':str(folder)==preferred,'complete':False,'package_sha256':s['package_sha256'],'history_dependency_dates':sorted({Path(x['run_dir']).parents[1].name for x in s.get('completed_dependencies',[])})}
      try:
       _,rows=read_draft(folder/'关系结果.md',s)
       check.update(complete=len(rows)==len(s['pairs']),counts=dict(collections.Counter(x['status'] for x in rows)),candidate_count=len(s['pairs']),history_mode=s.get('history_mode'),historic_dates=sorted({e['diary_date'] for e in s['events'].values() if e['run_id']!=rid}))
       actual={e['id']:run_identity(e) for e in current_data};frozen={e['id']:run_identity(e) for e in s['events'].values() if e['run_id']==rid}
       check['current_day_points_match_database']=actual==frozen
       snapshot,manifest=load_package(folder);check['dependency_and_skill_check_passed']=True
       check['all_candidates_done']=progress(snapshot,saved_results(folder,snapshot),manifest)['complete']
      except WorkflowError as exc:check['error']=str(exc)
      draft_checks.append(check)
      if check.get('declared_current') or (check.get('complete') and check.get('current_day_points_match_database') and check.get('all_candidates_done')):break
     item['local_relation_draft']=next((x for x in draft_checks if x.get('declared_current')),next((x for x in draft_checks if x.get('complete') and x.get('current_day_points_match_database') and x.get('all_candidates_done')),draft_checks[0] if draft_checks else None))
     chosen=item['local_relation_draft'];item['published_current_draft']=bool(chosen and archive and run['status']=='PUBLISHED' and archive.get('source_package_sha256')==chosen.get('package_sha256'))
     item['local_draft_attempts']=len(draft_checks)
    row['runs'].append(item)
   valid=[r for r in row['runs'] if r['valid_points']];row['valid_point_runs']=len(valid);row['points_complete']=len(valid)==1
   row['points_count']=sum(r['points'] for r in valid)
   row['relation_draft_complete']=any(r.get('local_relation_draft') and r['local_relation_draft'].get('complete') and r['local_relation_draft'].get('current_day_points_match_database') and r['local_relation_draft'].get('all_candidates_done') for r in valid)
   row['relations_published']=any(r['relations_published'] for r in valid)
   row['relation_draft_exists_and_covers_pairs']=any(r.get('local_relation_draft') and r['local_relation_draft'].get('complete') and r['local_relation_draft'].get('current_day_points_match_database') for r in valid)
   row['current_relation_draft_published']=any(r.get('published_current_draft') for r in valid)
   report['diaries'].append(row)
  report['active_graph_tasks']=[dict(r) for r in query(conn,"SELECT id,status,date_from,date_to,error_code FROM graph_tasks WHERE user_id=:uid AND status IN ('QUEUED','RUNNING')",{'uid':uid})]
 report['months']={}
 for month in ['2026-09','2026-10']:
  ds=[d for d in report['diaries'] if d['date'].startswith(month)];org=[d for d in ds if d['organized_valid']]
  report['months'][month]={'database_diaries':len(ds),'valid_organized_diaries':len(org),'organized_events':sum(d['event_count'] for d in org),'points_complete_diaries':sum(d['points_complete'] for d in org),'point_count':sum(d['points_count'] for d in org),'local_relation_complete_diaries':sum(d['relation_draft_complete'] for d in org),'local_full_draft_diaries':sum(d['relation_draft_exists_and_covers_pairs'] for d in org),'current_relation_draft_published_diaries':sum(d['current_relation_draft_published'] for d in org),'published_relation_diaries':sum(d['relations_published'] for d in org),'not_valid_organized':[{'date':d['date'],'diary_id':d['diary_id'],'status':d['diary_status'],'has_organized':d['organized_exists'],'dirty':d['is_dirty']} for d in ds if not d['organized_valid']],'processing_gaps':[{'date':d['date'],'diary_id':d['diary_id'],'events':d['event_count'],'points_complete':d['points_complete'],'relation_draft_exists_and_covers_pairs':d['relation_draft_exists_and_covers_pairs']} for d in org if not d['points_complete'] or not d['relation_draft_exists_and_covers_pairs']],'draft_rules_need_refresh':[d['date'] for d in org if d['relation_draft_exists_and_covers_pairs'] and not d['relation_draft_complete']]}
 (OUT/'核查结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
 print(json.dumps({'checked_at':report['checked_at'],'months':report['months'],'active_graph_tasks':report['active_graph_tasks']},ensure_ascii=False,indent=2,default=str))
except Exception as exc:
 print(json.dumps({'audit_failed':type(exc).__name__,'reason':str(exc) if isinstance(exc,WorkflowError) else '数据库/环境访问未完成；未输出认证信息'},ensure_ascii=False));raise SystemExit(1)
