"""在独立进程复用 Skill 数据逻辑，隔离各阶段同名 Python 模块。"""
import asyncio
from contextlib import contextmanager
from datetime import date, datetime, timezone
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'skills/shared'))
from skill_files import uploaded_files

STAGES = {
    'workflow': ('diary-workflow', 'status'),
    'people': ('diary-organizer', 'export_people'),
    'organize': ('diary-organizer', 'store_diary'),
    'organize-review': ('diary-organizer', 'review_diary'),
    'points-source': ('diary-event-points', 'export_events'),
    'points': ('diary-event-points', 'store_points'),
    'supplement': ('diary-event-points', 'supplement_points'),
    'relations': ('diary-event-relations', 'workflow'),
    'analyze': ('diary-analyzer', 'store_analysis'),
}
ACTIONS = {
    'workflow': {'status'}, 'people': {'export'},
    'organize': {'find', 'export', 'prepare', 'save'},
    'organize-review': {'export', 'prepare', 'save'},
    'points-source': {'find', 'export'},
    'points': {'prepare', 'save', 'status', 'schema', 'embedding-config'},
    'supplement': {'prepare', 'save', 'status'},
    'relations': {'find', 'prepare', 'verify', 'history-context', 'preflight', 'save', 'storage-status', 'schema'},
    'analyze': {'find', 'export', 'prepare', 'save'},
}


