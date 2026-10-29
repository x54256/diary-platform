#!/usr/bin/env python3
"""冻结已审阅要点，确认后只保存要点及向量；默认只读，不重新生成文字。"""

import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta, timezone
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from skill_files import read_bytes, read_text
import re
from uuid import UUID, uuid4

from export_events import PROJECT_ROOT, SKILL_ROOT, ExportError, digest


class StorageError(Exception):
    """仅承载可展示的脱敏业务错误。"""


def require(condition, message):
    if not condition:
        raise StorageError(message)


def file_digest(path):
    import hashlib
    return hashlib.sha256(read_bytes(path)).hexdigest()


def open_backend(path):
    backend = Path(path).resolve()
    require((backend / 'database.py').is_file(), 'backend 路径无效')
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    import models  # noqa: F401
    from database import SessionLocal
    return SessionLocal


def parse_markdown(value):
    """只解析已约定格式；遇到不认识的结构即停止，不猜测事件对应。"""
    require('```' not in value, '入库稿不支持代码围栏，请保留原稿并另存兼容版本')
    events, event, point = [], None, None
    for line in value.splitlines():
        heading = re.fullmatch(r'## 事件：(.+)', line)
        identity = re.fullmatch(r'<!-- event_id: ([0-9a-fA-F-]{36}) -->', line)
        item = re.fullmatch(r'### ([1-9][0-9]*)\. (.+)', line)
        if heading:
            event = {'title': heading[1], 'event_id': None, 'points': []}
            events.append(event)
            point = None
        elif identity:
            require(event is not None and point is None and event['event_id'] is None,
                    '事件 ID 注释必须在所属事件首个要点之前，且只出现一次')
            event['event_id'] = str(UUID(identity[1]))
        elif item:
            require(event is not None and event['event_id'] is not None, '每个事件必须先提供 event_id 注释')
            point = {'no': int(item[1]), 'summary': item[2], 'lines': []}
            event['points'].append(point)
        else:
            require(not re.match(r'^#{2,}\s', line), '存在无法识别的结构标题')
            require('<!--' not in line and '-->' not in line, '存在无法识别的注释')
            if point is not None:
                point['lines'].append(line)
            elif event is not None:
                require(not line.strip(), '事件标题与首个要点之间只能有空行和 event_id 注释')
            # 首个事件前的日记标题及来源说明不属于要点正文。
    require(bool(events), '未找到事件要点')
    ids = []
    for event in events:
        require(event['event_id'] is not None and bool(event['points']), '事件缺少 ID 或要点')
        ids.append(event['event_id'])
        for index, p in enumerate(event['points'], 1):
            p['detail'] = '\n'.join(p.pop('lines')).strip()
            require(p['no'] == index and bool(p['summary'].strip()) and bool(p['detail']),
                    '要点必须从 1 连续编号，主旨和详情不能为空')
    require(len(ids) == len(set(ids)), '事件 ID 重复')
    return events


def read_source(path):
    source = json.loads(read_text(path))
    require(source.get('origin') == 'database' and source.get('schema_version') == 1,
            '只能使用本 Skill 导出的数据库来源快照')
    require(source.get('source_sha256') == digest({k: v for k, v in source.items() if k != 'source_sha256'}),
            '来源快照指纹不匹配')
    UUID(source['user_id']); UUID(source['diary_id'])
    return source


def check_draft(events, source):
    require([e['event_id'] for e in events] == [e['event_id'] for e in source['events']],
            '稿件事件 ID 或顺序与来源不一致，不能漏项或猜配重名事件')
    for event, original in zip(events, source['events']):
        require(event['title'] == original['title'], '稿件事件标题与来源不一致')


def readonly(db):
    from sqlalchemy import text
    name = db.get_bind().dialect.name
    if name == 'postgresql':
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    elif name == 'sqlite':
        db.execute(text('PRAGMA query_only = ON'))
    else:
        raise StorageError('不支持该数据库的只读预检')


