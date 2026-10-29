#!/usr/bin/env python3
"""导出当前整理结果，对比修订并按事件 ID 保存联动修改；默认只读。"""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from skill_api import api_enabled, request, write_json
from store_diary import open_backend, load_source, digest, snapshot

ROOT = Path(__file__).resolve().parents[3]


def array(value):
    if value is None: return []
    if isinstance(value, str): value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError('内容须为非空字符串数组；无内容使用空数组')
    return value


def export_current(db, diary):
    from models.diary import DiaryStatus
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed) or not diary.organized:
        raise ValueError('日记尚无整理结果')
    if diary.is_dirty or diary.organized.source_content_revision != diary.content_revision:
        raise ValueError('整理来源已过期')
    org = diary.organized
    result = {'schema_version': 1, 'kind': 'diary-organized-review', 'source': snapshot(diary),
              'introduction': org.introduction or '', 'trivia': array(org.trivia), 'plans': array(org.plans),
              'events': [{'event_id': str(e.id), 'event_title': e.event_title or '',
                          'body': array(e.body), 'feeling': array(e.feeling), 'reflection': array(e.reflection)}
                         for e in sorted(org.events, key=lambda e: (e.sort_order, str(e.id)))]}
    result['source_sha256'] = digest(result)
    return result


def verify_source(value):
    if value.get('kind') != 'diary-organized-review' or value.get('schema_version') != 1:
        raise ValueError('复查来源格式错误')
    if value.get('source_sha256') != digest({k: v for k, v in value.items() if k != 'source_sha256'}):
        raise ValueError('复查来源指纹错误')
    return value


def compare(before, after):
    verify_source(before); verify_source(after)
    if any(before['source'][k] != after['source'][k] for k in ('user_id', 'diary_id', 'organized_id')):
        raise ValueError('比较对象不是同一篇日记的同一整理记录')
    a = {e['event_id']: e for e in before['events']}; b = {e['event_id']: e for e in after['events']}
    return {'added_event_ids': sorted(b.keys() - a.keys()), 'removed_event_ids': sorted(a.keys() - b.keys()),
            'changed_events': [{'event_id': key, 'fields': [f for f in ('event_title', 'body', 'feeling', 'reflection')
                                if a[key][f] != b[key][f]]} for key in sorted(a.keys() & b.keys()) if a[key] != b[key]],
            'plans_changed': before['plans'] != after['plans'],
            'diary_fields_changed': [f for f in ('introduction', 'trivia') if before[f] != after[f]]}


def validate_changes(changes, source):
    if not isinstance(changes, dict) or set(changes) - {'events', 'plans'}:
        raise ValueError('只支持 events 与 plans 定点修改')
    ids = {e['event_id'] for e in source['events']}; seen = set()
    events = changes.get('events', [])
    if not isinstance(events, list): raise ValueError('events 须为数组')
    for e in events:
        if not isinstance(e, dict) or not set(e) <= {'event_id', 'event_title', 'body', 'feeling', 'reflection'}:
            raise ValueError('事件包含不支持的修改字段')
        eid = e.get('event_id')
        if eid not in ids or eid in seen: raise ValueError('事件 ID 不存在或重复')
        seen.add(eid)
        if 'event_title' in e and (not isinstance(e['event_title'], str) or not e['event_title'].strip()):
            raise ValueError('事件标题不能为空')
        for f in ('body', 'feeling', 'reflection'):
            if f in e:
                if not isinstance(e[f], list): raise ValueError('修改值须为数组')
                array(e[f])
                if f == 'body' and not e[f]: raise ValueError('正文不能为空')
    if 'plans' in changes:
        if not isinstance(changes['plans'], list): raise ValueError('plans 须为数组')
        array(changes['plans'])


def prepare(source, changes):
    verify_source(source); validate_changes(changes, source)
    packet = {'schema_version': 1, 'kind': 'diary-organized-patch', 'exported': source, 'changes': changes}
    packet['confirmation_sha256'] = digest(packet)
    return packet


