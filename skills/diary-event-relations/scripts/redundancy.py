#!/usr/bin/env python3
"""后续边冗余预检；程序检查路径，当前agent完成全部语义决定。默认不写数据库。"""
import argparse
from collections import defaultdict, deque
from copy import deepcopy
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from skill_api import api_enabled, request
from uuid import uuid4

from workflow import (PROJECT_ROOT, WorkflowError, check_rows, digest, load_package,
                      local_lock, read_json, require, saved_results, write_json)

CONTEXT = 'redundancy-context.json'
REVIEW = 'redundancy-review.json'
REPORT = 'redundancy-final.json'


def history_context(conn, snapshot):
    """重查准入清单及全部历史后续边，捕获新增/删除边及要点内容变化。"""
    from db_source import database_history, load_run, query
    uid, day = snapshot['user_id'], snapshot['diary_date']
    events, _, inventory = database_history(conn, uid, day)
    if 'history_inventory' in snapshot:
        require(inventory == snapshot['history_inventory'], '历史正式要点已变化，请新建关系识别运行')
    byid = {e['id']: e for e in events}
    edges = []
    for row in query(conn, """SELECT e.id,e.run_id,e.source_event_id,e.target_event_id,
             e.source_run_id,e.target_run_id,e.description,e.certainty
             FROM graph_event_relations e JOIN graph_runs r ON r.id=e.run_id AND r.user_id=e.user_id
             WHERE e.user_id=:uid AND r.status='PUBLISHED' AND r.diary_date<:day
             AND e.relation_type='后续事件' ORDER BY e.id""", {'uid': uid, 'day': day}):
        a, b = str(row['source_event_id']), str(row['target_event_id'])
        require(a in byid and b in byid, '历史后续边端点已失效，不能静默排除')
        require(byid[a]['run_id'] == str(row['source_run_id']) and
                byid[b]['run_id'] == str(row['target_run_id']), '历史后续边引用过期运行')
        proof = []
        for p in query(conn, 'SELECT side,point_id,point_event_id,point_run_id FROM graph_relation_evidence WHERE relation_id=:id ORDER BY side,point_id', {'id': str(row['id'])}):
            require(p['side'] in ('SOURCE', 'TARGET'), '历史证据侧别非法')
            eid = a if p['side'] == 'SOURCE' else b
            require(str(p['point_event_id']) == eid and str(p['point_run_id']) == byid[eid]['run_id'], '历史证据归属错误')
            require(str(p['point_id']) in {v['id'] for v in byid[eid]['points']}, '历史关系要点证据已失效')
            proof.append({'side': p['side'], 'point_id': str(p['point_id'])})
        require({p['side'] for p in proof} == {'SOURCE', 'TARGET'}, '历史后续边缺少双方证据')
        edges.append({'edge_id': 'H:' + str(row['id']), 'source': a, 'target': b,
                      'description': row['description'], 'certainty': row['certainty'], 'evidence': proof})
    material = {'events': {e['id']: {k: e[k] for k in ('id','run_id','user_id','diary_id','diary_date','title','points')} for e in events}, 'edges': edges}
    return material


def candidate_edges(snapshot, rows):
    result = []
    for row in rows:
        rel = row['relation']
        if row['status'] == 'RELATED' and rel['relation_type'] == '后续事件':
            result.append({'edge_id': 'C:' + row['pair_id'], 'pair_id': row['pair_id'],
                           'source': snapshot['events'][rel['source_event']]['id'],
                           'target': snapshot['events'][rel['target_event']]['id'],
                           'description': rel['description'], 'relation': rel})
    return result


def alternative(edges, edge, excluded=()):
    blocked = set(excluded) | {edge['edge_id']}
    adj = defaultdict(list)
    for e in edges:
        if e['edge_id'] not in blocked:
            adj[e['source']].append(e)
    queue = deque([(edge['source'], [])]); seen = {edge['source']}
    while queue:
        node, path = queue.popleft()
        for nxt in sorted(adj[node], key=lambda e: e['edge_id']):
            p = path + [nxt['edge_id']]
            if nxt['target'] == edge['target'] and len(p) >= 2:
                return p
            if nxt['target'] not in seen:
                seen.add(nxt['target']); queue.append((nxt['target'], p))
    return None


