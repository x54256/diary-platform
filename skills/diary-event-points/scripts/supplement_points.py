#!/usr/bin/env python3
"""从已审阅完整稿追加既有运行中缺失的事件；默认只读。"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from store_points import (StorageError, check_draft, digest, file_digest, freeze_embedding_config,
                         open_backend, parse_markdown, read_source, readonly, require, validate_vector)
from export_events import PROJECT_ROOT, json_array


@contextmanager
def reading(Session):
    from sqlalchemy import text
    with Session()as db:
        sqlite=db.get_bind().dialect.name=='sqlite'
        previous=db.execute(text('PRAGMA query_only')).scalar()if sqlite else None
        readonly(db)
        try:yield db
        finally:
            db.rollback()
            if sqlite:
                db.execute(text('PRAGMA query_only='+str(int(previous))));db.rollback()


def vector_list(value):
    if isinstance(value,str):value=json.loads(value)
    if hasattr(value,'tolist'):value=value.tolist()
    validate_vector(value);return [float(x)for x in value]


def capture(db,source,rid,*,lock=False):
    from models.user import User
    from models.diary import Diary, DiaryOrganized, DiaryEvent, DiaryStatus, OrganizeTask
    from models.graph import GraphRun, GraphTask, GraphRunEvent, GraphEventPoint
    def one(query):return (query.with_for_update()if lock else query).one_or_none()
    user=one(db.query(User).filter(User.id==UUID(source['user_id']),User.username==source['username']))
    require(user is not None,'来源用户不存在或不匹配')
    require(not db.query(GraphTask.id).filter(GraphTask.user_id==user.id,GraphTask.status.in_(('QUEUED','RUNNING'))).first(),'用户有活动图谱任务')
    require(not db.query(OrganizeTask.id).filter(OrganizeTask.user_id==user.id,OrganizeTask.status=='running').first(),'用户有活动整理或分析任务')
    diary=one(db.query(Diary).filter(Diary.id==UUID(source['diary_id']),Diary.user_id==user.id,Diary.deleted_at.is_(None)))
    require(diary is not None and diary.status in (DiaryStatus.organized,DiaryStatus.analyzed)and not diary.is_dirty,'日记来源无效')
    org=one(db.query(DiaryOrganized).filter(DiaryOrganized.diary_id==diary.id))
    require(org is not None and str(org.id)==source['organized_id']and str(diary.diary_date)==source['diary_date']
            and diary.content_revision==org.source_content_revision==source['content_revision']
            and org.structured_revision==source['structured_revision'],'来源版本已变化')
    run=one(db.query(GraphRun).filter(GraphRun.id==UUID(rid),GraphRun.diary_id==diary.id,GraphRun.user_id==user.id))
    require(run is not None and run.status in ('POINTS_READY','PUBLISHED')and run.source_organized_id==org.id,'目标不是有效原要点运行')
    require(db.query(GraphRun).filter(GraphRun.diary_id==diary.id,GraphRun.user_id==user.id,GraphRun.status.in_(('POINTS_READY','PUBLISHED'))).count()==1,'目标日记有效运行不唯一')
    owner=one(db.query(GraphTask).filter(GraphTask.id==run.task_id,GraphTask.user_id==user.id))
    require(owner is not None and owner.status=='SUCCEEDED','原要点任务不是已完成状态')
    event_query=db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id==org.id).order_by(DiaryEvent.id)
    events=(event_query.with_for_update()if lock else event_query).all()
    events.sort(key=lambda e:(e.sort_order,str(e.id)))
    fresh=[{'event_id':str(e.id),'title':e.event_title or'未命名事件','body':json_array(e.body,'正文',required=True),
        'feeling':json_array(e.feeling,'感受'),'reflection':json_array(e.reflection,'反思'),'source_order':e.sort_order,
        'is_in_graph':bool(e.is_in_graph)}for e in events]
    require([e['event_id']for e in fresh]==[e['event_id']for e in source['events']],'完整稿来源事件范围已变化')
    for actual,old in zip(fresh,source['events']):
        require(all(actual[k]==old[k]for k in ('event_id','title','body','feeling','reflection','source_order')),'稿件来源正文已变化')
    frozen=run.source_snapshot
    require(frozen and frozen.get('scope')=='EVENT_POINTS'and digest(frozen)==run.source_sha256,'原运行来源不是受支持的完整要点快照')
    require(frozen['user_id']==source['user_id']and frozen['diary_id']==source['diary_id']and frozen['diary_date']==source['diary_date']
        and frozen['organized_id']==source['organized_id']and frozen['content_revision']==source['content_revision']
        and frozen['structured_revision']==source['structured_revision'],'原运行来源归属或修订不一致')
    require(len(frozen['events'])==len(fresh),'原运行冻结事件范围不完整')
    for actual,old in zip(fresh,frozen['events']):
        require(all(actual[k]==old[k]for k in ('event_id','title','body','feeling','reflection','source_order')),'原运行冻结事实已变化')
    nodes=db.query(GraphRunEvent).filter(GraphRunEvent.run_id==run.id).order_by(GraphRunEvent.event_id).all()
    points_q=db.query(GraphEventPoint).filter(GraphEventPoint.run_id==run.id).order_by(GraphEventPoint.id)
    points=(points_q.with_for_update()if lock else points_q).all()
    node_data=[{'event_id':str(n.event_id),'user_id':str(n.user_id),'source_order':n.source_order,
        'occurred_on':str(n.occurred_on)if n.occurred_on else None}for n in nodes]
    point_data=[{'id':str(p.id),'event_id':str(p.event_id),'user_id':str(p.user_id),'no':p.no,'summary':p.summary,'detail':p.detail,
        'embedding':vector_list(p.embedding),'embedding_model':p.embedding_model}for p in points]
    data={'run_id':str(run.id),'status':run.status,'task_id':str(owner.id),'task_status':owner.status,
        'source_sha256':run.source_sha256,'checkpoint_sha256':digest(run.checkpoint or{}),'events':fresh,'nodes':node_data,'points':point_data}
    return data,run,owner,events


def source_view(source):
    """文件保留原始指纹；新包只携带正式事件身份与内容。"""
    fields=('schema_version','origin','username','user_id','diary_id','diary_date','organized_id','content_revision','structured_revision')
    view={k:deepcopy(source[k])for k in fields}
    view['events']=[{k:deepcopy(e[k])for k in ('event_id','title','body','feeling','reflection','source_order')}for e in source['events']]
    view['source_sha256']=digest(view)
    return view


def prepare(db,inputs):
    config=freeze_embedding_config();items=[];seen=set()
    for entry in inputs:
        source_path=Path(entry['source']).resolve();markdown=Path(entry['markdown']).resolve()
        source=source_view(read_source(source_path));draft=parse_markdown(markdown.read_text());check_draft(draft,source)
        data,run,owner,_=capture(db,source,entry['run_id'])
        require(str(run.id)not in seen,'补充运行重复');seen.add(str(run.id))
        require(owner.config_snapshot.get('embedding_model')==config['embedding_model'],'原要点与当前向量配置不一致，不能混用模型')
        by_event={e['event_id']:e for e in draft};nodes={n['event_id']:n for n in data['nodes']};points={}
        for p in data['points']:
            require(p['user_id']==source['user_id']and p['embedding_model']==config['embedding_model'],'原要点归属或向量模型不一致')
            points.setdefault(p['event_id'],[]).append(p)
        require(set(nodes)<=set(by_event)and set(points)<=set(nodes),'原要点或节点包含未知事件')
        for node in nodes.values():require(node['user_id']==source['user_id'],'原节点用户归属错误')
        additions=[]
        for e in data['events']:
            eid=e['event_id'];text=by_event[eid]
            if eid in nodes:
                original=sorted(points.get(eid,[]),key=lambda p:p['no'])
                require(original and [{k:p[k]for k in ('no','summary','detail')}for p in original]==text['points'],'已有要点与当前已审阅稿不一致，不覆盖')
                require(nodes[eid]['source_order']==e['source_order'],'原节点顺序异常')
                continue
            require(eid not in points,'事件已部分保存，不追加或覆盖')
            additions.append({**text,'source_order':e['source_order'],'points':[
                {**p,'id':str(uuid5(run.id,'POINTS_SUPPLEMENT:'+digest({'event_id':eid,**p,'model':config['embedding_model']})))}for p in text['points']]})
        if not additions:continue
        require(all(len(p['detail'])<=config['embedding_max_chars']for e in additions for p in e['points']),'补充详情超过向量预算，不允许截断')
        items.append({'run_id':str(run.id),'source':source,'source_file':{'path':str(source_path),'sha256':file_digest(source_path)},
            'markdown':{'path':str(markdown),'sha256':file_digest(markdown)},'before_sha256':digest(data),
            'old_events':len(nodes),'old_points':len(data['points']),
            'existing_points_sha256':digest(data['points']),'existing_nodes_sha256':digest(data['nodes']),
            'checkpoint_sha256':digest(run.checkpoint or{}),'checkpoint_keys':sorted((run.checkpoint or{}).keys()),'events':additions,'run_status':run.status})
    packet={'schema_version':2,'kind':'diary-event-points-supplement','config':config,'config_sha256':digest(config),
        'script_sha256':file_digest(__file__),'review_origin':'SKILL_USER_CONFIRMED','items':items}
    packet['confirmation_sha256']=digest(packet);return packet


def verify(packet,confirmed=None):
    require(packet.get('schema_version')==2 and packet.get('kind')=='diary-event-points-supplement','历史补充包仅支持状态查询，请用当前脚本重新预检')
    require(packet['confirmation_sha256']==digest({k:v for k,v in packet.items()if k!='confirmation_sha256'}),'补充包指纹不匹配')
    if confirmed is not None:require(confirmed==packet['confirmation_sha256'],'补充包确认指纹不匹配')
    require(packet['script_sha256']==file_digest(__file__)and packet['config_sha256']==digest(freeze_embedding_config()),'脚本或向量配置已变化')
    for item in packet['items']:
        for name in ('source_file','markdown'):
            require(file_digest(item[name]['path'])==item[name]['sha256'],'来源或已审阅稿已变化')
        require(source_view(read_source(item['source_file']['path']))==item['source'],'补充包来源不匹配')
        draft=parse_markdown(Path(item['markdown']['path']).read_text());check_draft(draft,item['source'])
        byid={e['event_id']:e for e in draft}
        for e in item['events']:
            require(e['title']==byid[e['event_id']]['title']and
                [{k:p[k]for k in ('no','summary','detail')}for p in e['points']]==byid[e['event_id']]['points'],'补充包要点不对应已审阅稿')


def publish(Session,packet,vectors,confirmed):
    from models.graph import GraphRunEvent, GraphEventPoint, utcnow
    verify(packet,confirmed)
    with Session()as db:
        # 原入口同样先锁用户；一次事务追加全部日期，任一来源变化则全部回滚。
        for item in sorted(packet['items'],key=lambda i:i['run_id']):
            data,run,owner,records=capture(db,item['source'],item['run_id'],lock=True)
            prior=(run.checkpoint or{}).get('point_supplements',{}).get(packet['confirmation_sha256'])
            if prior:
                require(prior.get('stored')is True,'原补充记录状态不完整')
                continue
            require(digest(data)==item['before_sha256'],'正式来源、原要点或检查点已变化，停止补充')
            checkpoint=deepcopy(run.checkpoint or{});byid={str(e.id):e for e in records}
            for event in item['events']:
                eid=event['event_id']
                db.add(GraphRunEvent(run_id=run.id,event_id=UUID(eid),user_id=run.user_id,source_order=event['source_order']))
                db.flush()
                for point in event['points']:
                    vector=vectors[point['id']];validate_vector(vector)
                    db.add(GraphEventPoint(id=UUID(point['id']),run_id=run.id,event_id=UUID(eid),user_id=run.user_id,
                        no=point['no'],summary=point['summary'],detail=point['detail'],embedding=vector,embedding_model=packet['config']['embedding_model']))
                checkpoint.setdefault('point_work',{})[eid]={'review_origin':'SKILL_USER_CONFIRMED','points':[
                    {**p,'run_id':str(run.id),'event_id':eid}for p in event['points']]}
                checkpoint.setdefault('vectors',{}).update({p['id']:vectors[p['id']]for p in event['points']})
                # 已发布运行新增的是孤立事件节点，不新增或改写任何关系边。
                if run.status=='PUBLISHED':byid[eid].is_in_graph=True
            checkpoint.setdefault('point_supplements',{})[packet['confirmation_sha256']]={
                'stored':True,'review_origin':'SKILL_USER_CONFIRMED','published_at':utcnow().isoformat(),
                'source_file':item['source_file'],'markdown':item['markdown'],'events':item['events'],
                'embedding_model':packet['config']['embedding_model'],'prior_events':item['old_events'],'prior_points':item['old_points'],
                'relation_review':'NOT_RUN_FOR_SUPPLEMENTED_EVENTS','published_run':run.status=='PUBLISHED'}
            run.checkpoint=checkpoint;run.updated_at=utcnow();db.flush()
        db.commit()
    return status(Session,packet)


def status(Session,packet):
    from models.graph import GraphRun,GraphEventPoint,GraphRunEvent
    result=[]
    with reading(Session)as db:
        for item in packet['items']:
            run=db.get(GraphRun,UUID(item['run_id']));archive=(run.checkpoint or{}).get('point_supplements',{}).get(packet['confirmation_sha256'])if run else None
            actual=db.query(GraphEventPoint).filter(GraphEventPoint.run_id==UUID(item['run_id']),GraphEventPoint.event_id.in_([UUID(e['event_id'])for e in item['events']])).all()
            expected={p['id']:(p,e['event_id'])for e in item['events']for p in e['points']}
            match=len(actual)==len(expected)and all(str(p.id)in expected and p.no==expected[str(p.id)][0]['no']
                and p.summary==expected[str(p.id)][0]['summary']and p.detail==expected[str(p.id)][0]['detail']
                and str(p.event_id)==expected[str(p.id)][1]and p.embedding_model==packet['config']['embedding_model']
                and len(vector_list(p.embedding))==1024 for p in actual)
            selected={e['event_id']for e in item['events']}
            original=db.query(GraphEventPoint).filter(GraphEventPoint.run_id==UUID(item['run_id'])).order_by(GraphEventPoint.id).all()
            original=[{'id':str(p.id),'event_id':str(p.event_id),'user_id':str(p.user_id),'no':p.no,'summary':p.summary,'detail':p.detail,
                'embedding':vector_list(p.embedding),'embedding_model':p.embedding_model}for p in original if str(p.event_id)not in selected]
            old_nodes=db.query(GraphRunEvent).filter(GraphRunEvent.run_id==UUID(item['run_id'])).order_by(GraphRunEvent.event_id).all()
            old_nodes=[{'event_id':str(n.event_id),'user_id':str(n.user_id),'source_order':n.source_order,
                'occurred_on':str(n.occurred_on)if n.occurred_on else None}for n in old_nodes if str(n.event_id)not in selected]
            unchanged=digest(original)==item['existing_points_sha256']and digest(old_nodes)==item['existing_nodes_sha256']
            if archive:
                old_cp=deepcopy(run.checkpoint)
                old_cp['point_supplements'].pop(packet['confirmation_sha256'])
                for event in item['events']:
                    old_cp.get('point_work',{}).pop(event['event_id'],None)
                    for point in event['points']:old_cp.get('vectors',{}).pop(point['id'],None)
                for key in ('point_supplements','point_work','vectors'):
                    if key not in item['checkpoint_keys']and not old_cp.get(key):old_cp.pop(key,None)
                unchanged=unchanged and digest(old_cp)==item['checkpoint_sha256']
            result.append({'date':item['source']['diary_date'],'run_id':item['run_id'],'stored':bool(archive and archive.get('stored')and match and unchanged),'existing_content_unchanged':unchanged,
                'events':len(item['events']),'points':len(expected),'actual_points':len(actual),'run_status':run.status if run else None})
    return {'stored':bool(result)and all(r['stored']for r in result),'events':sum(r['events']for r in result),'points':sum(r['points']for r in result),'items':result}


def embed(Session,packet):
    """复用冻结渠道及1024维协议；实际请求记录在原运行的独立补充调用阶段。"""
    import httpx
    from models.graph import GraphModelCall,utcnow
    from services.graph_runtime import thaw_model
    model=packet['config']['models']['embedding'];base,key=thaw_model(model);vectors={}
    total=sum(len(e['points'])for item in packet['items']for e in item['events'])
    with httpx.Client(timeout=60)as client:
        for item in packet['items']:
            for event in item['events']:
                for point in event['points']:
                    body={'model':model['model_name'],'input':[point['detail']],'dimensions':1024,'encoding_format':'float'}
                    request_hash=digest({'body':body,'model':model})
                    with Session()as db:
                        data,run,owner,_=capture(db,item['source'],item['run_id'],lock=True)
                        require(digest(data)==item['before_sha256'],'准备向量前来源或原要点已变化')
                        calls=db.query(GraphModelCall).filter(GraphModelCall.run_id==run.id,GraphModelCall.stage=='SUPPLEMENT_EMBED',GraphModelCall.unit_key==point['id']).order_by(GraphModelCall.attempt_no).all()
                        cached=next((r for r in calls if r.status=='SUCCEEDED'and r.request_snapshot.get('base_sha256')==request_hash),None)
                        if cached:
                            vectors[point['id']]=vector_list(cached.parsed_result['data'][0]['embedding']);continue
                        record=GraphModelCall(task_id=owner.id,run_id=run.id,stage='SUPPLEMENT_EMBED',unit_key=point['id'],
                            attempt_no=max((r.attempt_no for r in calls),default=0)+1,status='STARTED',
                            request_snapshot={'body':body,'model':model,'base_sha256':request_hash,'supplement_sha256':packet['confirmation_sha256']})
                        db.add(record);db.flush();call_id=record.id;db.commit()
                    try:
                        response=client.post(base+'/embeddings',headers={'Authorization':'Bearer '+key},json=body)
                        require(response.status_code==200,'向量服务返回 HTTP '+str(response.status_code))
                        raw=response.json();rows=raw.get('data')
                        require(isinstance(rows,list)and len(rows)==1 and rows[0].get('index')==0,'向量响应条数或索引异常')
                        vector=vector_list(rows[0]['embedding']);usage=raw.get('usage')or{}
                    except Exception as error:
                        with Session()as db:
                            rec=db.get(GraphModelCall,call_id);rec.status='FAILED';rec.completed_at=utcnow();rec.error_code='SUPPLEMENT_EMBED_FAILED';rec.error_message=type(error).__name__;rec.validation_errors=['补充向量请求失败'];db.commit()
                        raise StorageError('补充向量失败，已保留调用记录，可使用同包恢复')from None
                    with Session()as db:
                        rec=db.get(GraphModelCall,call_id);rec.status='SUCCEEDED';rec.completed_at=utcnow()
                        rec.parsed_result={'data':[{'index':0,'embedding':vector}]};rec.response_text=response.text.replace(key,'[已隐藏]')if key else response.text
                        rec.input_tokens=usage.get('prompt_tokens');db.commit()
                    vectors[point['id']]=vector
                    print(json.dumps({'phase':'embedding','completed':len(vectors),'total':total}),flush=True)
    return vectors


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend-dir',type=Path,default=PROJECT_ROOT/'backend')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for name in ('save','status'):
        p=sub.add_parser(name);p.add_argument('packet',type=Path)
        if name=='save':p.add_argument('--write',action='store_true');p.add_argument('--confirmed-sha256')
    args=parser.parse_args()
    for name in ('inputs','output','packet'):
        if hasattr(args,name):setattr(args,name,getattr(args,name).resolve())
    try:
        Session=open_backend(args.backend_dir)
        if args.command=='prepare':
            require(not args.output.exists(),'补充包已存在，不覆盖')
            with reading(Session)as db:
                packet=prepare(db,json.loads(args.inputs.read_text()))
            with args.output.open('x')as f:json.dump(packet,f,ensure_ascii=False,indent=2)
            result={'events':sum(len(i['events'])for i in packet['items']),'points':sum(len(e['points'])for i in packet['items']for e in i['events']),
                'diaries':len(packet['items']),'confirmation_sha256':packet['confirmation_sha256'],'stored':False}
        else:
            packet=json.loads(args.packet.read_text())
            if args.command=='status':result=status(Session,packet)
            else:
                verify(packet,args.confirmed_sha256 if args.write else None)
                existing=status(Session,packet)
                if existing['stored']:result=existing
                elif args.write:
                    require(args.confirmed_sha256==packet['confirmation_sha256'],'写入需匹配当前确认包指纹')
                    vectors=embed(Session,packet);result=publish(Session,packet,vectors,args.confirmed_sha256)
                else:
                    with reading(Session)as db:
                        for item in packet['items']:require(digest(capture(db,item['source'],item['run_id'])[0])==item['before_sha256'],'原运行已变化')
                        db.rollback()
                    result={'stored':False,'validated':True}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except StorageError as exc:print(json.dumps({'error':str(exc)},ensure_ascii=False));return 1
    except Exception as exc:print(json.dumps({'error':type(exc).__name__,'message':'补充未完成；请先查询状态，未输出认证信息'},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
