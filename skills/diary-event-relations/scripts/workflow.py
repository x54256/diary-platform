#!/usr/bin/env python3
"""事件关系工作流：默认只读；正式发布通过独立入库包及显式 --write 完成。"""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import shutil
import sys
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[1]
VERSION = 1


class WorkflowError(Exception):
    """可以展示、不包含认证信息的业务错误。"""


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_json(path):
    def unique(items):
        result = {}
        for k, v in items:
            require(k not in result, 'JSON 含重复字段')
            result[k] = v
        return result
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(WorkflowError('JSON 含非有限数值')))
    except (ValueError, OSError):
        raise WorkflowError('无法读取合法 JSON 文件') from None


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def settings():
    value = read_json(SKILL_ROOT / 'settings.json')
    require(isinstance(value.get('workspace_root'), str) and value['workspace_root'].strip(), '工作根目录配置缺失')
    require(type(value.get('top_k')) is int and value['top_k'] > 0, 'top_k 必须为正整数')
    require(type(value.get('min_similarity')) in (int, float) and math.isfinite(value['min_similarity'])
            and -1 <= value['min_similarity'] <= 1, '相似度阈值不合法')
    keep = value.get('retain_all_min_similarity')
    require(keep is None or (type(keep) in (int, float) and math.isfinite(keep)
            and value['min_similarity'] <= keep <= 1), '全量保留阈值须不低于最低相似度且不大于1')
    for key in ('max_batch_chars', 'max_pairs_per_batch'):
        require(type(value.get(key)) is int and value[key] > 0, key + ' 必须为正整数')
    return value