def execute(db, action, p):
    writing = action == 'save' and p.get('write', False)
    packet = p.get('packet')
    exported = p.get('exported') if action == 'prepare' else (packet['exported'] if packet else None)
    if exported: verify_source(exported)
    identity = exported['source'] if exported else p
    if writing:
        from models.user import User
        db.query(User).filter(User.id == UUID(identity['user_id'])).with_for_update().one()
    diary = load_source(db, identity['diary_id'], identity['user_id'], lock=writing)
    if writing:
        from models.diary import DiaryOrganized, DiaryEvent
        db.query(DiaryOrganized).filter(DiaryOrganized.diary_id == diary.id).with_for_update().one()
        db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == diary.organized.id).order_by(DiaryEvent.id).with_for_update().all()
        db.expire(diary, ['organized'])
    current = export_current(db, diary)
    if action == 'export': return {'file': current}
    from services.graph_tasks import assert_source_writable
    from models.diary import OrganizeTask
    assert_source_writable(db, diary.id, content=True)
    if db.query(OrganizeTask.id).filter(OrganizeTask.diary_id == diary.id, OrganizeTask.status == 'running').first():
        raise ValueError('存在活动整理或分析任务')
    if current != exported: raise ValueError('来源已变化，请重新导出并复查，不能覆盖人工修改')
    if action == 'prepare':
        return {'packet': prepare(exported, p['changes']), 'stored': False}
    rebuilt = prepare(exported, packet['changes'])
    if packet != rebuilt: raise ValueError('修订包已变化')
    if not writing: return {'validated': True, 'stored': False}
    if p.get('confirmed_sha256') != packet['confirmation_sha256']: raise ValueError('修订确认指纹不匹配')
    from schemas.diary import DiaryOrganizedUpdate
    from services.organized_update import apply_organized_update
    changes = dict(packet['changes'])
    if 'events' in changes:
        changes['events'] = [{('id' if k == 'event_id' else k): v for k, v in e.items()} for e in changes['events']]
    apply_organized_update(db, diary, DiaryOrganizedUpdate.model_validate(changes), diary.user_id)
    db.flush()
    return {'stored': True, 'diary_id': str(diary.id), 'source': export_current(db, diary),
            'confirmation_sha256': packet['confirmation_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-dir', type=Path, default=ROOT / 'backend')
    subs = parser.add_subparsers(dest='command', required=True)
    exp = subs.add_parser('export'); exp.add_argument('--diary-id', required=True); exp.add_argument('--user-id', required=True); exp.add_argument('--output', type=Path, required=True)
    diff = subs.add_parser('diff'); diff.add_argument('--before', type=Path, required=True); diff.add_argument('--after', type=Path, required=True)
    prep = subs.add_parser('prepare'); prep.add_argument('--source', type=Path, required=True); prep.add_argument('--changes', type=Path, required=True); prep.add_argument('--output', type=Path, required=True)
    save = subs.add_parser('save'); save.add_argument('packet', type=Path); save.add_argument('--write', action='store_true'); save.add_argument('--confirmed-sha256')
    args = parser.parse_args()
    try:
        if args.command == 'diff':
            print(json.dumps(compare(json.loads(args.before.read_text()), json.loads(args.after.read_text())), ensure_ascii=False, indent=2)); return
        if hasattr(args, 'output'):
            args.output = args.output.resolve()
            if args.output.exists(): raise ValueError('输出文件已存在')
        p = {'diary_id': args.diary_id, 'user_id': args.user_id} if args.command == 'export' else {}
        if args.command == 'prepare':
            p = {'exported': json.loads(args.source.read_text()), 'changes': json.loads(args.changes.read_text())}
        if args.command == 'save':
            p = {'packet': json.loads(args.packet.read_text()), 'write': args.write, 'confirmed_sha256': args.confirmed_sha256}
        if api_enabled(): result = request('organize-review', args.command, p)
        else:
            Session = open_backend(args.backend_dir)
            with Session() as db, db.begin():
                if not p.get('write') and db.bind.dialect.name == 'postgresql':
                    from sqlalchemy import text
                    db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                result = execute(db, args.command, p)
        if args.command in ('export', 'prepare'):
            write_json(args.output, result.pop('file' if args.command == 'export' else 'packet'))
            result['path'] = str(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        reason = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1, '复查操作停止：' + reason + '\n')


if __name__ == '__main__': main()