def freeze_embedding_config():
    from config import settings
    from services.model_runtime import resolve_model_setting
    from services.graph_runtime import freeze_model
    model = freeze_model(resolve_model_setting('graph_embedding'), thinking=False)
    require(model['model_type'] == 'embedding', '配置的用途必须是向量模型')
    return {'models': {'embedding': model}, 'prompts': {}, 'embedding_model': digest(model),
            'embedding_max_chars': settings.GRAPH_EMBEDDING_MAX_CHARS,
            'context_limit': settings.GRAPH_CONTEXT_TOKEN_LIMIT}


def schema_ready(db):
    from sqlalchemy import inspect
    if db.get_bind().dialect.name == 'sqlite':
        return True  # 仅供隔离测试。
    constraints = inspect(db.connection()).get_check_constraints('graph_runs')
    return any(c['name'] == 'ck_graph_run_status' and 'POINTS_READY' in c['sqltext'] for c in constraints)


def ensure_schema(db, *, write=False):
    from sqlalchemy import inspect, text
    if schema_ready(db):
        return {'points_ready_supported': True, 'changed': False}
    if not write:
        return {'points_ready_supported': False, 'changed': False}
    require(db.get_bind().dialect.name == 'postgresql', '状态扩展仅用于 PostgreSQL')
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('diary:event_points:status'))"))
    # 等待锁后重新检查，重复执行不重建约束。
    if schema_ready(db):
        return {'points_ready_supported': True, 'changed': False}
    constraints = inspect(db.connection()).get_check_constraints('graph_runs')
    current = next((c['sqltext'] for c in constraints if c['name'] == 'ck_graph_run_status'), None)
    require(current is not None and set(re.findall(r"'([^']+)'", current)) ==
            {'QUEUED', 'RUNNING', 'FAILED', 'PUBLISHED', 'OBSOLETE', 'SKIPPED'},
            '现有状态约束与基线不一致，停止变更')
    migration = PROJECT_ROOT / 'backend/migrations/051_event_points_ready.sql'
    require(migration.is_file(), '状态扩展 SQL 文件缺失')
    statements = re.sub(r'--[^\n]*', '', migration.read_text()).split(';')
    for statement in statements:
        if statement.strip(): db.execute(text(statement))
    require(schema_ready(db), '状态扩展后检查未通过')
    return {'points_ready_supported': True, 'changed': True}


