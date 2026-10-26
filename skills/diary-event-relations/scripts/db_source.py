"""只读数据库适配；不创建任务，不调用模型，不执行迁移。"""

from contextlib import contextmanager
from pathlib import Path
import os
import sys

from workflow import (WorkflowError, digest, load_package, prepare_data, progress,
                      read_json, require, saved_results, settings, validate_events,
                      validate_vector, local_lock, write_json)


def query(connection, sql, params):
    from sqlalchemy import text
    return connection.execute(text(sql), params).mappings().all()


def backend_engine(backend):
    previous=Path.cwd()
    backend=Path(backend).resolve()
    require((backend/'database.py').is_file(),'backend 路径无效')
    try:
        os.chdir(backend);sys.path.insert(0,str(backend))
        from database import engine
    finally:
        os.chdir(previous)
    return engine


@contextmanager
def connection(backend):
    with readonly(backend_engine(backend)) as conn:yield conn


@contextmanager
def readonly(engine):
    with engine.connect() as conn:
        if conn.dialect.name=='postgresql':
            conn=conn.execution_options(isolation_level='REPEATABLE READ')
            conn.exec_driver_sql('SET TRANSACTION READ ONLY')
        elif conn.dialect.name=='sqlite':
            prior_query_only=conn.exec_driver_sql('PRAGMA query_only').scalar()
            conn.exec_driver_sql('PRAGMA query_only = ON')
        else:raise WorkflowError('不支持当前数据库的只读事务')
        try:yield conn
        finally:
            conn.rollback()
            if conn.dialect.name=='sqlite':
                conn.exec_driver_sql('PRAGMA query_only = '+str(int(prior_query_only)))
                conn.rollback()


def array(value):
    import json
    if value is None:return []
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:raise WorkflowError('来源数组不是合法 JSON') from None
    require(isinstance(value,list) and all(isinstance(x,str) for x in value),'来源内容必须为字符串数组')
    return value


def object_value(value):
    import json
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:raise WorkflowError('运行来源不是合法 JSON') from None
    require(isinstance(value,dict),'运行缺少来源快照')
    return value


def list_diaries(conn,username,day=None,diary_id=None):
    users=query(conn,'SELECT id FROM users WHERE username=:name',{'name':username})
    require(len(users)==1,'用户不存在或不唯一')
    uid=str(users[0]['id'])
    params={'uid':uid};where='d.user_id=:uid AND d.deleted_at IS NULL'
    if day is not None:where+=' AND d.diary_date=:day';params['day']=str(day)
    if diary_id is not None:where+=' AND d.id=:did';params['did']=str(diary_id)
    rows=query(conn,"""SELECT d.id,d.diary_date,d.status,d.is_dirty,
               (SELECT count(*) FROM graph_runs r WHERE r.diary_id=d.id AND r.user_id=d.user_id
                AND r.status IN ('POINTS_READY','PUBLISHED')) AS ready_runs
             FROM diaries d WHERE """+where+' ORDER BY d.diary_date,d.id',params)
    diaries=[dict(r)for r in rows]
    for diary in diaries:
        diary['runs']=[dict(r)for r in query(conn,"""SELECT id,status,created_at FROM graph_runs
              WHERE user_id=:uid AND diary_id=:did AND status IN ('POINTS_READY','PUBLISHED')
              ORDER BY created_at,id""",{'uid':uid,'did':str(diary['id'])})]
    return {'user_id':uid,'username':username,'diaries':diaries}


def run_identity(event):
    return {k:v for k,v in event.items() if k not in ('run_status','is_in_graph')}