def make_context(snapshot, rows, history):
    check_rows(snapshot, {'package_sha256': snapshot['package_sha256'], 'results': rows})
    require({r['pair_id'] for r in rows} == {p['pair_id'] for p in snapshot['pairs']}, '先完成全部初步关系判断')
    require(not any(r['status'] == 'INDIRECT_FOLLOWUP' for r in rows), '请使用冗余检查前的完整初稿准备，保留当前稿及旧检查记录')
    candidates = candidate_edges(snapshot, rows)
    edges = history['edges'] + candidates
    flagged = [{'pair_id': e['pair_id'], 'found_path': path} for e in candidates
               if (path := alternative(edges, e)) is not None]
    value = {'schema_version': 1, 'package_sha256': snapshot['package_sha256'],
             'base_rows': deepcopy(rows), 'history': history, 'candidates': candidates, 'flagged': flagged}
    value['context_sha256'] = digest(value)
    return value


def validate_context(snapshot, ctx):
    require(ctx.get('schema_version') == 1 and ctx.get('package_sha256') == snapshot['package_sha256'], '冗余来源版本不匹配')
    require(ctx.get('context_sha256') == digest({k:v for k,v in ctx.items() if k != 'context_sha256'}), '冗余上下文指纹不匹配')
    expected = make_context(snapshot, ctx['base_rows'], ctx['history'])
    require(expected == ctx, '冗余候选或路径与冻结输入不符')


def validate_decisions(ctx, decisions, *, complete=False):
    require(isinstance(decisions,list),'语义决定必须为数组')
    flagged = {x['pair_id'] for x in ctx['flagged']}
    candidates = {e['pair_id']:e for e in ctx['candidates']}
    edges = {e['edge_id']:e for e in ctx['history']['edges'] + ctx['candidates']}
    seen = set()
    for d in decisions:
        require(isinstance(d, dict) and set(d) == {'pair_id','decision','reason','replacement_path'}, '语义决定字段不完整')
        pid = d['pair_id']
        require(pid in flagged and pid not in seen, '遗漏范围外或重复的语义决定'); seen.add(pid)
        require(d['decision'] in ('KEEP','INDIRECT_FOLLOWUP'), '语义决定仅接受KEEP或INDIRECT_FOLLOWUP')
        require(isinstance(d['reason'], str) and d['reason'].strip(), '语义理由不能为空')
        path = d['replacement_path']
        require(isinstance(path, list), '替代路径必须为边ID数组')
        if d['decision'] == 'KEEP':
            require(not path, '保留直连不应附替代路径'); continue
        require(len(path) >= 2 and all(isinstance(k,str) and k in edges for k in path), '替代路径须至少两条真实后续边')
        node = candidates[pid]['source']; visited = {node}
        for key in path:
            edge = edges[key]
            require(key != candidates[pid]['edge_id'] and edge['source'] == node, '替代路径包含自身或不连续')
            node = edge['target']; require(node not in visited, '替代路径不能成环'); visited.add(node)
        require(node == candidates[pid]['target'], '替代路径终点不匹配')
    if complete: require(seen == flagged, '仍有待复核后续边，必须由模型逐条完成，不能只交付样例')
    return decisions


def final_rows(ctx, decisions):
    validate_decisions(ctx, decisions, complete=True)
    dropped = {'C:' + d['pair_id'] for d in decisions if d['decision'] == 'INDIRECT_FOLLOWUP'}
    failures = [d['pair_id'] for d in decisions if d['decision'] == 'INDIRECT_FOLLOWUP'
                and dropped.intersection(d['replacement_path'])]
    require(not failures, '最终认可路径含本批被过滤边，退回模型补审路径或保留直连：' + ','.join(failures))
    byid = {d['pair_id']:d for d in decisions}
    rows = deepcopy(ctx['base_rows'])
    for row in rows:
        d = byid.get(row['pair_id'])
        if d and d['decision'] == 'INDIRECT_FOLLOWUP':
            row.update(status='INDIRECT_FOLLOWUP', relation=None,
                       reason=d['reason'] + '\n\n已核对的保留路径：' + ' → '.join(d['replacement_path']))
    return rows


