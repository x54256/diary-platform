#!/usr/bin/env python3
"""只读检查日记四阶段进度；来源核验复用现有关系 Skill。"""

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from datetime import date
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / 'skills/diary-event-relations/scripts'))
from db_source import connection, list_diaries, load_run, query
from workflow import WorkflowError


def inspect_diary(conn, user_id, diary, validate_run=load_run):
    """在调用方的同一只读快照内确认来源、有效运行和下一阶段。"""
    did = str(diary['id'])
    params = {'uid': user_id, 'did': did}
    orgs = query(conn, '''SELECT o.id, o.source_content_revision, o.structured_revision,
        d.content_revision FROM diary_organized o JOIN diaries d ON d.id=o.diary_id
        WHERE d.id=:did AND d.user_id=:uid''', params)
    analyses = query(conn, '''SELECT id,status,diary_organized_id,source_structured_revision
        FROM analysis_runs WHERE diary_id=:did ORDER BY created_at,id''', params)
    active = query(conn, '''SELECT id FROM graph_tasks
        WHERE user_id=:uid AND status IN ('QUEUED','RUNNING')''', params)
    organizing = query(conn, '''SELECT id FROM organize_tasks
        WHERE diary_id=:did AND status='running' ''', params)
    result = {'diary_id': did, 'diary_date': str(diary['diary_date']),
              'diary_status': diary['status'], 'blocked': False,
              'completed_stages': [], 'next_stage': None}

    def stop(reason):
        result.update(blocked=True, reason=reason)
        return result

    if active or organizing:
        result['active_task_ids'] = [str(r['id']) for r in active + organizing]
        return stop('已有活动任务，请先查询原任务进度，不重复启动')
    if len(orgs) > 1:
        return stop('存在多份整理结果，需先核实目标版本')
    runs = diary['runs']
    valid_org = (len(orgs) == 1 and not diary['is_dirty']
                 and orgs[0]['source_content_revision'] == orgs[0]['content_revision']
                 and diary['status'] in ('organized', 'analyzed'))
    if not valid_org:
        if runs or analyses or diary['status'] == 'analyzed':
            return stop('整理来源缺失或失效，且已有下游结果，需先处理来源修订范围')
        result['next_stage'] = 'organize'
        return result
    result['completed_stages'].append('organize')
    result['organized_id'] = str(orgs[0]['id'])
    result['structured_revision'] = orgs[0]['structured_revision']

    if len(runs) > 1:
        return stop('存在多个有效要点运行，需核实运行，不自动取最新一条')
    if runs:
        run = runs[0]
        try:
            events, _ = validate_run(conn, user_id, run['id'], published=run['status'] == 'PUBLISHED')
        except WorkflowError as exc:
            return stop(str(exc))
        result.update(graph_run_id=str(run['id']), graph_run_status=run['status'],
                      events=len(events), points=sum(len(e['points']) for e in events))
        result['completed_stages'].append('points')
        if run['status'] == 'PUBLISHED':
            result['completed_stages'].append('relations')
    else:
        failed = query(conn, '''SELECT DISTINCT t.id FROM graph_tasks t
            JOIN graph_runs r ON r.task_id=t.id
            WHERE r.diary_id=:did AND t.user_id=:uid AND t.status='FAILED'
            AND r.status IN ('QUEUED','RUNNING','FAILED')''', params)
        if failed:
            result['failed_task_ids'] = [str(r['id']) for r in failed]
            return stop('发现未完成的失败任务，请按原阶段的入库包查询并恢复')

    current = [r for r in analyses if r['status'] == 'CURRENT']
    if analyses:
        if (len(current) != 1 or diary['status'] != 'analyzed'
                or str(current[0]['diary_organized_id']) != result['organized_id']
                or current[0]['source_structured_revision'] != result['structured_revision']):
            return stop('已有分析轮次但当前分析来源或状态不一致，分析 Skill 不支持自动重分析')
        result['analysis_run_id'] = str(current[0]['id'])
        result['completed_stages'].append('analyze')
    elif diary['status'] == 'analyzed':
        return stop('日记标为已分析但缺少分析轮次，需先核实数据状态')

    for stage in ('organize', 'points', 'relations', 'analyze'):
        if stage not in result['completed_stages']:
            result['next_stage'] = stage
            break
    else:
        result['next_stage'] = 'complete'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-dir', type=Path, default=PROJECT_ROOT / 'backend')
    parser.add_argument('--username', default='x5456')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--date', type=date.fromisoformat)
    target.add_argument('--diary-id', type=UUID)
    args = parser.parse_args()
    from skill_api import maybe_remote
    maybe_remote("workflow", args)
    try:
        with connection(args.backend_dir) as conn:
            found = list_diaries(conn, args.username, args.date, args.diary_id)
            result = {'username': args.username, 'user_id': found['user_id'],
                      'match_count': len(found['diaries']), 'read_only': True}
            if len(found['diaries']) == 1:
                result.update(inspect_diary(conn, found['user_id'], found['diaries'][0]))
            else:
                result.update(selection_required=True,
                              candidates=[{'diary_id': str(d['id']), 'diary_date': str(d['diary_date']),
                                           'status': d['status']} for d in found['diaries']])
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except WorkflowError as exc:
        print('检查停止：' + str(exc), file=sys.stderr)
    except Exception as exc:
        print('检查失败，异常类型：' + type(exc).__name__ + '；未写入数据库', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
