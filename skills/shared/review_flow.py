"""云端人工审阅暂停与恢复记录；语义复查由 Agent 完成。"""
from contextlib import contextmanager
from datetime import date
import fcntl
import json
import os
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]


def folder_for(source, root=None):
    s = source['source']
    return Path(root or ROOT / 'diary-workflows') / date.fromisoformat(s['diary_date']).isoformat() / str(UUID(s['diary_id']))


@contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.review.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(stream, fcntl.LOCK_UN)


def read_state(folder):
    path = folder / 'state.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def save_state(folder, state):
    path = folder / 'state.json'
    temp = folder / 'state.json.tmp'
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def transition(action, source, *, user_message=None, report=None, root=None):
    # 指纹与身份由与整理导出共用的协议校验。
    import hashlib
    unsigned = {k: v for k, v in source.items() if k != 'source_sha256'}
    sha = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if source.get('kind') != 'diary-organized-review' or sha != source.get('source_sha256'):
        raise ValueError('复查来源格式或指纹错误')
    folder = folder_for(source, root)
    with locked(folder):
        state = read_state(folder)
        identity = {k: source['source'][k] for k in ('user_id', 'diary_id', 'organized_id')}
        if state and state['identity'] != identity: raise ValueError('审阅记录的目标身份已变化')
        if action == 'wait':
            if state:
                if state.get('baseline') != source: raise ValueError('已有不同的审阅记录，请先核对原流程')
                return state
            state = {'schema_version': 1, 'identity': identity, 'phase': 'waiting_user_review', 'baseline': source}
        elif action == 'start':
            if not user_message or not user_message.strip(): raise ValueError('须记录用户实际通知继续的原话')
            state = state or {'schema_version': 1, 'identity': identity, 'baseline': source, 'baseline_recovered': True}
            state.update(phase='reviewing_changes', user_message=user_message, review_started_source=source)
        elif action == 'finish':
            if not state or state['phase'] != 'reviewing_changes': raise ValueError('尚未收到用户继续通知并开始复查')
            expected = sorted(e['event_id'] for e in source['events'])
            if not isinstance(report, dict) or report.get('source_sha256') != source['source_sha256']:
                raise ValueError('复查记录与最终来源不一致')
            if sorted(report.get('reviewed_event_ids', [])) != expected or report.get('plans_reviewed') is not True:
                raise ValueError('必须复查全部当前事件的感受、反思与成长及整篇后续计划')
            if report.get('pending_questions') != [] or not isinstance(report.get('conclusion'), str) or not report['conclusion'].strip():
                raise ValueError('复查须有具体结论且无待澄清问题')
            state.update(phase='ready_for_points', reviewed_source=source, report=report)
        else: raise ValueError('未知状态操作')
        save_state(folder, state)
        return state


def gate(result, fetch_source):
    if result.get('blocked') or 'organize' not in result.get('completed_stages', []) or 'points' in result.get('completed_stages', []):
        return result
    stub = {'source': {'diary_id': result['diary_id'], 'diary_date': result['diary_date']}}
    folder = folder_for(stub)
    with locked(folder): state = read_state(folder)
    reason = '整理已保存，等待用户在应用中审阅并明确通知继续'
    if state and state.get('phase') == 'ready_for_points':
        current = fetch_source()
        if current == state.get('reviewed_source'): return result
        reason = '联动复查后来源又发生修改，须重新读取并复查'
    elif state and state.get('phase') == 'reviewing_changes':
        reason = '用户已通知继续，须先完成修改后的联动复查'
    elif not state:
        reason = '缺少人工审阅记录，请导出当前结果并核实用户审阅情况'
    return {**result, 'database_next_stage': result['next_stage'], 'next_stage': 'review',
            'review_required': True, 'review_phase': state['phase'] if state else 'missing_record', 'reason': reason}