def skill_fingerprint():
    files = [p for p in SKILL_ROOT.rglob('*') if p.is_file()
             and p.suffix in ('.md', '.py', '.json', '.yaml') and '__pycache__' not in p.parts]
    return digest({str(p.relative_to(SKILL_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(files)})


def validate_vector(v):
    require(isinstance(v, list) and len(v) == 1024, '向量缺失或维度不为 1024')
    require(all(type(x) in (int, float) and math.isfinite(x) for x in v), '向量含非法数值')
    norm = math.sqrt(sum(x*x for x in v))
    require(math.isfinite(norm) and norm > 0, '向量模长非法')
    return [x/norm for x in v]


def validate_events(events, user_id):
    require(events, '当前日记没有已保存要点的事件')
    require(len({e['id'] for e in events}) == len(events), '事件身份重复')
    point_ids = []
    for e in events:
        require(e['user_id'] == user_id, '来源含其他用户事件')
        UUID(e['id']); UUID(e['run_id']); UUID(e['diary_id'])
        date.fromisoformat(e['diary_date'])
        require(e['points'] and [p['no'] for p in e['points']] == list(range(1, len(e['points'])+1)), '正式要点缺失或编号不连续')
        for p in e['points']:
            UUID(p['id']); point_ids.append(p['id'])
            require(type(p['no']) is int, '要点序号必须为整数')
            require(all(isinstance(p[k], str) and p[k].strip() for k in ('summary', 'detail')), '要点内容为空')
    require(len(set(point_ids)) == len(point_ids), '要点身份重复')


def select_history_hits(hits, config):
    """输入按分数降序及事件ID升序排序；Top K与高分全保留取并集。"""
    eligible = [h for h in hits if h['score'] >= config['min_similarity']]
    keep = config.get('retain_all_min_similarity')
    return [h for rank, h in enumerate(eligible)
            if rank < config['top_k'] or (keep is not None and h['score'] >= keep)]


def prepare_data(current, history, vectors, config, *, history_mode='database', completed=(), history_inventory=()):
    """纯计算入口；数据库来源校验由 db_source 完成，测试可以注入隔离来源。"""
    # 来源只保留本流程实际使用的身份、事实与向量指纹字段。
    event_fields={'id','user_id','run_id','run_status','diary_id','diary_date','occurred_on',
                  'source_order','title','run_source_sha256','points'}
    point_fields={'id','no','summary','detail','embedding_sha256'}
    def project(events):
        result=[]
        for event in events:
            value={k:v for k,v in event.items()if k in event_fields}
            value['points']=[{k:v for k,v in point.items()if k in point_fields}for point in event['points']]
            result.append(value)
        return result
    current,history=project(current),project(history)
    user = current[0]['user_id'] if current else None
    validate_events(current + history, user)
    day = current[0]['diary_date']
    require(len({(e['diary_id'], e['diary_date'], e['run_id']) for e in current}) == 1, '当前范围必须是一篇日记的一个运行')
    require(all(e['diary_date'] < day for e in history), '历史必须早于当前日记日期')
    require(history_mode in ('database', 'published', 'replay'), '历史模式不合法')
    all_events = current + history
    normalized, models = {}, set()
    for e in all_events:
        for p in e['points']:
            v = vectors.get(p['id'])
            require(isinstance(v, dict) and isinstance(v.get('model'), str) and v['model'], '向量模型标识缺失')
            models.add(v['model']); normalized[p['id']] = validate_vector(v.get('values'))
    require(len(models) == 1, '当前与历史向量模型不一致，不能静默排除历史')
    recall, selected = [], set()
    pair_ids = set()
    for a, b in combinations(current, 2):
        pair_ids.add(tuple(sorted((a['id'], b['id']))))
    for c in current:
        hits = []
        for h in history:
            scored = []
            for cp in c['points']:
                for hp in h['points']:
                    score = max(-1., min(1., sum(x*y for x,y in zip(normalized[cp['id']], normalized[hp['id']]))))
                    scored.append((score, cp['id'], hp['id']))
            best = min(scored, key=lambda x: (-x[0], x[1], x[2]))
            hits.append({'event_id': h['id'], 'run_id': h['run_id'], 'score': best[0],
                         'current_point_id': best[1], 'historic_point_id': best[2]})
        hits.sort(key=lambda x: (-x['score'], x['event_id']))
        admitted = select_history_hits(hits, config)
        for h in admitted:
            selected.add(h['event_id']); pair_ids.add(tuple(sorted((c['id'], h['event_id']))))
        recall.append({'current_event_id': c['id'], 'hits': hits,
                       'selected_event_ids': [h['event_id'] for h in admitted]})
    chosen = sorted(current + [e for e in history if e['id'] in selected],
                    key=lambda e: (e['diary_date'], e['source_order'], e['id']))
    events = {f'E{i:03}': e for i,e in enumerate(chosen, 1)}
    aliases = {e['id']: key for key,e in events.items()}
    pairs = [{'pair_id': 'P-' + digest(list(key))[:16], 'event_a': aliases[key[0]], 'event_b': aliases[key[1]]}
             for key in sorted(pair_ids)]
    snapshot = {'schema_version': VERSION, 'kind': 'diary-event-relations-readonly',
                'user_id': user, 'diary_id': current[0]['diary_id'], 'diary_date': day,
                'current_run_id': current[0]['run_id'], 'history_mode': history_mode,
                'config': config, 'embedding_model': next(iter(models)),
                'events': events, 'pairs': pairs, 'recall': recall,
                'completed_dependencies': list(completed), 'skill_sha256': skill_fingerprint()}
    if history_mode == 'database':
        snapshot['history_inventory'] = list(history_inventory)
        snapshot['history_selection'] = {'source': 'database_formal_points', 'before': day,
            'states': ['POINTS_READY', 'PUBLISHED'], 'month_boundary': False,
            'run_count': sum('run_id' in h for h in history_inventory), 'event_count': len(history),
            'gaps': [h for h in history_inventory if 'gap' in h],
            'point_count': sum(len(e['points']) for e in history)}
    snapshot['package_sha256'] = digest(snapshot)
    return snapshot


def payload(snapshot, pairs):
    aliases = sorted({p[k] for p in pairs for k in ('event_a', 'event_b')})
    events = []
    for alias in aliases:
        e = snapshot['events'][alias]
        events.append({'id': alias, 'title': e['title'], 'diary_date': e['diary_date'],
                       'occurred_on': e.get('occurred_on'),
                       'points': [{k:p[k] for k in ('no','summary','detail')} for p in e['points']]})
    return {'package_sha256': snapshot['package_sha256'], 'events': events, 'pairs': pairs}


def batches(snapshot):
    config = snapshot['config']
    def fits(items):
        return (len(items) <= config['max_pairs_per_batch'] and
                len(json.dumps(payload(snapshot, items), ensure_ascii=False, separators=(',', ':'))) <= config['max_batch_chars'])
    groups, group = [], []
    for pair in snapshot['pairs']:
        require(fits([pair]), '单事件对完整资料超过字符预算；提高 max_batch_chars 后重新准备，不得截断')
        if group and not fits(group + [pair]):
            groups.append(group); group = []
        group.append(pair)
    if group: groups.append(group)
    return [{'batch_id': f'B{i:03}', 'pair_ids': [p['pair_id'] for p in group],
             'payload': payload(snapshot, group)} for i,group in enumerate(groups, 1)]


def write_package(snapshot, root=None):
    groups = batches(snapshot)  # 全部预算检查通过后才创建运行目录。
    base = Path(root) if root is not None else (SKILL_ROOT / snapshot['config']['workspace_root']).resolve()
    name = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
    folder = base / date.fromisoformat(snapshot['diary_date']).isoformat() / str(UUID(snapshot['diary_id'])) / name
    folder.mkdir(parents=True, exist_ok=False)
    try:
        write_json(folder/'source.json', snapshot)
        for b in groups:
            # 紧凑序列化与预算计算一致，避免缩进把已合格的输入再次撑大。
            (folder/(b['batch_id']+'.json')).write_text(json.dumps(b['payload'], ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
        manifest = {'schema_version': VERSION, 'package_sha256': snapshot['package_sha256'],
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'batches': [{k:v for k,v in b.items() if k!='payload'} for b in groups],
                    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}}
        write_json(folder/'run.json', manifest)
    except Exception:
        shutil.rmtree(folder); raise
    return folder


def load_package(folder, *, check_dependencies=True):
    folder = Path(folder).resolve()
    s, manifest = read_json(folder/'source.json'), read_json(folder/'run.json')
    require(s.get('kind') == 'diary-event-relations-readonly' and s.get('schema_version') == VERSION, '来源包类型或版本错误')
    require(s.get('package_sha256') == digest({k:v for k,v in s.items() if k!='package_sha256'}), '来源包指纹不匹配')
    require(manifest.get('package_sha256') == s['package_sha256'], '运行与来源不匹配')
    expected = {'source.json'} | {b['batch_id']+'.json' for b in manifest['batches']}
    require(set(manifest['files']) == expected, '运行文件清单不完整')
    for name, sha in manifest['files'].items():
        require(Path(name).name == name and hashlib.sha256((folder/name).read_bytes()).hexdigest() == sha, '来源或批次文件已修改')
    expected_batches = [{k:v for k,v in b.items() if k!='payload'} for b in batches(s)]
    require(manifest['batches'] == expected_batches, '批次清单与冻结配对不一致')
    if check_dependencies:
        for dependency in s['completed_dependencies']:
            prior, prior_manifest = load_package(dependency['run_dir'], check_dependencies=False)
            rows = saved_results(dependency['run_dir'], prior)
            require(prior['user_id'] == s['user_id'] and prior['diary_date'] < s['diary_date'], '回放依赖用户或日期错误')
            require(prior['package_sha256'] == dependency['package_sha256'] and
                    digest(rows) == dependency['results_sha256'] and progress(prior, rows, prior_manifest)['complete'],
                    '回放依赖未完成或已修订，请重新准备当前日')
    return s, manifest


def check_rows(s, value):
    require(isinstance(value, dict) and set(value) == {'package_sha256','results'}, '结果顶层只接受 package_sha256/results')
    require(value['package_sha256'] == s['package_sha256'], '结果不属于本次冻结来源')
    rows = value['results']
    require(isinstance(rows, list), 'results 必须为数组')
    ids = [r.get('pair_id') if isinstance(r,dict) else None for r in rows]
    require(all(isinstance(pid,str) for pid in ids), '事件对标识必须为字符串')
    require(len(set(ids)) == len(ids), '结果包含重复事件对，不能任选一项接受')
    pairs = {p['pair_id']:p for p in s['pairs']}
    for r in rows:
        require(isinstance(r, dict) and set(r) == {'pair_id','status','reason','relation'}, '逐对结果字段不合法')
        require(r['pair_id'] in pairs, '包含本次清单以外的事件对')
        require(r['status'] in ('RELATED','NO_RELATION','UNRESOLVED','INDIRECT_FOLLOWUP'), '结果状态不合法')
        require(isinstance(r['reason'], str) and r['reason'].strip(), '判断理由不能为空')
        rel = r['relation']
        if r['status'] != 'RELATED':
            require(rel is None, '非正式关系的 relation 必须为 null'); continue
        fields = {'source_event','target_event','relation_type','certainty','source_evidence','target_evidence','description'}
        require(isinstance(rel, dict) and set(rel) == fields, '关系字段不合法')
        pair = pairs[r['pair_id']]
        require(isinstance(rel['source_event'],str) and isinstance(rel['target_event'],str), '关系端点必须为局部事件标识')
        require({rel['source_event'],rel['target_event']} == {pair['event_a'],pair['event_b']}, '关系方向端点不属于指定对')
        require(rel['relation_type'] in ('后续事件','引发事件','提及事件'), '关系类型不合法')
        require(rel['certainty'] in ('EXPLICIT','SPECULATIVE'), '确定性不合法')
        require(isinstance(rel['description'], str) and rel['description'].strip(), '关系描述不能为空')
        for side in ('source','target'):
            evidence = rel[side+'_evidence']
            require(isinstance(evidence,list) and evidence, '双方证据必须非空')
            nums=[]
            points={p['no']:p for p in s['events'][rel[side+'_event']]['points']}
            for item in evidence:
                require(isinstance(item,dict) and set(item)=={'point_no','quote'}, '证据字段必须为 point_no/quote')
                no, quote = item['point_no'], item['quote']
                require(type(no) is int and no in points, '证据序号不属于相应事件')
                require(isinstance(quote,str) and quote.strip(), '证据短引不能为空')
                detail=points[no]['detail']
                positions=[i for i in range(len(detail)) if detail.startswith(quote,i)]
                require(len(positions)==1, '引用不存在或出现多次，请使用唯一的连续原文短引')
                nums.append(no)
            require(len(set(nums))==len(nums), '同一侧证据要点重复')
    return rows


def saved_results(folder,s):
    draft=Path(folder)/'关系结果.md'
    if draft.exists():
        from draft import read_draft
        return read_draft(draft,s,complete=False)[1]
    p=Path(folder)/'results.json'
    return check_rows(s,read_json(p)) if p.exists() else []


def progress(s, rows, manifest):
    finished={r['pair_id'] for r in rows}
    missing=[p['pair_id'] for p in s['pairs'] if p['pair_id'] not in finished]
    return {'package_sha256':s['package_sha256'],'history_mode':s['history_mode'],
            'history_selection':s.get('history_selection'),
            'total_pairs':len(s['pairs']),'completed_pairs':len(rows),'complete':not missing,
            'counts':dict(Counter(r['status'] for r in rows)), 'pending_pair_ids':missing,
            'pending_batches':[b['batch_id'] for b in manifest['batches'] if set(b['pair_ids'])-finished],
            'stored_in_database':False}


@contextmanager
def local_lock(folder):
    with (Path(folder)/'.results.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(stream,fcntl.LOCK_UN)


def record(folder, incoming, *, replace=False):
    with local_lock(folder):
        s, manifest=load_package(folder)
        new=check_rows(s,read_json(incoming))
        old=saved_results(folder,s); byid={r['pair_id']:r for r in old}
        conflicts=[r['pair_id'] for r in new if r['pair_id'] in byid and r!=byid[r['pair_id']]]
        require(not conflicts or replace, '已有不同结论；核对当前稿后用 --replace 保留旧版并修订')
        if any(r!=byid.get(r['pair_id']) for r in new):
            if old:
                write_json(Path(folder)/('results-backup-'+uuid4().hex+'.json'),{'package_sha256':s['package_sha256'],'results':old})
            byid.update({r['pair_id']:r for r in new})
            value={'package_sha256':s['package_sha256'],'results':[byid[p['pair_id']] for p in s['pairs'] if p['pair_id'] in byid]}
            temporary=Path(folder)/('results-'+uuid4().hex+'.tmp')
            try:
                write_json(temporary,value); os.replace(temporary,Path(folder)/'results.json')
            finally:
                temporary.unlink(missing_ok=True)
            # 任何追加或修订后，旧阅读稿不能继续被误认为当前稿。
            for name in ('关系结果.md','resolved-results.json'):
                target=Path(folder)/name
                if target.exists():target.rename(Path(folder)/(target.stem+'-previous-'+uuid4().hex+target.suffix))
        return progress(s,list(byid.values()),manifest)


def render(folder):
    from draft import read_draft, render_text
    from storage import resolve
    with local_lock(folder):
        snapshot,manifest=load_package(folder);rows=saved_results(folder,snapshot)
        state=progress(snapshot,rows,manifest)
        require(state['complete'],'仍有未完成事件对，不能生成完整关系稿')
        path=Path(folder)/'关系结果.md'
        from redundancy import CONTEXT, REPORT, check_report
        if snapshot.get('requires_redundancy_review') or (Path(folder)/CONTEXT).exists() or any(r['status']=='INDIRECT_FOLLOWUP'for r in rows):
            require((Path(folder)/REPORT).exists(),'请先完成后续冗余复核并执行redundancy.py finalize')
            check_report(snapshot,rows,read_json(Path(folder)/REPORT))
        if path.exists():
            # 稿件已是可编辑主稿，重复 render 只校验，不覆盖用户的当前文字。
            read_draft(path,snapshot)
        else:
            content=render_text(snapshot,rows)
            with path.open('x',encoding='utf-8')as stream:stream.write(content)
        receipt_path=Path(folder)/'verification.json'
        receipt=read_json(receipt_path)if receipt_path.exists()else None
        verified=bool(receipt and receipt.get('package_sha256')==snapshot['package_sha256']and receipt.get('verified_against_database')is True)
        write_json(Path(folder)/'resolved-results.json',{'package_sha256':snapshot['package_sha256'],
            'review_origin':'SKILL_AGENT_REVIEW','stored_in_database':False,
            'database_verification':receipt if verified else None,'results':resolve(snapshot,rows)})
        return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-dir',type=Path,default=PROJECT_ROOT/'backend')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('find','prepare'):
        cmd=commands.add_parser(name);cmd.add_argument('--username',required=True)
        target=cmd.add_mutually_exclusive_group(required=True)
        target.add_argument('--date',type=date.fromisoformat);target.add_argument('--diary-id',type=UUID)
        if name=='prepare':
            cmd.add_argument('--run-id',type=UUID)
    for name in ('read','record','status','check','render','verify'):
        cmd=commands.add_parser(name);cmd.add_argument('run_dir',type=Path)
        if name=='read':cmd.add_argument('--batch',required=True);cmd.add_argument('--pending-only',action='store_true')
        if name=='record':
            source=cmd.add_mutually_exclusive_group(required=True)
            source.add_argument('--input',type=Path);source.add_argument('--markdown',type=Path)
            cmd.add_argument('--replace',action='store_true')
    cmd=commands.add_parser('convert');cmd.add_argument('run_dir',type=Path)
    cmd.add_argument('--markdown',type=Path,required=True);cmd.add_argument('--output',type=Path,required=True)
    cmd=commands.add_parser('schema');cmd.add_argument('--write',action='store_true')
    cmd=commands.add_parser('prepare-storage');cmd.add_argument('run_dir',type=Path)
    cmd.add_argument('--username',required=True);cmd.add_argument('--output',type=Path);cmd.add_argument('--markdown',type=Path)
    cmd.add_argument('--replace-published',action='store_true')
    cmd.add_argument('--accept-published-revisions',action='store_true')
    for name in ('save','storage-status'):
        cmd=commands.add_parser(name);cmd.add_argument('packet',type=Path);cmd.add_argument('--username',required=True)
        if name=='save':
            cmd.add_argument('--write',action='store_true');cmd.add_argument('--confirmed-sha256')
            cmd.add_argument('--replace-published',action='store_true')
            cmd.add_argument('--accept-published-revisions',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command in ('schema','prepare-storage','save','storage-status'):
            from storage import execute
            result=execute(args)
        elif args.command in ('find','prepare','verify'):
            from db_source import find, prepare, verify
            if args.command=='find': result=find(args)
            elif args.command=='prepare':
                s=prepare(args);folder=write_package(s)
                result={'run_dir':str(folder),'pairs':len(s['pairs']),'events':len(s['events']),
                        'package_sha256':s['package_sha256'],'history_mode':s['history_mode']}
            else:result=verify(args)
        elif args.command in ('record','convert')and getattr(args,'markdown',None)is not None:
            from draft import read_draft
            snapshot,_=load_package(args.run_dir)
            _,rows=read_draft(args.markdown,snapshot,complete=args.command=='convert')
            value={'package_sha256':snapshot['package_sha256'],'results':rows}
            if args.command=='convert':
                with args.output.open('x',encoding='utf-8')as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
                result={'output':str(args.output.resolve()),'pairs':len(rows),'stored_in_database':False}
            else:
                temporary=Path(args.run_dir)/('markdown-import-'+uuid4().hex+'.json')
                try:
                    write_json(temporary,value);result=record(args.run_dir,temporary,replace=args.replace)
                finally:temporary.unlink(missing_ok=True)
        elif args.command=='record':result=record(args.run_dir,args.input,replace=args.replace)
        elif args.command=='render':result=render(args.run_dir)
        else:
            s,manifest=load_package(args.run_dir);rows=saved_results(args.run_dir,s)
            result=progress(s,rows,manifest)
            if args.command=='read':
                group=next((b for b in manifest['batches'] if b['batch_id']==args.batch),None)
                require(group is not None,'批次不存在')
                done={r['pair_id'] for r in rows} if args.pending_only else set()
                selected=[p for p in s['pairs'] if p['pair_id'] in group['pair_ids'] and p['pair_id'] not in done]
                print(json.dumps(payload(s,selected),ensure_ascii=False,separators=(',',':')));return 0
            if args.command=='check':require(result['complete'],'仍有未完成事件对，请用 status 查看')
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False,default=str));return 0
    except WorkflowError as exc:print('处理停止：'+str(exc),file=sys.stderr)
    except Exception as exc:
        blocked='Operation not permitted' in str(exc)
        message='环境拒绝网络访问，请按权限流程重试只读命令' if blocked else type(exc).__name__
        print('处理停止：'+message,file=sys.stderr)
    return 1


if __name__=='__main__':
    sys.modules['workflow'] = sys.modules[__name__]
    raise SystemExit(main())