def load_run(conn,uid,rid,*,published=False):
    rows=query(conn,"""SELECT r.id,r.diary_id,r.diary_date,r.status,r.source_organized_id,
          r.source_snapshot,r.source_sha256,d.content_revision,d.is_dirty,d.status AS diary_status,
          d.original_text,o.id AS organized_id,o.source_content_revision,o.structured_revision,
          o.introduction,o.trivia,o.plans
        FROM graph_runs r JOIN diaries d ON d.id=r.diary_id AND d.user_id=r.user_id
        JOIN diary_organized o ON o.diary_id=d.id
        WHERE r.id=:rid AND r.user_id=:uid AND d.deleted_at IS NULL""",{'rid':str(rid),'uid':uid})
    require(len(rows)==1,'指定运行不存在、不属于当前用户或整理记录不唯一')
    r=rows[0]
    require(r['status']=='PUBLISHED' if published else r['status'] in ('POINTS_READY','PUBLISHED'),'运行不是可用要点状态')
    require(r['diary_status'] in ('organized','analyzed') and not r['is_dirty']
            and r['content_revision']==r['source_content_revision'],'日记整理来源已失效')
    require(str(r['source_organized_id'])==str(r['organized_id']),'运行与当前整理记录不一致')
    source=object_value(r['source_snapshot'])
    if source.get('scope')=='EVENT_POINTS':material=source
    else:
        keys=('user_id','diary_id','diary_date','organized_id','original_text','events','introduction','trivia','plans')
        require(all(k in source for k in keys),'运行来源协议不支持')
        material={k:source[k]for k in keys}
        require(source['original_text']==r['original_text'] and source['introduction']==(r['introduction']or'')
                and source['trivia']==array(r['trivia']) and source['plans']==array(r['plans']),'运行来源正文或整篇内容已变化')
    require(digest(material)==r['source_sha256'],'数据库运行来源指纹不匹配')
    require(source['user_id']==uid and source['diary_id']==str(r['diary_id'])
            and source['diary_date']==str(r['diary_date']) and source['organized_id']==str(r['organized_id']),'运行来源归属不一致')
    if source.get('scope')=='EVENT_POINTS':
        require(source['content_revision']==r['content_revision'] and source['structured_revision']==r['structured_revision'],'要点对应的来源修订已变化')
    records=query(conn,"""SELECT id,event_title,body,feeling,reflection,sort_order,is_in_graph
            FROM diary_events WHERE diary_organized_id=:oid ORDER BY sort_order,id""",{'oid':str(r['organized_id'])})
    fresh=[{'event_id':str(e['id']),'title':e['event_title'] or '未命名事件','body':array(e['body']),
            'feeling':array(e['feeling']),'reflection':array(e['reflection']),
            'source_order':e['sort_order']}for e in records]
    frozen=source.get('events')
    require(isinstance(frozen,list) and len(frozen)==len(fresh),'来源事件范围已变化')
    require(all(all(a.get(k)==b[k] for k in b)for a,b in zip(frozen,fresh)),'事件内容、顺序或标题已变化')
    nodes=query(conn,'SELECT event_id,source_order,occurred_on FROM graph_run_events WHERE run_id=:rid AND user_id=:uid ORDER BY source_order,event_id',{'rid':str(rid),'uid':uid})
    eligible={e['event_id']:e for e in fresh}
    require({str(n['event_id'])for n in nodes}==set(eligible),'正式要点运行未覆盖全部来源事件，请先补齐缺失事件的正式要点')
    point_rows=query(conn,"""SELECT id,event_id,no,summary,detail,embedding,embedding_model FROM graph_event_points
              WHERE run_id=:rid AND user_id=:uid ORDER BY event_id,no""",{'rid':str(rid),'uid':uid})
    require(all(str(p['event_id'])in eligible for p in point_rows),'要点包含来源以外的事件')
    result,vectors=[],{}
    byid={str(e['id']):e for e in records}
    for n in nodes:
        eid=str(n['event_id']);e=eligible[eid]
        require(e['source_order']==n['source_order'],'运行事件顺序与来源不一致')
        require(not published or byid[eid]['is_in_graph'],'历史事件有效入图标志已失效')
        points=[]
        for p in point_rows:
            if str(p['event_id'])!=eid:continue
            pid=str(p['id']);v=p['embedding']
            if isinstance(v,str):
                import json
                v=json.loads(v)
            elif hasattr(v,'tolist'):v=v.tolist()
            validate_vector(v)
            require(isinstance(p['embedding_model'],str) and p['embedding_model'].strip(),'向量模型标识缺失')
            vectors[pid]={'model':p['embedding_model'],'values':v}
            points.append({'id':pid,'no':p['no'],'summary':p['summary'],'detail':p['detail'],
                           'embedding_sha256':digest(vectors[pid])})
        result.append({'id':eid,'user_id':uid,'run_id':str(rid),'run_status':r['status'],
            'diary_id':str(r['diary_id']),'diary_date':str(r['diary_date']),
            'occurred_on':str(n['occurred_on'])if n['occurred_on']else None,
            'source_order':e['source_order'],'title':e['title'],
            'run_source_sha256':r['source_sha256'],'points':points})
    if result:validate_events(result,uid)
    return result,vectors