def target(db, source, *, lock=False, own_task=None):
    from models.user import User
    from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus, OrganizeTask
    from models.graph import GraphRun, GraphTask
    from export_events import json_array
    user_query = db.query(User).filter(User.id == UUID(source['user_id']), User.username == source['username'])
    user = (user_query.with_for_update() if lock else user_query).one_or_none()
    require(user is not None, '来源用户身份不匹配')
    query = db.query(Diary).filter(Diary.id == UUID(source['diary_id']), Diary.user_id == user.id,
                                   Diary.deleted_at.is_(None))
    diary = (query.with_for_update() if lock else query).one_or_none()
    require(diary is not None, '日记不存在、已删除或不属于该用户')
    require(diary.status in (DiaryStatus.organized, DiaryStatus.analyzed), '仅已整理或已分析日记可保存要点')
    require(not diary.is_dirty and diary.organized is not None, '来源没有有效整理结果')
    org = diary.organized
    event_query = db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == org.id)
    if lock:
        db.query(DiaryOrganized).filter(DiaryOrganized.id == org.id).with_for_update().one()
        rows = event_query.order_by(DiaryEvent.id).with_for_update().all()
    else:
        rows = event_query.order_by(DiaryEvent.sort_order, DiaryEvent.id).all()
    require(org.source_content_revision == diary.content_revision, '整理来源已过期')
    require(str(diary.diary_date) == source['diary_date'] and str(org.id) == source['organized_id']
            and diary.content_revision == source['content_revision']
            and org.structured_revision == source['structured_revision'], '数据库来源版本已变化，须重新导出')
    events = [{'event_id': str(e.id), 'title': e.event_title or '未命名事件',
               'body': json_array(e.body, '正文', required=True), 'feeling': json_array(e.feeling, '感受'),
               'reflection': json_array(e.reflection, '反思'), 'source_order': e.sort_order}
              for e in sorted(rows, key=lambda e: (e.sort_order, str(e.id)))]
    records = {e['event_id']: e for e in events}
    for original in source['events']:
        current = records.get(original['event_id'])
        require(current is not None and all(current[k] == original[k] for k in
                ('title', 'body', 'feeling', 'reflection', 'source_order')),
                '数据库事件内容已变化，须重新导出')
    require(bool(events) and [e['event_id'] for e in source['events']]
            == [e['event_id'] for e in events], '必须按顺序覆盖本篇全部事件')
    active = db.query(GraphTask.id).filter(GraphTask.user_id == user.id, GraphTask.status.in_(('QUEUED', 'RUNNING')))
    if own_task is not None:
        active = active.filter(GraphTask.id != own_task)
    require(not active.first(), '该用户已有活动任务')
    require(not db.query(OrganizeTask.id).filter(OrganizeTask.diary_id == diary.id,
                OrganizeTask.status == 'running').first(), '该日记已有运行中的整理或分析任务')
    ready = db.query(GraphRun.id).filter(GraphRun.diary_id == diary.id,
                                       GraphRun.status.in_(('POINTS_READY', 'PUBLISHED')))
    require(not ready.first(), '该日记已有有效要点，本脚本不覆盖已有结果')
    fresh = {'scope': 'EVENT_POINTS', 'user_id': str(user.id), 'diary_id': str(diary.id),
             'diary_date': str(diary.diary_date), 'organized_id': str(org.id),
             'content_revision': diary.content_revision, 'structured_revision': org.structured_revision,
             'events': events}
    return diary, fresh, digest(fresh)


def prepare(db, markdown, source_path):
    require(schema_ready(db), '需先应用 051_event_points_ready.sql，以支持要点就绪状态')
    markdown, source_path = Path(markdown).resolve(), Path(source_path).resolve()
    source = read_source(source_path)
    events = parse_markdown(read_text(markdown))
    check_draft(events, source)
    _, _, source_hash = target(db, source)
    config = freeze_embedding_config()
    require(all(len(p['detail']) <= config['embedding_max_chars'] for e in events for p in e['points']),
            '详情超过当前向量输入上限，不得截断')
    packet = {'schema_version': 3, 'kind': 'diary-event-points-only',
        'source_file': {'path': str(source_path), 'sha256': file_digest(source_path)},
        'markdown': {'path': str(markdown), 'sha256': file_digest(markdown)},
        'user_id': source['user_id'], 'diary_id': source['diary_id'], 'diary_date': source['diary_date'],
        'points_source_sha256': source_hash, 'config_sha256': digest(config),
        'skill_sha256': file_digest(SKILL_ROOT / 'SKILL.md'),
        'review_mode': 'SKILL_USER_CONFIRMED', 'events': events}
    packet['confirmation_sha256'] = digest(packet)
    return packet