def normalized_rows(rows):
    result=deepcopy(rows)
    for row in result:
        if row['relation']:
            for side in ('source','target'):row['relation'][side+'_evidence'].sort(key=lambda e:e['point_no'])
    return sorted(result,key=lambda r:r['pair_id'])


def check_report(snapshot, rows, report):
    require(isinstance(report,dict) and set(report) == {'context','decisions','final_rows_sha256'}, '缺少完整冗余复核归档')
    ctx = report['context']; validate_context(snapshot, ctx)
    expected = final_rows(ctx, report['decisions'])
    canonical = normalized_rows
    require(canonical(rows) == canonical(expected) and report['final_rows_sha256'] == digest(canonical(expected)), '当前稿与已完成冗余复核不一致，请重新复核')
    return report


def review_rows(folder, ctx):
    path = Path(folder)/REVIEW
    if not path.exists(): return []
    data = read_json(path)
    require(data.get('context_sha256') == ctx['context_sha256'], '语义复核不属于当前上下文')
    return validate_decisions(ctx, data['decisions'])


def execute(args):
    folder = args.run_dir
    with local_lock(folder):
        snapshot,_ = load_package(folder)
        if args.command == 'prepare':
            from db_source import connection
            rows = saved_results(folder,snapshot)
            if api_enabled():
                history = request('relations', 'history-context', {'snapshot': snapshot})['history']
            else:
                with connection(args.backend_dir) as conn: history = history_context(conn,snapshot)
            ctx = make_context(snapshot,rows,history)
            if (folder/CONTEXT).exists():
                require(read_json(folder/CONTEXT) == ctx, '已有不同冗余上下文，请保留当前运行并新建识别运行')
            else: write_json(folder/CONTEXT,ctx)
        else:
            ctx = read_json(folder/CONTEXT); validate_context(snapshot,ctx)
        decisions = review_rows(folder,ctx)
        if args.command == 'read':
            events = {**ctx['history']['events'], **{e['id']:e for e in snapshot['events'].values()}}
            if args.edge_id:
                edge=next((e for e in ctx['history']['edges']+ctx['candidates']if e['edge_id']==args.edge_id),None)
                require(edge is not None,'边不属于冗余上下文')
                return {'edge':edge,'events':{n:events[n]for n in (edge['source'],edge['target'])}}
            if args.event_id:
                require(args.event_id in events, '事件不属于冗余上下文')
                return events[args.event_id]
            selected = next((v for v in ctx['flagged'] if v['pair_id'] == args.pair_id),None)
            require(selected is not None, '指定事件对不在待复核清单')
            edges = ctx['history']['edges'] + ctx['candidates']
            byid = {e['edge_id']:e for e in edges}
            direct = byid['C:'+args.pair_id]
            keys = [direct['edge_id']] + selected['found_path']
            nodes = {byid[k][side] for k in keys for side in ('source','target')}
            # 只索引能够位于此对端点之间的路径；分页返回，不静默截断。
            def reachable(start, reverse=False):
                adj=defaultdict(set)
                for e in edges:
                    if e['edge_id']==direct['edge_id']:continue
                    adj[e['target']if reverse else e['source']].add(e['source']if reverse else e['target'])
                seen={start};todo=[start]
                while todo:
                    for v in adj[todo.pop()]:
                        if v not in seen:seen.add(v);todo.append(v)
                return seen
            scope=reachable(direct['source']) & reachable(direct['target'],True)
            index=[{k:e[k]for k in ('edge_id','source','target')}for e in edges
                   if e['edge_id']!=direct['edge_id']and e['source']in scope and e['target']in scope]
            require(args.index_offset>=0 and args.index_limit>0,'索引分页参数非法')
            stop=args.index_offset+args.index_limit
            return {'context_sha256':ctx['context_sha256'], 'pair':direct,
                    'found_path':selected['found_path'], 'edges':[byid[k] for k in keys],
                    'events':{n:events[n] for n in sorted(nodes)},
                    'graph_index':index[args.index_offset:stop], 'index_total':len(index),
                    'next_index_offset':stop if stop<len(index)else None}
        if args.command == 'record':
            incoming = read_json(args.input)
            require(set(incoming) == {'context_sha256','decisions'} and incoming['context_sha256'] == ctx['context_sha256'], '模型结果来源指纹不符')
            validate_decisions(ctx,incoming['decisions'])
            byid = {d['pair_id']:d for d in decisions}
            for d in incoming['decisions']:
                require(d['pair_id'] not in byid or byid[d['pair_id']] == d or args.replace, '修改决定须使用--replace并保留旧记录')
                byid[d['pair_id']] = d
            decisions = [byid[k] for k in sorted(byid)]
            if (folder/REVIEW).exists():
                write_json(folder/('redundancy-review-backup-'+uuid4().hex+'.json'),read_json(folder/REVIEW))
            write_json(folder/REVIEW,{'context_sha256':ctx['context_sha256'],'decisions':decisions})
        if args.command == 'finalize':
            from draft import render_text
            rows = final_rows(ctx,decisions)
            actual = saved_results(folder,snapshot)
            require(actual == ctx['base_rows'] or sorted(actual,key=lambda r:r['pair_id']) == sorted(rows,key=lambda r:r['pair_id']), '初步稿已改动，请重新完成冗余复核')
            report = {'context':ctx,'decisions':decisions,'final_rows_sha256':digest(normalized_rows(rows))}
            check_report(snapshot,rows,report)
            path = folder/'关系结果.md'
            # 已有最终稿语义一致时保留其原始文字和排版，不从缓存覆盖人工稿。
            already_final = (folder/REPORT).exists() and path.exists() and normalized_rows(actual)==normalized_rows(rows)
            if not already_final:
                if path.exists(): path.rename(folder/('关系结果-冗余前-'+uuid4().hex+'.md'))
                path.write_text(render_text(snapshot,rows),encoding='utf-8')
            write_json(folder/REPORT,report)
        pending = sorted({v['pair_id'] for v in ctx['flagged']} - {d['pair_id'] for d in decisions})
        invalid = [d['pair_id'] for d in decisions if d['decision']=='INDIRECT_FOLLOWUP' and
                   set(d['replacement_path']) & {'C:'+v['pair_id'] for v in decisions if v['decision']=='INDIRECT_FOLLOWUP'}]
        return {'context_sha256':ctx['context_sha256'],'followup_candidates':len(ctx['candidates']),
                'needs_review':len(ctx['flagged']),'reviewed':len(decisions),
                'pending_pair_ids':pending,'repair_pair_ids':invalid,
                'ready_to_finalize':not pending and not invalid,'stored_in_database':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-dir',type=Path,default=PROJECT_ROOT/'backend')
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ('prepare','read','record','status','finalize'):
        cmd=subs.add_parser(name);cmd.add_argument('run_dir',type=Path)
        if name=='read':
            group=cmd.add_mutually_exclusive_group(required=True)
            group.add_argument('--pair-id');group.add_argument('--event-id');group.add_argument('--edge-id')
            cmd.add_argument('--index-offset',type=int,default=0);cmd.add_argument('--index-limit',type=int,default=50)
        if name=='record':cmd.add_argument('--input',type=Path,required=True);cmd.add_argument('--replace',action='store_true')
    try:
        print(json.dumps(execute(parser.parse_args(argv)),ensure_ascii=False,indent=2));return 0
    except WorkflowError as exc:print('处理停止：'+str(exc),file=sys.stderr)
    except Exception as exc:print('处理停止：'+type(exc).__name__,file=sys.stderr)
    return 1


if __name__=='__main__':
    sys.modules['redundancy']=sys.modules[__name__]
    raise SystemExit(main())