def check_identity(value, user_id, username):
    """所有上传包、历史来源及参数均限于 Token 绑定用户。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'user_id' and str(item) != user_id:
                raise ValueError('数据不属于 Token 绑定用户')
            if key == 'username' and item != username:
                raise ValueError('用户名与 Token 绑定用户不一致')
            check_identity(item, user_id, username)
    elif isinstance(value, list):
        for item in value:
            check_identity(item, user_id, username)


@contextmanager
def session(writing=False):
    from database import SessionLocal
    with SessionLocal() as db, db.begin():
        if not writing and db.bind.dialect.name == 'postgresql':
            from sqlalchemy import text
            db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        yield db


def verified_snapshot(m, snapshot):
    if snapshot['package_sha256'] != m.digest({k: v for k, v in snapshot.items() if k != 'package_sha256'}):
        raise ValueError('来源包指纹不匹配')


def workflow(m, p):
    from db_source import connection, list_diaries
    with connection(ROOT / 'backend') as conn:
        found = list_diaries(conn, p['username'], p.get('date'), p.get('diary_id'))
        result = {'username': p['username'], 'user_id': found['user_id'],
                  'match_count': len(found['diaries']), 'read_only': True}
        if len(found['diaries']) == 1:
            result.update(m.inspect_diary(conn, found['user_id'], found['diaries'][0]))
        else:
            result.update(selection_required=True, candidates=[
                {'diary_id': str(d['id']), 'diary_date': str(d['diary_date']), 'status': d['status']}
                for d in found['diaries']])
        return result


def document(m, action, p, analysis=False):
    writing = action == 'save' and p.get('write', False)
    if writing and not p.get('confirmed_sha256'):
        raise ValueError('保存必须携带已确认稿件的指纹')
    packet = p.get('packet')
    exported = p.get('exported')
    if action == 'prepare':
        if analysis:
            packet = m.make_packet(Path(p['markdown']), Path(p['source']))
            exported = packet['exported']
        else:
            from skill_files import read_text
            exported = json.loads(read_text(p['source']))
            if exported.get('schema_version') != 1 or m.digest(exported['original_text']) != exported['source']['original_sha256']:
                raise ValueError('原文导出文件格式或指纹错误')
            packet = m.make_packet(Path(p['markdown']), Path(p['clarifications']), exported['source'])
    if action == 'save':
        m.verify_packet(packet, p.get('confirmed_sha256'))
        exported = packet['exported'] if analysis else {'source': packet['source']}
    with session(writing) as db:
        if action == 'find':
            return m.find_diaries(db, p['username'], date.fromisoformat(p['date']))
        source = exported['source'] if exported else p
        loader = m.load_target if analysis or action != 'export' else m.load_source
        diary = loader(db, source['diary_id'], source['user_id'], lock=writing)
        if action == 'export':
            if analysis:
                return {'file': m.build_export(db, diary)}
            return {'file': {'schema_version': 1, 'source': m.snapshot(diary),
                             'original_text': diary.original_text, 'capabilities': m.replacement_capability(db, diary)}}
        if analysis:
            m.assert_current(db, diary, exported)
            result = m.verify_packet(packet, p.get('confirmed_sha256'))
            m.validate_backend_result(result)
            m.assert_fresh_dates(result)
        else:
            if m.snapshot(diary) != exported['source']:
                raise ValueError('数据库来源已变化，请重新导出、预检和确认')
            result = packet['result']
        if action == 'prepare':
            return {'packet': packet, 'validated': True, 'stored': False,
                    'confirmation_sha256': packet['confirmation_sha256']}
        if writing:
            receipt = {'status': '已提交', **m.persist_result(db, diary, result)}
            if not analysis:
                from review_diary import export_current
                db.expire(diary, ['organized'])
                receipt['review_source'] = export_current(db, diary)
            return receipt
        return {'validated': True, 'stored': False, 'confirmation_sha256': packet['confirmation_sha256']}


def points(m, action, p):
    from database import SessionLocal
    if action == 'embedding-config':
        config = m.freeze_embedding_config()
        return {'model': config['models']['embedding'], 'dimension': 1024, 'input': '全部要点详情'}
    if action == 'schema':
        with session() as db:
            return m.ensure_schema(db)
    if action == 'prepare':
        with session() as db:
            packet = m.prepare(db, Path(p['markdown']), Path(p['source']),
                review_mode='SKILL_WORKFLOW_AUTHORIZED' if p.get('workflow_authorized') else 'SKILL_USER_CONFIRMED')
        return {'packet': packet, 'confirmation_sha256': packet['confirmation_sha256'],
                'events': len(packet['events']), 'points': sum(len(e['points']) for e in packet['events']), 'stored': False}
    packet = p['packet']
    m.verify_packet(packet, files=action != 'status')
    with SessionLocal() as db:
        if action == 'status' or not p.get('write'):
            m.readonly(db)
            task = m.existing_task(db, packet)
            if task:
                return m.status(db, task)
            if action == 'status':
                return {'phase': 'not_submitted', 'stored': False}
            current = m.prepare(db, Path(packet['markdown']['path']), Path(packet['source_file']['path']), review_mode=packet['review_mode'])
            m.require(current == packet, '预检状态已变化，请重新生成入库包')
            return {'validated': True, 'stored': False}
        task, reused = m.submit(db, packet, p.get('confirmed_sha256'))
        task_id = task.id
        db.commit()
        asyncio.run(m.execute(SessionLocal, task_id, packet))
        db.expire_all()
        from models.graph import GraphTask
        return {'phase': 'existing' if reused else 'saved', **m.status(db, db.get(GraphTask, task_id))}


def supplement(m, action, p):
    from database import SessionLocal
    if action == 'prepare':
        with m.reading(SessionLocal) as db:
            packet = m.prepare(db, p['inputs'])
        return {'packet': packet, 'confirmation_sha256': packet['confirmation_sha256'], 'stored': False}
    packet = p['packet']
    # 原本地状态脚本按运行 ID 读取；HTTP 入口额外限制每个运行的归属。
    from models.graph import GraphRun
    from uuid import UUID
    with SessionLocal() as db:
        for item in packet['items']:
            run = db.query(GraphRun).filter(GraphRun.id == UUID(item['run_id']),
                GraphRun.user_id == UUID(p['_bound_user_id'])).one_or_none()
            if run is None: raise ValueError('补充运行不属于 Token 绑定用户')
    if action == 'status':
        return m.status(SessionLocal, packet)
    m.verify(packet, p.get('confirmed_sha256') if p.get('write') else None)
    existing = m.status(SessionLocal, packet)
    if existing['stored']:
        return existing
    if p.get('write'):
        m.require(p.get('confirmed_sha256') == packet['confirmation_sha256'], '保存需匹配确认指纹')
        return m.publish(SessionLocal, packet, m.embed(SessionLocal, packet), p['confirmed_sha256'])
    with m.reading(SessionLocal) as db:
        for item in packet['items']:
            m.require(m.digest(m.capture(db, item['source'], item['run_id'])[0]) == item['before_sha256'], '原运行已变化')
    return {'validated': True, 'stored': False}


def relations(m, action, p):
    import db_source as source
    if action in {'find', 'prepare'}:
        args = SimpleNamespace(backend_dir=ROOT / 'backend', username=p['username'],
                               date=p.get('date'), diary_id=p.get('diary_id'), run_id=p.get('run_id'))
        return source.find(args) if action == 'find' else {'snapshot': source.prepare(args)}
    if action in {'verify', 'history-context'}:
        s = p['snapshot']
        verified_snapshot(m, s)
        with source.connection(ROOT / 'backend') as conn:
            if action == 'history-context':
                from redundancy import history_context
                return {'history': history_context(conn, s)}
            if s['history_mode'] == 'database':
                _, _, inventory = source.database_history(conn, s['user_id'], s['diary_date'])
                m.require(inventory == s['history_inventory'], '历史范围、正式要点或向量已变化，请新建运行')
            for rid in sorted({e['run_id'] for e in s['events'].values()}):
                events, _ = source.load_run(conn, s['user_id'], rid,
                    published=rid != s['current_run_id'] and s['history_mode'] == 'published')
                actual = {e['id']: source.run_identity(e) for e in events}
                for frozen in s['events'].values():
                    if frozen['run_id'] == rid:
                        m.require(actual.get(frozen['id']) == source.run_identity(frozen), '来源已变化')
        return {'verified_against_database': True, 'package_sha256': s['package_sha256'],
                'verified_at': datetime.now(timezone.utc).isoformat(), 'stored_in_database': False}
    import storage
    if action == 'schema':
        with source.connection(ROOT / 'backend') as conn:
            return storage.schema(conn)
    packet = storage.validate_packet(p['packet'], current_skill=action != 'storage-status')
    options = {k: p.get(k, False) for k in ('replace_published', 'accept_published_revisions')}
    if action == 'save' and p.get('write'):
        with source.backend_engine(ROOT / 'backend').begin() as conn:
            return storage.publish(conn, packet, p['username'], p.get('confirmed_sha256'), **options)
    with source.connection(ROOT / 'backend') as conn:
        if action == 'storage-status':
            storage.owned(conn, packet, p['username'])
            status, _, archive = storage.archive_for(conn, packet)
            matched = bool(archive and archive.get('storage_sha256') == packet['storage_sha256'])
            return {'stored': status == 'PUBLISHED' and matched, 'archived': matched,
                    'run_status': status, 'storage_sha256': packet['storage_sha256']}
        state = storage.inspect_target(conn, packet, p['username'], **options)
        return {**state, 'ready_to_publish': state['skill_source_supported']}


def execute(request):
    stage, action, p = request['stage'], request['action'], request['params']
    if action not in ACTIONS.get(stage, set()):
        raise ValueError('不支持的 Skill 操作')
    if action == 'schema' and p.get('write'):
        raise ValueError('接口只检查迁移状态，请在服务端执行固定迁移')
    from config import settings
    from database import SessionLocal
    from models.user import User
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == settings.SKILL_API_USERNAME).one_or_none()
        if user is None:
            raise ValueError('Token 绑定用户不存在')
        user_id, username = str(user.id), user.username
    check_identity(p, user_id, username)
    # 文件内容亦含导出来源身份；业务校验会再次核对数据库归属。
    for content in request.get('files', {}).values():
        try:
            parsed = json.loads(content)
        except ValueError:
            continue
        check_identity(parsed, user_id, username)
    p.setdefault('username', username)
    p['_bound_user_id'] = user_id
    name, module = STAGES[stage]
    sys.path.insert(0, str(ROOT / 'skills' / name / 'scripts'))
    m = importlib.import_module(module)
    with uploaded_files(request.get('files', {})):
        if stage == 'workflow': return workflow(m, p)
        if stage == 'organize-review':
            with session(action == 'save' and p.get('write', False)) as db:
                return m.execute(db, action, p)
        if stage == 'people':
            with session() as db: return {'file': m.export_people(db, username)}
        if stage in {'organize', 'analyze'}: return document(m, action, p, analysis=stage == 'analyze')
        if stage == 'points-source':
            with m.read_connection(m.load_engine(ROOT / 'backend')) as conn:
                options = {'diary_date': date.fromisoformat(p['date']) if p.get('date') else None,
                           'diary_id': p.get('diary_id')}
                if action == 'find': return m.list_diaries(conn, username, **options)
                return {'source': m.export_source(conn, username, **options, event_ids=p.get('event_id', []))}
        if stage == 'points': return points(m, action, p)
        if stage == 'supplement': return supplement(m, action, p)
        if stage == 'relations': return relations(m, action, p)


if __name__ == '__main__':
    # stdout 仅返回结构化回执，驱动和业务异常不回显参数、SQL 或凭据。
    from contextlib import redirect_stdout
    try:
        request = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result = execute(request)
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, default=str, allow_nan=False))
    except Exception as error:
        safe = (type(error) is ValueError or type(error).__name__ in {'WorkflowError', 'StorageError', 'AnalysisInputError'}
                or (type(error).__name__ == 'GraphError' and getattr(error, 'code', None) in {'SOURCE_LOCKED', 'USER_TASK_ACTIVE'}))
        message = str(error) if safe else type(error).__name__
        print(json.dumps({'ok': False, 'error': '操作未完成：' + message + '；保存失败请先查询状态'}, ensure_ascii=False))