def verify_packet(packet, confirmed=None, *, files=True):
    # 旧包仍可查询历史任务；写入和恢复须重新准备全事件范围的新包。
    require(packet.get('schema_version') in ((2, 3) if not files else (3,))
            and packet.get('kind') == 'diary-event-points-only',
            '旧入库包不能用于保存，请使用当前脚本重新预检')
    require(packet.get('confirmation_sha256') == digest({k: v for k, v in packet.items() if k != 'confirmation_sha256'}),
            '入库包已修改，须重新预检')
    if confirmed is not None:
        require(confirmed == packet['confirmation_sha256'], '确认指纹不匹配')
    require(packet['review_mode'] == 'SKILL_USER_CONFIRMED', '不支持该审核来源')
    UUID(packet['user_id']); UUID(packet['diary_id'])
    if not files:
        return None
    for key in ('source_file', 'markdown'):
        require(file_digest(packet[key]['path']) == packet[key]['sha256'], '来源或稿件文件已变化，须重新预检')
    source = read_source(packet['source_file']['path'])
    require(all(packet[k] == source[k] for k in ('user_id', 'diary_id', 'diary_date')), '入库包目标与来源不一致')
    events = parse_markdown(read_text(packet['markdown']['path']))
    check_draft(events, source)
    require(packet['events'] == events, '入库包文字或事件范围与稿件不一致')
    require(bool(packet['events']), '没有可保存的要点')
    return source


def existing_task(db, packet):
    from models.graph import GraphTask, GraphRun
    tasks = db.query(GraphTask).join(GraphRun, GraphRun.task_id == GraphTask.id).filter(
        GraphTask.user_id == UUID(packet['user_id']), GraphRun.diary_id == UUID(packet['diary_id'])).all()
    return next((t for t in tasks if (t.config_snapshot or {}).get('skill_import', {}).get('confirmation_sha256')
                 == packet['confirmation_sha256']), None)


def submit(db, packet, confirmed):
    from models.user import User
    from models.graph import GraphTask, GraphRun
    from services.task_environment import TASK_ENVIRONMENT
    require(bool(confirmed), '提交必须提供用户确认指纹')
    source = verify_packet(packet, confirmed)
    require(schema_ready(db), '数据库尚不支持要点就绪状态')
    user = db.query(User).filter(User.id == UUID(packet['user_id']), User.username == source['username']).with_for_update().first()
    require(user is not None, '来源用户身份不匹配')
    old = existing_task(db, packet)
    if old is not None:
        return old, True
    require(file_digest(SKILL_ROOT / 'SKILL.md') == packet['skill_sha256'], 'Skill 已变化，请重新预检')
    diary, fresh, source_hash = target(db, source, lock=True)
    require(source_hash == packet['points_source_sha256'], '要点来源已变化，请重新预检')
    config = freeze_embedding_config()
    require(digest(config) == packet['config_sha256'], '向量配置已变化，请重新预检')
    provenance = {'confirmation_sha256': packet['confirmation_sha256'], 'review_mode': packet['review_mode'],
                  'markdown_sha256': packet['markdown']['sha256'], 'source_sha256': source['source_sha256'],
                  'skill_sha256': packet['skill_sha256']}
    config.update(scope='EVENT_POINTS', skill_import=provenance)
    # 此入口由脚本同步推进，不进入应用的后台队列。
    task = GraphTask(id=uuid4(), user_id=diary.user_id, environment='points:' + TASK_ENVIRONMENT,
        entry_type='HISTORY', date_from=diary.diary_date, date_to=diary.diary_date,
        config_snapshot=config, status='QUEUED')
    db.add(task); db.flush()
    run_id = uuid4()
    work = {}
    for event in packet['events']:
        work[event['event_id']] = {'review_origin': packet['review_mode'],
            'points': [{**p, 'id': str(uuid4()), 'run_id': str(run_id), 'event_id': event['event_id']}
                       for p in event['points']]}
    run = GraphRun(id=run_id, task_id=task.id, user_id=diary.user_id, diary_id=diary.id,
        diary_date=diary.diary_date, source_organized_id=diary.organized.id,
        source_snapshot=fresh, source_sha256=source_hash, status='QUEUED',
        checkpoint={'point_work': work, 'skill_import': provenance})
    db.add(run); db.flush()
    task.current_run_id = run.id
    db.flush()
    return task, False


def validate_vector(vector):
    import math
    require(isinstance(vector, list) and len(vector) == 1024, '向量维度必须为1024')
    require(all(type(x) in (int, float) and math.isfinite(x) for x in vector), '向量包含非法数值')
    require(sum(x*x for x in vector) > 0, '向量模长为零')