def find(args):
    with connection(args.backend_dir)as conn:
        return list_diaries(conn,args.username,args.date,args.diary_id)


def database_history(conn, uid, day):
    """召回全部较早正式要点；另列尚无正式要点的历史日记，不依赖关系状态。"""
    diaries=query(conn,"""SELECT id FROM diaries WHERE user_id=:uid AND deleted_at IS NULL
        AND diary_date<:day AND status IN ('organized','analyzed') ORDER BY diary_date,id""",
        {'uid':uid,'day':str(day)})
    events=[];vectors={};inventory=[]
    for diary in diaries:
        did=str(diary['id'])
        runs=query(conn,"""SELECT id FROM graph_runs WHERE user_id=:uid AND diary_id=:did
            AND status IN ('POINTS_READY','PUBLISHED') ORDER BY created_at,id""",{'uid':uid,'did':did})
        if not runs:
            row=query(conn,'SELECT diary_date FROM diaries WHERE id=:did AND user_id=:uid',{'did':did,'uid':uid})[0]
            inventory.append({'diary_id':did,'diary_date':str(row['diary_date']),
                'gap':'NO_FORMAL_POINTS','event_count':0,'point_count':0})
            continue
        require(len(runs)==1, '历史日记存在多个有效运行：'+did)
        rid=str(runs[0]['id']);loaded,vs=load_run(conn,uid,rid)
        require(loaded, '历史正式要点为空：'+did)
        inventory.append({'run_id':rid,'diary_id':did,'diary_date':loaded[0]['diary_date'],
            'event_count':len(loaded),'point_count':sum(len(e['points'])for e in loaded),
            'content_sha256':digest([run_identity(e)for e in loaded])})
        events.extend(loaded);vectors.update(vs)
    return events,vectors,inventory


def prepare(args):
    with connection(args.backend_dir)as conn:
        listing=list_diaries(conn,args.username,args.date,args.diary_id)
        require(len(listing['diaries'])==1,'日记定位不是唯一结果，请 find 后按 diary-id 选择')
        uid=listing['user_id'];diary=listing['diaries'][0]
        runs=query(conn,"""SELECT id FROM graph_runs WHERE user_id=:uid AND diary_id=:did
                   AND status IN ('POINTS_READY','PUBLISHED') ORDER BY created_at,id""",{'uid':uid,'did':str(diary['id'])})
        if args.run_id:runs=[r for r in runs if str(r['id'])==str(args.run_id)]
        require(len(runs)==1,'有效要点运行不是唯一结果，请显式指定 run-id')
        current,vectors=load_run(conn,uid,runs[0]['id'])
        require(current,'当前日记没有正式事件要点')
        history,vs,inventory=database_history(conn,uid,diary['diary_date']);vectors.update(vs)
    return prepare_data(current,history,vectors,settings(),history_inventory=inventory)


def verify(args):
    from datetime import datetime, timezone
    with local_lock(args.run_dir):
        snapshot,manifest=load_package(args.run_dir)
        receipt=Path(args.run_dir)/'verification.json'
        receipt.unlink(missing_ok=True)
        with connection(args.backend_dir)as conn:
            if snapshot['history_mode']=='database':
                _,_,inventory=database_history(conn,snapshot['user_id'],snapshot['diary_date'])
                require(inventory==snapshot['history_inventory'],'数据库历史范围、正式要点或向量已变化，请新建运行')
            for rid in sorted({e['run_id']for e in snapshot['events'].values()}):
                history=rid!=snapshot['current_run_id']
                events,_=load_run(conn,snapshot['user_id'],rid,published=history and snapshot['history_mode']=='published')
                actual={e['id']:run_identity(e)for e in events}
                for frozen in snapshot['events'].values():
                    if frozen['run_id']==rid:
                        require(actual.get(frozen['id'])==run_identity(frozen),'数据库要点、向量、来源或身份已变化')
        result={'verified_against_database':True,'package_sha256':snapshot['package_sha256'],
                'verified_at':datetime.now(timezone.utc).isoformat(),'stored_in_database':False}
        write_json(receipt,result)
        return result
