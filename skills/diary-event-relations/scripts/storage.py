"""独立关系入库包与仅补关系的短事务发布；不调用模型、不重新保存要点。"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import UUID, uuid5

from db_source import backend_engine, connection, load_run, object_value, query, readonly, run_identity
from workflow import (PROJECT_ROOT, VERSION, WorkflowError, check_rows, digest, load_package,
                      local_lock, progress, read_json, require, saved_results,
                      validate_events, write_json)

STORAGE_VERSION = 2
FINAL_SOURCE = 'SKILL_AGENT'


def resolve(snapshot, rows):
    """归一化结果，所有状态均保留真实两端身份；证据位置由程序重算。"""
    check_rows(snapshot, {'package_sha256':snapshot['package_sha256'], 'results':rows})
    pairs = {p['pair_id']:p for p in snapshot['pairs']}
    require(len(rows)==len(pairs) and {r['pair_id']for r in rows}==set(pairs), '全部事件对完成后才能准备入库包')
    output=[]
    for row in sorted(rows, key=lambda r:r['pair_id']):
        pair=pairs[row['pair_id']]
        a,b=(snapshot['events'][pair[k]]for k in ('event_a','event_b'))
        result={'pair_id':row['pair_id'],'event_a_id':a['id'],'event_a_run_id':a['run_id'],
                'event_b_id':b['id'],'event_b_run_id':b['run_id'],'status':row['status'],
                'reason':row['reason'],'relation':None}
        if row['relation']:
            rel=row['relation']
            value={k:rel[k]for k in ('relation_type','certainty','description')}
            for side in ('source','target'):
                event=snapshot['events'][rel[side+'_event']]
                value[side+'_event_id']=event['id'];value[side+'_run_id']=event['run_id']
                proofs=[]
                for proof in sorted(rel[side+'_evidence'],key=lambda p:p['point_no']):
                    point=next(p for p in event['points']if p['no']==proof['point_no'])
                    proofs.append({**proof,'point_id':point['id'],'point_event_id':event['id'],
                                   'point_run_id':event['run_id'],'offset':point['detail'].index(proof['quote']),
                                   'offset_unit':'unicode_codepoint','detail_sha256':digest(point['detail'])})
                value[side+'_evidence']=proofs
            result['relation']=value
        output.append(result)
    return output


def result_digest(snapshot, resolved):
    return digest({'schema_version':STORAGE_VERSION,'source_package_sha256':snapshot['package_sha256'],
                   'results':resolved})


def canonical_rows(rows):
    result=deepcopy(rows)
    for row in result:
        if row['relation']:
            for side in ('source','target'):
                row['relation'][side+'_evidence'].sort(key=lambda x:x['point_no'])
    return sorted(result,key=lambda row:row['pair_id'])


def build_packet(folder, username, markdown=None):
    with local_lock(folder):
        snapshot,manifest=load_package(folder)
        from draft import read_draft, text_sha, FORMAT_VERSION
        markdown=Path(markdown)if markdown is not None else Path(folder)/'关系结果.md'
        content,parsed=read_draft(markdown,snapshot)
        rows=canonical_rows(parsed)
        require(progress(snapshot,rows,manifest)['complete'],'识别尚未完成')
        resolved=resolve(snapshot,rows)
        dependencies=[]
        for dependency in snapshot['completed_dependencies']:
            prior,pm=load_package(dependency['run_dir'])
            prior_rows=canonical_rows(saved_results(dependency['run_dir'],prior))
            dependencies.append({'run_id':prior['current_run_id'],'source_package_sha256':prior['package_sha256'],
                                 'results_sha256':result_digest(prior,resolve(prior,prior_rows))})
        packet={'schema_version':STORAGE_VERSION,'kind':'diary-event-relations-storage',
                'username':username,'user_id':snapshot['user_id'],'diary_id':snapshot['diary_id'],
                'diary_date':snapshot['diary_date'],'current_run_id':snapshot['current_run_id'],
                'source_package_sha256':snapshot['package_sha256'],'skill_sha256':snapshot['skill_sha256'],
                'review_origin':'SKILL_AGENT_REVIEW','final_source':FINAL_SOURCE,
                'snapshot':deepcopy(snapshot),'results':rows,'resolved_results':resolved,
                'draft':{'format_version':FORMAT_VERSION,'path':str(markdown.resolve()),'content':content,'sha256':text_sha(content)},
                'results_sha256':result_digest(snapshot,resolved),
                'publication_dependencies':sorted(dependencies,key=lambda d:d['run_id'])}
        packet['storage_sha256']=digest(packet)
        return packet


def validate_packet(packet, *, current_skill=True):
    fields={'schema_version','kind','username','user_id','diary_id','diary_date','current_run_id',
            'source_package_sha256','skill_sha256','review_origin','final_source','snapshot','results',
            'resolved_results','results_sha256','publication_dependencies','storage_sha256'}
    require(isinstance(packet,dict),'入库包必须为对象')
    if packet.get('schema_version')==2:fields.add('draft')
    require(set(packet)==fields,'入库包字段不完整或含未知字段')
    require(packet['schema_version']in (1,STORAGE_VERSION) and packet['kind']=='diary-event-relations-storage','入库包协议版本不支持')
    require(packet['storage_sha256']==digest({k:v for k,v in packet.items()if k!='storage_sha256'}),'入库包内容指纹不匹配')
    require(packet['review_origin']=='SKILL_AGENT_REVIEW' and packet['final_source']==FINAL_SOURCE,'结果来源不支持')
    require(isinstance(packet['username'],str) and packet['username'].strip(),'入库包缺少用户定位')
    snapshot=packet['snapshot']
    require(snapshot['schema_version']==VERSION and snapshot['kind']=='diary-event-relations-readonly','来源协议不支持')
    require(snapshot['package_sha256']==digest({k:v for k,v in snapshot.items()if k!='package_sha256'}),'冻结来源指纹不匹配')
    require(snapshot['package_sha256']==packet['source_package_sha256'] and snapshot['skill_sha256']==packet['skill_sha256'],'入库包与来源版本不一致')
    if current_skill:
        require(packet['schema_version']==STORAGE_VERSION,'旧版包仅支持状态查询，请用当前关系稿重新准备入库包')
    for key in ('user_id','diary_id','diary_date','current_run_id'):
        require(packet[key]==snapshot[key],'用户、日期或运行归属不匹配')
    validate_events(list(snapshot['events'].values()),packet['user_id'])
    current=[e for e in snapshot['events'].values()if e['run_id']==packet['current_run_id']]
    require(current and all(e['diary_id']==packet['diary_id'] and e['diary_date']==packet['diary_date']for e in current),'当前运行事件不完整或归属错误')
    seen=set()
    for pair in snapshot['pairs']:
        require(pair['event_a']in snapshot['events'] and pair['event_b']in snapshot['events'],'配对端点不存在')
        a,b=(snapshot['events'][pair[k]]for k in ('event_a','event_b'))
        require(a['id']!=b['id'] and (a in current or b in current),'配对必须包含当前运行端点')
        key=tuple(sorted((a['id'],b['id'])))
        require(key not in seen,'无序事件对重复');seen.add(key)
        for e in (a,b):require(e['run_id']==packet['current_run_id'] or e['diary_date']<packet['diary_date'],'历史端点日期非法')
    if packet['schema_version']==2:
        from draft import parse_text, text_sha, FORMAT_VERSION
        draft=packet['draft']
        require(isinstance(draft,dict)and set(draft)=={'format_version','path','content','sha256'},'稿件快照字段不完整')
        require(draft['format_version']==FORMAT_VERSION and isinstance(draft['content'],str)and isinstance(draft['path'],str),'稿件快照格式不合法')
        require(draft['sha256']==text_sha(draft['content']),'稿件内容指纹不匹配')
        require(canonical_rows(parse_text(draft['content'],snapshot))==packet['results'],'入库结果与关系稿不一致')
    expected=resolve(snapshot,packet['results'])
    require(expected==packet['resolved_results'] and digest({'schema_version':packet['schema_version'],'source_package_sha256':snapshot['package_sha256'],'results':expected})==packet['results_sha256'],'最终结果指纹或身份映射不一致')
    require(isinstance(packet['publication_dependencies'],list),'发布依赖结构不合法')
    ids=[]
    for dep in packet['publication_dependencies']:
        require(set(dep)=={'run_id','source_package_sha256','results_sha256'},'发布依赖字段不合法')
        UUID(dep['run_id']);ids.append(dep['run_id'])
    require(len(set(ids))==len(ids) and packet['current_run_id']not in ids,'发布依赖重复或引用自身')
    frozen_deps={d['run_id']:d['package_sha256']for d in snapshot['completed_dependencies']}
    require({d['run_id']:d['source_package_sha256']for d in packet['publication_dependencies']}==frozen_deps,'独立入库包遗漏或增加了回放依赖')
    return packet


def schema_ready(conn):
    from sqlalchemy import inspect
    constraints=inspect(conn).get_check_constraints('graph_event_relations')
    sql=next((c['sqltext']for c in constraints if c['name']=='ck_graph_relation_description'),'')
    return 'SKILL_AGENT' in sql and 'AGREEMENT' in sql and 'ADJUDICATED' in sql


def schema(conn, *, write=False):
    if schema_ready(conn):return {'skill_source_supported':True,'changed':False}
    if not write:return {'skill_source_supported':False,'changed':False}
    require(conn.dialect.name=='postgresql','固定迁移仅支持 PostgreSQL')
    from sqlalchemy import inspect, text
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('diary:skill_relations:schema'))"))
    if schema_ready(conn):return {'skill_source_supported':True,'changed':False}
    sql=next((c['sqltext']for c in inspect(conn).get_check_constraints('graph_event_relations')
              if c['name']=='ck_graph_relation_description'),None)
    require(sql is not None and set(re.findall(r"'([^']*)'",sql))- {''}=={'AGREEMENT','ADJUDICATED'}
            and 'btrim' in sql and 'description' in sql,'现有结果来源约束偏离旧基线，停止迁移')
    migration=PROJECT_ROOT/'backend/migrations/052_skill_event_relations.sql'
    value=re.sub(r'--[^\n]*','',migration.read_text())
    for statement in value.split(';'):
        if statement.strip():conn.execute(text(statement))
    require(schema_ready(conn),'迁移后 Skill 来源仍不可用')
    return {'skill_source_supported':True,'changed':True}


def owned(conn, packet, username):
    require(username==packet['username'],'执行用户与入库包不符')
    rows=query(conn,'SELECT id FROM users WHERE username=:name AND id=:uid',{'name':username,'uid':packet['user_id']})
    require(len(rows)==1,'入库用户不存在或归属不匹配')


def archive_for(conn, packet):
    rows=query(conn,'SELECT status,checkpoint FROM graph_runs WHERE id=:rid AND user_id=:uid',
               {'rid':packet['current_run_id'],'uid':packet['user_id']})
    require(len(rows)==1,'目标运行不存在或归属不符')
    checkpoint=object_value(rows[0]['checkpoint'])
    return rows[0]['status'],checkpoint,checkpoint.get('skill_relations')


def inspect_target(conn, packet, username, *, replace_published=False, accept_published_revisions=False):
    """只读复验；历史仅要求有效正式要点，不要求关系已发布。"""
    owned(conn,packet,username)
    snapshot=packet['snapshot']
    for rid in sorted({e['run_id']for e in snapshot['events'].values()}):
        events,_=load_run(conn,packet['user_id'],rid)
        actual={e['id']:run_identity(e)for e in events}
        expected={e['id']:run_identity(e)for e in snapshot['events'].values()if e['run_id']==rid}
        require(all(actual.get(eid)==e for eid,e in expected.items()),'数据库要点、向量或来源已变化')
        if rid==packet['current_run_id']:require(actual==expected,'当前运行事件覆盖不完整')
    # 旧包的回放依赖仅保留身份及来源有效性检查，不依赖关系发布状态或结果版本。
    for dep in packet['publication_dependencies']:
        rows=query(conn,'SELECT diary_date FROM graph_runs WHERE id=:rid AND user_id=:uid',
                   {'rid':dep['run_id'],'uid':packet['user_id']})
        require(len(rows)==1 and str(rows[0]['diary_date'])<packet['diary_date'],'历史依赖不存在、跨用户或日期非法')
        load_run(conn,packet['user_id'],dep['run_id'])
    status,checkpoint,archive=archive_for(conn,packet)
    stored=bool(status=='PUBLISHED' and archive and archive.get('storage_sha256')==packet['storage_sha256'])
    replacing=bool(status=='PUBLISHED' and not stored and replace_published and archive)
    require(status=='POINTS_READY' or stored or replacing,'目标已发布其他结果或已失效，不支持覆盖重建')
    if status=='POINTS_READY':
        require(archive is None,'目标存在其他 Skill 发布记录，不覆盖')
        require(not query(conn,'SELECT id FROM graph_event_relations WHERE run_id=:rid',{'rid':packet['current_run_id']}),'目标已有关系，不覆盖')
        require(not query(conn,"SELECT id FROM graph_runs WHERE user_id=:uid AND diary_id=:did AND status='PUBLISHED' AND id<>:rid",
                          {'uid':packet['user_id'],'did':packet['diary_id'],'rid':packet['current_run_id']}),'该日记已有另一有效已发布运行')
    return {'stored':stored,'run_status':status,'replacing_published':replacing,
            'accept_published_revisions':accept_published_revisions,'missing_published_dependencies':[],
            'skill_source_supported':schema_ready(conn),'relations':sum(r['status']=='RELATED'for r in packet['results']),
            'pairs':len(packet['results']),'storage_sha256':packet['storage_sha256'],'results_sha256':packet['results_sha256']}


def lock_inputs(conn, packet):
    """与原图谱创建/重试及要点入口共用用户行锁；来源写入再由行锁串行化。"""
    from sqlalchemy import text
    suffix=' FOR UPDATE'if conn.dialect.name=='postgresql'else''
    require(query(conn,'SELECT id FROM users WHERE id=:uid'+suffix,{'uid':packet['user_id']}),'用户不存在')
    require(not query(conn,"SELECT id FROM graph_tasks WHERE user_id=:uid AND status IN ('QUEUED','RUNNING')",{'uid':packet['user_id']}),'该用户已有活动图谱任务')
    require(not query(conn,"SELECT id FROM organize_tasks WHERE user_id=:uid AND status='running'",{'uid':packet['user_id']}),'该用户已有活动整理或分析任务')
    events=list(packet['snapshot']['events'].values())
    run_ids={e['run_id']for e in events}|{d['run_id']for d in packet['publication_dependencies']}
    diary_ids={e['diary_id']for e in events}
    for rid in sorted(run_ids):
        diary_ids.update(str(r['diary_id'])for r in query(conn,'SELECT diary_id FROM graph_runs WHERE id=:rid AND user_id=:uid',{'rid':rid,'uid':packet['user_id']}))
    for did in sorted(diary_ids):
        query(conn,'SELECT id FROM diaries WHERE id=:id AND user_id=:uid'+suffix,{'id':did,'uid':packet['user_id']})
    for rid in sorted(run_ids):
        query(conn,'SELECT id FROM graph_runs WHERE id=:id AND user_id=:uid'+suffix,{'id':rid,'uid':packet['user_id']})
    for did in sorted(diary_ids):
        orgs=query(conn,'SELECT id FROM diary_organized WHERE diary_id=:id ORDER BY id'+suffix,{'id':did})
        for org in orgs:
            query(conn,'SELECT id FROM diary_events WHERE diary_organized_id=:id ORDER BY id'+suffix,{'id':str(org['id'])})
    for rid in sorted(run_ids):
        query(conn,'SELECT id FROM graph_event_points WHERE run_id=:id ORDER BY id'+suffix,{'id':rid})


def publish(conn, packet, username, confirmed_sha256, *, replace_published=False, accept_published_revisions=False):
    """调用者必须使用一个短事务；任何失败由事务整体回滚。"""
    from sqlalchemy import text
    validate_packet(packet)
    require(confirmed_sha256==packet['storage_sha256'],'--confirmed-sha256 不对应当前完整入库包')
    owned(conn,packet,username);lock_inputs(conn,packet)
    state=inspect_target(conn,packet,username,replace_published=replace_published,
                         accept_published_revisions=accept_published_revisions)
    require(state['skill_source_supported'],'数据库尚未支持 SKILL_AGENT，请先显式执行固定迁移')
    if state['stored']:return state
    stamp=datetime.now(timezone.utc).isoformat();ids={}
    _,checkpoint,previous_archive=archive_for(conn,packet)
    checkpoint=deepcopy(checkpoint)
    if state['replacing_published']:
        parameters={'rid':packet['current_run_id'],'uid':packet['user_id']}
        old_edges=query(conn,'SELECT * FROM graph_event_relations WHERE run_id=:rid AND user_id=:uid ORDER BY id',parameters)
        old_evidence=query(conn,'''SELECT e.* FROM graph_relation_evidence e
            JOIN graph_event_relations r ON r.id=e.relation_id
            WHERE r.run_id=:rid AND r.user_id=:uid ORDER BY e.relation_id,e.side,e.point_id''',parameters)
        backup=json.loads(json.dumps({'replaced_at':stamp,'archive':previous_archive,
            'relations':[dict(r)for r in old_edges],'evidence':[dict(e)for e in old_evidence]},default=str))
        checkpoint.setdefault('skill_relations_history',[]).append(backup)
        conn.execute(text('''DELETE FROM graph_relation_evidence WHERE relation_id IN
            (SELECT id FROM graph_event_relations WHERE run_id=:rid AND user_id=:uid)'''),parameters)
        conn.execute(text('DELETE FROM graph_event_relations WHERE run_id=:rid AND user_id=:uid'),parameters)
    for row in packet['resolved_results']:
        if row['status']!='RELATED':continue
        rel=row['relation'];rid=str(uuid5(UUID(packet['current_run_id']),packet['storage_sha256']+':'+row['pair_id']))
        params={k:rel[k]for k in ('source_run_id','source_event_id','target_run_id','target_event_id','relation_type','certainty','description')}
        params.update(id=rid,run_id=packet['current_run_id'],user_id=packet['user_id'],final_source=FINAL_SOURCE,created_at=stamp)
        conn.execute(text('''INSERT INTO graph_event_relations
            (id,run_id,user_id,source_run_id,source_event_id,target_run_id,target_event_id,relation_type,certainty,description,final_source,created_at)
            VALUES (:id,:run_id,:user_id,:source_run_id,:source_event_id,:target_run_id,:target_event_id,:relation_type,:certainty,:description,:final_source,:created_at)'''),params)
        ids[row['pair_id']]=rid
        for side in ('source','target'):
            for proof in rel[side+'_evidence']:
                values={k:params[k]for k in ('user_id','source_run_id','source_event_id','target_run_id','target_event_id')}
                values.update(relation_id=rid,side=side.upper(),point_id=proof['point_id'],point_run_id=proof['point_run_id'],point_event_id=proof['point_event_id'])
                conn.execute(text('''INSERT INTO graph_relation_evidence
                    (relation_id,side,point_id,user_id,source_run_id,source_event_id,target_run_id,target_event_id,point_run_id,point_event_id)
                    VALUES (:relation_id,:side,:point_id,:user_id,:source_run_id,:source_event_id,:target_run_id,:target_event_id,:point_run_id,:point_event_id)'''),values)
    checkpoint['skill_relations']={'schema_version':STORAGE_VERSION,'storage_sha256':packet['storage_sha256'],
        'source_package_sha256':packet['source_package_sha256'],'results_sha256':packet['results_sha256'],
        'skill_sha256':packet['skill_sha256'],'review_origin':packet['review_origin'],'final_source':FINAL_SOURCE,
        'published_at':stamp,'authorization':'EXPLICIT_CLI_WRITE_WITH_MATCHED_PACKET_SHA256',
        'publication_options':{'replace_published':replace_published,'accept_published_revisions':accept_published_revisions},
        'snapshot':packet['snapshot'],'results':packet['resolved_results'],
        'publication_dependencies':packet['publication_dependencies'],'relation_ids':ids,'draft':packet['draft']}
    for event in packet['snapshot']['events'].values():
        if event['run_id']==packet['current_run_id']:
            conn.execute(text('UPDATE diary_events SET is_in_graph=true WHERE id=:id'),{'id':event['id']})
    encoded='CAST(:checkpoint AS jsonb)'if conn.dialect.name=='postgresql'else':checkpoint'
    conn.execute(text("UPDATE graph_runs SET checkpoint="+encoded+",status='PUBLISHED',published_at=:stamp,updated_at=:stamp,current_step=NULL WHERE id=:rid AND user_id=:uid"),
                 {'checkpoint':json.dumps(checkpoint,ensure_ascii=False,allow_nan=False),'stamp':stamp,'rid':packet['current_run_id'],'uid':packet['user_id']})
    return {**state,'stored':True,'run_status':'PUBLISHED','relation_ids':ids}


def execute(args):
    if args.command=='schema':
        engine=backend_engine(args.backend_dir)
        if args.write:
            with engine.begin()as conn:return schema(conn,write=True)
        with readonly(engine)as conn:return schema(conn)
    if args.command=='prepare-storage':
        packet=build_packet(args.run_dir,args.username,getattr(args,'markdown',None))
        with connection(args.backend_dir)as conn:state=inspect_target(conn,packet,args.username,
            replace_published=getattr(args,'replace_published',False),
            accept_published_revisions=getattr(args,'accept_published_revisions',False))
        if args.output is None:args.output=args.run_dir/('入库包-事件关系-'+packet['storage_sha256'][:16]+'.json')
        require(not args.output.exists(),'入库包输出已存在，不能覆盖；可直接复验已有同包')
        with args.output.open('x',encoding='utf-8')as stream:json.dump(packet,stream,ensure_ascii=False,indent=2);stream.write('\n')
        return {**state,'packet_file':str(args.output.resolve()),'ready_to_publish':state['skill_source_supported']}
    packet=validate_packet(read_json(args.packet),current_skill=args.command!='storage-status')
    if args.command=='storage-status':
        with connection(args.backend_dir)as conn:
            owned(conn,packet,args.username);status,_,archive=archive_for(conn,packet)
            return {'stored':bool(status=='PUBLISHED'and archive and archive.get('storage_sha256')==packet['storage_sha256']),
                    'run_status':status,'storage_sha256':packet['storage_sha256'],
                    'archived':bool(archive and archive.get('storage_sha256')==packet['storage_sha256'])}
    if args.write:
        with backend_engine(args.backend_dir).begin()as conn:return publish(conn,packet,args.username,args.confirmed_sha256,
            replace_published=getattr(args,'replace_published',False),
            accept_published_revisions=getattr(args,'accept_published_revisions',False))
    with connection(args.backend_dir)as conn:
        state=inspect_target(conn,packet,args.username,replace_published=getattr(args,'replace_published',False),
            accept_published_revisions=getattr(args,'accept_published_revisions',False))
        return {**state,'ready_to_publish':state['skill_source_supported']}