async def embed_points(ctx, state):
    """复用当前用途配置、完整 detail 请求和审计调用，只执行向量阶段。"""
    vectors = dict(state.get('vectors', {}))
    from database import SessionLocal
    from models.graph import GraphTask, GraphRun
    # 复用同日同用户、同向量模型、完全相同详情的既有合法向量。
    with SessionLocal() as db:
        task = ctx.owned(db)
        run = db.get(GraphRun, ctx.run_id)
        previous = db.query(GraphRun, GraphTask).join(GraphTask, GraphTask.id == GraphRun.task_id).filter(
            GraphRun.user_id == task.user_id, GraphRun.diary_id == run.diary_id,
            GraphRun.id != run.id).order_by(GraphRun.created_at.desc()).all()
        cache = {}
        for old, owner in previous:
            if owner.config_snapshot.get('embedding_model') != ctx.config['embedding_model']:
                continue
            cp = old.checkpoint or {}
            for work in cp.get('point_work', {}).values():
                for p in work.get('points', []):
                    v = cp.get('vectors', {}).get(p['id'])
                    try: validate_vector(v)
                    except StorageError: continue
                    cache.setdefault(p['detail'], (v, str(old.id), p['id']))
    reused = dict(state.get('vector_reuse', {}))
    for work in state['point_work'].values():
        for point in work['points']:
            pid = point['id']
            if pid in vectors:
                validate_vector(vectors[pid]); continue
            require(len(point['detail']) <= ctx.config['embedding_max_chars'], '详情超过向量输入预算')
            if point['detail'] in cache:
                vector, old_run, old_point = cache[point['detail']]
                vectors[pid] = vector
                reused[pid] = {'run_id': old_run, 'point_id': old_point}
            else:
                def check(data):
                    require(isinstance(data, dict) and isinstance(data.get('data'), list)
                            and len(data['data']) == 1 and data['data'][0].get('index') == 0,
                            '向量响应结构不正确')
                    validate_vector(data['data'][0].get('embedding'))
                result = await ctx.call('embedding', pid, [point['detail']], check, embedding=True)
                check(result)
                vectors[pid] = result['data'][0]['embedding']
            state = ctx.save('EMBED_POINTS', vectors=vectors, vector_reuse=reused)
    return state


def store_ready(SessionLocal, ctx, packet):
    from models.user import User
    from models.graph import GraphTask, GraphRun, GraphRunEvent, GraphEventPoint, utcnow
    source = verify_packet(packet, packet['confirmation_sha256'])
    with SessionLocal() as db:
        # 与提交相同的用户锁顺序，提交前重查来源。
        db.query(User).filter(User.id == UUID(packet['user_id'])).with_for_update().one()
        task = ctx.owned(db, lock=True)
        run = db.query(GraphRun).filter(GraphRun.id == ctx.run_id, GraphRun.task_id == task.id).with_for_update().one()
        _, fresh, source_hash = target(db, source, lock=True, own_task=task.id)
        require(source_hash == run.source_sha256 == packet['points_source_sha256'], '来源已变化，停止保存')
        state = deepcopy(run.checkpoint)
        expected = {e['event_id']: e for e in packet['events']}
        require(set(state['point_work']) == set(expected), '候选事件覆盖不完整')
        for event in fresh['events']:
            eid = event['event_id']
            if eid not in expected: continue
            points = state['point_work'][eid]['points']
            require([{k: p[k] for k in ('no', 'summary', 'detail')} for p in points] == expected[eid]['points'],
                    '数据库候选与确认稿不一致')
            db.add(GraphRunEvent(run_id=run.id, event_id=UUID(eid), user_id=task.user_id,
                                 source_order=event['source_order']))
            db.flush()
            for point in points:
                vector = state.get('vectors', {}).get(point['id'])
                validate_vector(vector)
                db.add(GraphEventPoint(id=UUID(point['id']), run_id=run.id, event_id=UUID(eid),
                    user_id=task.user_id, no=point['no'], summary=point['summary'], detail=point['detail'],
                    embedding=vector, embedding_model=ctx.config['embedding_model']))
        db.flush()
        require(db.query(GraphEventPoint).filter(GraphEventPoint.run_id == run.id).count()
                == sum(len(e['points']) for e in expected.values()), '保存后要点数量不一致')
        run.status, run.current_step, run.updated_at = 'POINTS_READY', None, utcnow()
        run.checkpoint = {**state, 'points_stored': True}
        task.status, task.completed_at, task.updated_at = 'SUCCEEDED', utcnow(), utcnow()
        db.commit()


def status(db, task):
    from models.graph import GraphRun, GraphEventPoint
    run = db.query(GraphRun).filter(GraphRun.task_id == task.id).one()
    state = run.checkpoint or {}
    return {'task_id': str(task.id), 'run_id': str(run.id), 'task_status': task.status,
        'run_status': run.status, 'current_step': run.current_step, 'error_code': task.error_code,
        'events': len(state.get('point_work', {})),
        'candidate_points': sum(len(w.get('points', [])) for w in state.get('point_work', {}).values()),
        'vectors': len(state.get('vectors', {})), 'reused_vectors': len(state.get('vector_reuse', {})),
        'stored_points': db.query(GraphEventPoint).filter(GraphEventPoint.run_id == run.id).count(),
        'stored': run.status == 'POINTS_READY'}


async def execute(SessionLocal, task_id, packet):
    from contextlib import suppress
    from models.graph import GraphTask, GraphRun, GraphModelCall, utcnow
    from services.graph_runtime import GraphContext, GraphError
    from config import settings
    with SessionLocal() as db:
        task = db.query(GraphTask).filter(GraphTask.id == task_id).with_for_update().one()
        require(task.config_snapshot.get('scope') == 'EVENT_POINTS', '此任务不属于当前入口')
        if task.status == 'SUCCEEDED': return
        now = utcnow()
        lease = task.lease_until
        if lease is not None and lease.tzinfo is None: lease = lease.replace(tzinfo=timezone.utc)
        if task.status == 'RUNNING' and lease and lease > now: return
        require(task.status in ('QUEUED', 'RUNNING', 'FAILED'), '任务不可执行')
        if task.status != 'QUEUED': task.retry_count += 1
        task.status, task.run_token = 'RUNNING', uuid4()
        task.lease_until = now + timedelta(seconds=settings.GRAPH_LEASE_SECONDS)
        task.started_at, task.updated_at = task.started_at or now, now
        task.error_code = task.error_message = None
        run = db.query(GraphRun).filter(GraphRun.task_id == task.id).with_for_update().one()
        run.status, run.error_code, run.error_message = 'RUNNING', None, None
        ctx = GraphContext(task.id, run.id, task.run_token, deepcopy(task.config_snapshot))
        db.query(GraphModelCall).filter(GraphModelCall.task_id == task.id,
            GraphModelCall.status == 'STARTED').update({'status': 'UNKNOWN', 'completed_at': now})
        db.commit()
    async def heartbeat():
        while True:
            await asyncio.sleep(settings.GRAPH_HEARTBEAT_SECONDS)
            with SessionLocal() as db:
                task = ctx.owned(db, lock=True)
                task.lease_until = utcnow() + timedelta(seconds=settings.GRAPH_LEASE_SECONDS)
                db.commit()
    heart = asyncio.create_task(heartbeat())
    try:
        with SessionLocal() as db:
            state = deepcopy(db.get(GraphRun, ctx.run_id).checkpoint)
        await embed_points(ctx, state)
        store_ready(SessionLocal, ctx, packet)
    except Exception as error:
        if isinstance(error, GraphError) and error.code == 'OWNERSHIP_LOST': raise
        with SessionLocal() as db:
            task = ctx.owned(db, lock=True)
            run = db.get(GraphRun, ctx.run_id)
            code = error.code if isinstance(error, GraphError) else 'POINTS_SAVE_FAILED'
            message = str(error) if isinstance(error, (GraphError, StorageError)) else type(error).__name__
            task.status, task.error_code, task.error_message = 'FAILED', code, message
            run.status, run.error_code, run.error_message = 'FAILED', code, message
            db.commit()
        raise
    finally:
        heart.cancel()
        with suppress(asyncio.CancelledError): await heart


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-dir', type=Path, default=PROJECT_ROOT / 'backend')
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--source', type=Path, required=True)
    prep.add_argument('--markdown', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    save = commands.add_parser('save')
    save.add_argument('packet', type=Path)
    save.add_argument('--write', action='store_true')
    save.add_argument('--confirmed-sha256')
    stat = commands.add_parser('status')
    stat.add_argument('packet', type=Path)
    commands.add_parser('embedding-config')
    schema = commands.add_parser('schema')
    schema.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    from skill_api import maybe_remote
    maybe_remote("points", args)
    for key in ('source', 'markdown', 'output', 'packet'):
        if hasattr(args, key): setattr(args, key, getattr(args, key).resolve())
    try:
        require(args.command == 'schema' or not getattr(args, 'write', False)
                or bool(args.confirmed_sha256), '写入必须提供用户确认指纹')
        if args.command == 'prepare': require(not args.output.exists(), '入库包已存在，请使用新文件名')
        SessionLocal = open_backend(args.backend_dir)
        with SessionLocal() as db:
            if args.command == 'embedding-config':
                config = freeze_embedding_config()
                result = {'model': config['models']['embedding'], 'dimension': 1024, 'input': '全部要点详情'}
            elif args.command == 'schema':
                if not args.write: readonly(db)
                result = ensure_schema(db, write=args.write)
                if args.write: db.commit()
                else: db.rollback()
            elif args.command == 'prepare':
                readonly(db)
                packet = prepare(db, args.markdown, args.source)
                db.rollback()
                with args.output.open('x', encoding='utf-8') as out:
                    out.write(json.dumps(packet, ensure_ascii=False, indent=2) + '\n')
                result = {'phase': 'prepared', 'write': False, 'packet': str(args.output),
                    'events': len(packet['events']), 'points': sum(len(e['points']) for e in packet['events']),
                    'confirmation_sha256': packet['confirmation_sha256']}
            else:
                packet = json.loads(args.packet.read_text(encoding='utf-8'))
                verify_packet(packet, files=args.command != 'status')
                if args.command == 'status':
                    readonly(db)
                    task = existing_task(db, packet)
                    result = status(db, task) if task else {'phase': 'not_submitted', 'stored': False}
                    db.rollback()
                elif not args.write:
                    readonly(db)
                    old = existing_task(db, packet)
                    if old: result = {'phase': 'existing', 'write': False, **status(db, old)}
                    else:
                        current = prepare(db, Path(packet['markdown']['path']), Path(packet['source_file']['path']))
                        require(current == packet, '预检状态已变化，请重新生成入库包')
                        result = {'phase': 'validated', 'write': False, 'stored': False}
                    db.rollback()
                else:
                    task, reused = submit(db, packet, args.confirmed_sha256)
                    task_id = task.id
                    db.commit()
                    asyncio.run(execute(SessionLocal, task_id, packet))
                    db.expire_all()
                    from models.graph import GraphTask
                    result = {'phase': 'existing' if reused else 'saved', 'write': True,
                              **status(db, db.get(GraphTask, task_id))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StorageError, ExportError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
    except Exception as error:
        blocked = 'Operation not permitted' in str(error)
        reason = '运行环境拒绝网络访问，请按权限流程重试' if blocked else type(error).__name__
        print(json.dumps({'error': reason, 'message': '操作未完成；先查询状态再重试，未输出认证信息'}, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
