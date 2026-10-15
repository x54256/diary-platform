"""独立复测入口：原要点脚本＋按实验记录重建的关系验证；仅写本地文件。"""

import argparse
import asyncio
import hashlib
import json
import math
import sys
from dataclasses import replace
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.historical_layer1_validation import validate_event_points_baseline as baseline


def read(path):
    return json.loads(path.read_text())


def cosine(a, b):
    return sum(x*y for x, y in zip(a, b)) / math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))


def language_config(role, model):
    from services.model_runtime import resolve_model_setting
    cfg = resolve_model_setting('graph', 'graph_' + role)
    if model == 'kimi-k3':
        # 仅覆盖本次实验请求，不写模型目录或管理端用途配置。
        cfg = replace(cfg, model_name=model, reasoning_mode='always_on', thinking_enabled=True,
                      thinkmode={'enabled': {'enable_thinking': True}})
    assert cfg.model_name == model and cfg.thinking_enabled
    return cfg


async def point_model_override(folder, event, model):
    cfg = language_config('point_generate', model)
    spec = read(baseline.BASELINE_FILE)
    for name, prompt in spec['prompts'].items():
        assert hashlib.sha256(prompt.encode()).hexdigest() == spec['prompt_sha256'][name]
    value = {k: event[k] for k in ('title', 'paragraphs')}
    source = {**value, 'source_units': baseline.units(value)}
    out = folder/'points'/event['id']
    manifest = {'model': model, 'version': spec['version'], 'prompt_sha256': spec['prompt_sha256'],
                'source_sha256': baseline_hash(value), 'repair_limit': 2, 'thinking': True,
                'baseline_functions': 'call,validate_points,validate_combined,validate_review,run_combined',
                'production_writes': False}
    if (out/'manifest.json').exists():
        assert read(out/'manifest.json') == manifest
    baseline.save(out/'manifest.json', manifest)
    candidate = await baseline.call(cfg, spec['prompts']['generate'], value, out, 'generate',
                                    lambda d: baseline.validate_points(d, value))
    await baseline.run_combined(cfg, spec['prompts'], source, value, candidate, out)


async def points(folder, source, model):
    outcomes = []
    for event in source['events']:
        print(json.dumps({'开始原要点脚本': event['title']}, ensure_ascii=False), flush=True)
        sys.argv = ['validate_event_points_baseline.py', '--source', str(folder/'source.json'),
                    '--event-id', event['id'], '--out', str(folder/'points'/event['id']),
                    '--model', 'qwen3.7-flash-2026-07-15']
        try:
            if model == 'qwen3.7-flash-2026-07-15':
                await baseline.main()
            else:
                await point_model_override(folder, event, model)
            status = read(folder/'points'/event['id']/'model-status.json')
            outcomes.append({'event_id': event['id'], **status})
        except Exception as error:
            # 原脚本只向此处抛出已脱敏服务错误或结构校验错误。
            outcomes.append({'event_id': event['id'], 'failed': True,
                             'error_type': type(error).__name__, 'error': str(error)[:300]})
        baseline.save(folder/'point-outcomes.json', outcomes)
        print(json.dumps(outcomes[-1], ensure_ascii=False), flush=True)


async def optimized_points(folder, source, model):
    """调用正式提取函数，在本地检查点中验证新协议，不发布业务数据。"""
    from types import SimpleNamespace
    from uuid import uuid5, NAMESPACE_URL
    from services.graph_points import extract_event
    spec = read(Path(__file__).parent/'fixtures/event_point_optimized.json')
    for name, prompt in spec['prompts'].items():
        assert hashlib.sha256(prompt.encode()).hexdigest() == spec['prompt_sha256'][name]
    cfg = language_config('point_generate', model)
    prompts = {'point_generate': spec['prompts']['generate'], 'point_combined': spec['prompts']['combined'],
               'point_review': spec['prompts']['review']}
    semaphore = asyncio.Semaphore(2)
    outcomes = {}

    async def one(event):
        async with semaphore:
            out = folder/'points'/event['id']
            manifest = {'model': model, 'point_version': spec['version'],
                        'source_sha256': baseline_hash(event), 'prompt_sha256': spec['prompt_sha256']}
            if (out/'manifest.json').exists():
                assert read(out/'manifest.json') == manifest, '样本或配置改变，须使用新目录'
            baseline.save(out/'manifest.json', manifest)

            class LocalContext:
                config = {'point_review_protocol': 'issues-v2'}
                run_id = uuid5(NAMESPACE_URL, str(folder)+event['id'])

                def __init__(self):
                    self.state = read(out/'checkpoint.json') if (out/'checkpoint.json').exists() else {}

                def owned(self, db):
                    return SimpleNamespace(retry_count=0)

                def save(self, step=None, **changes):
                    self.state.update(changes)
                    baseline.save(out/'checkpoint.json', self.state)
                    work = self.state.get('point_work', {}).get(event['id'], {})
                    if work.get('candidate'):
                        baseline.save(out/'candidate.json', work['candidate'])
                    return self.state

                async def call(self, role, key, payload, validator):
                    label = 'generate' if role == 'point_generate' else (
                        ('combined-' if role == 'point_combined' else 'review-')+key.rsplit(':',1)[-1])
                    return await baseline.call(cfg, prompts[role], payload, out, label, validator)

            ctx = LocalContext()
            print(json.dumps({'开始新版审核': event['title']}, ensure_ascii=False), flush=True)
            try:
                if not ctx.state.get('point_work', {}).get(event['id'], {}).get('passed'):
                    await extract_event(ctx, {'event_id': event['id'], 'title': event['title'],
                        'body': [p['text'] for p in event['paragraphs']]}, ctx.state)
                work = ctx.state['point_work'][event['id']]
                result = {'event_id': event['id'], 'passed': True, 'points': len(work['points'])}
            except Exception as error:
                result = {'event_id': event['id'], 'passed': False, 'error_type': type(error).__name__,
                          'error': str(error)[:300]}
            outcomes[event['id']] = result
            baseline.save(folder/'point-outcomes.json', list(outcomes.values()))
            print(json.dumps(result, ensure_ascii=False), flush=True)

    await asyncio.gather(*(one(event) for event in source['events']))


def validate_result(data, pairs, events):
    # 仅复用结构与引用检查，不调用正式建图调度、召回或发布流程。
    from services.graph_relations import validate_pair
    assert isinstance(data, dict) and set(data) == {'results'}, '关系输出顶层必须仅含results'
    rows = data['results']
    assert isinstance(rows, list), '关系results必须为数组'
    assert all(isinstance(r, dict) and isinstance(r.get('pair_id'), str) for r in rows), '关系结果每项须含字符串pair_id'
    expected, actual = sorted(p['pair_id'] for p in pairs), sorted(r['pair_id'] for r in rows)
    assert actual == expected, f'关系编号必须完整且唯一；预期{expected}，实际{actual}'
    by_id = {r['pair_id']: r for r in rows}
    for pair in pairs:
        validate_pair(by_id[pair['pair_id']], pair, events)


def equivalent(a, b):
    if a['status'] != b['status']:
        return False
    if a['status'] != 'RELATED':
        return True
    def canonical(row):
        rel = dict(row['relation'])
        rel['description'] = rel['description'].strip()
        for key in ('source_point_nos', 'target_point_nos'):
            rel[key] = sorted(rel[key])
        return rel
    return canonical(a) == canonical(b)


def payload(pairs, events):
    ids = sorted({p[k] for p in pairs for k in ('event_a_id', 'event_b_id')})
    return {'events': [{k: events[i][k] for k in ('id', 'title', 'diary_date', 'points')}
                       | {'occurred_on': None} for i in ids], 'pairs': pairs}


async def vectors(cfg, events, path):
    import httpx
    if path.exists():
        saved = read(path)
        assert saved['input_sha256'] == baseline_hash(events)
        return saved['vectors']
    texts = [p['detail'] for e in events.values() for p in e['points']]
    # 批量只改变运输方式；每个要点的完整detail分别编码。
    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(cfg.api_base_url.rstrip('/')+'/embeddings',
            headers={'Authorization': 'Bearer '+cfg.api_key},
            json={'model': cfg.model_name, 'input': texts, 'dimensions': 1024, 'encoding_format': 'float'})
    if response.status_code != 200:
        baseline.save(path.with_name('embedding-error.json'), {'http_status': response.status_code})
        raise RuntimeError('向量请求HTTP '+str(response.status_code))
    result = response.json()
    rows = sorted(result['data'], key=lambda r: r['index'])
    assert [r['index'] for r in rows] == list(range(len(texts)))
    for row in rows:
        v = row['embedding']
        assert len(v) == 1024 and all(type(x) in (int, float) and math.isfinite(x) for x in v)
        assert sum(x*x for x in v) > 0
    result_by_event, offset = {}, 0
    for key, event in events.items():
        result_by_event[key] = [r['embedding'] for r in rows[offset:offset+len(event['points'])]]
        offset += len(event['points'])
    baseline.save(path, {'input_sha256': baseline_hash(events), 'model': cfg.model_name,
                         'usage': result.get('usage'), 'requests': 1, 'vectors': result_by_event})
    return result_by_event


def baseline_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def relations(folder, source, model):
    from services.model_runtime import resolve_model_setting
    cfg = language_config('relation_a', model)
    emb = resolve_model_setting('graph_embedding')
    assert emb.model_name == 'qwen3.7-text-embedding-flash'
    fixtures = Path(__file__).parent/'fixtures'
    prompts = {'a': (fixtures/'layer1_relation_batch_prompt_v4.txt').read_text(),
               'b': (fixtures/'layer1_relation_batch_prompt_v4.txt').read_text(),
               'c': (fixtures/'layer1_relation_adjudicate_v3.txt').read_text()}
    events = {e['id']: {k: e[k] for k in ('id', 'title', 'diary_date', 'points')} for e in source['events']}
    variants = {'previous-points': events}
    new = {}
    outcomes_path = folder/'point-outcomes.json'
    outcomes = {row['event_id']: row for row in read(outcomes_path)} if outcomes_path.exists() else {}
    for key, e in events.items():
        path = folder/'points'/key/'candidate.json'
        if path.exists() and outcomes.get(key, {}).get('passed') and not outcomes[key].get('failed'):
            new[key] = {**e, 'points': read(path)['points']}
    if len(new) == len(events):
        variants['regenerated-points'] = new
    baseline.save(folder/'relation-manifest.json', {
        'provenance': '依据历史实验记录重建独立关系实验；并非已遗失实验脚本的逐字恢复',
        'language_model': cfg.model_name, 'embedding_model': emb.model_name,
        'thinking': True, 'threshold': 0.5, 'top_k': 5,
        'prompt_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()},
        'variants': list(variants), 'production_writes': False,
        'regenerated_group_complete': len(new) == len(events),
        'regenerated_group_excluded_events': [key for key in events if key not in new],
        'transport': '复用原要点脚本call；无显式max_tokens；每阶段至多两次请求；不自动恢复任务',
        'previous_points': '上次实现验收最终候选，含已记录语义问题；不等于旧实验人工核验要点'})
    for name, pool in variants.items():
        out = folder/name
        print('开始独立关系复测：'+name, flush=True)
        try:
            vs = await vectors(emb, pool, out/'vectors.json')
            all_pairs, recall = [], []
            ids = list(pool)
            for number, (a, b) in enumerate(combinations(ids, 2), 1):
                pair = {'pair_id': f'R{number:02}', 'event_a_id': a, 'event_b_id': b}
                all_pairs.append(pair)
                score = max(cosine(x,y) for x in vs[a] for y in vs[b])
                recall.append({**pair, 'similarity': score,
                               'same_day': pool[a]['diary_date']==pool[b]['diary_date']})
            for row in recall:
                if row['same_day']:
                    row['recalled'] = True
                    continue
                current = max((row['event_a_id'], row['event_b_id']), key=lambda i: pool[i]['diary_date'])
                eligible = [r for r in recall if not r['same_day'] and r['similarity'] >= 0.5 and
                            max((r['event_a_id'],r['event_b_id']),key=lambda i: pool[i]['diary_date'])==current]
                eligible.sort(key=lambda r: (-r['similarity'], min(r['event_a_id'],r['event_b_id'])))
                row['recalled'] = row in eligible[:5]
            baseline.save(out/'recall.json', recall)
            # 全6对强制送判，用于区分召回漏检与关系判定错误；正常链路按recalled筛选另计。
            p = payload(all_pairs, pool)
            decisions = {}
            stage_failures = {}
            for role in ('a', 'b'):
                try:
                    data = await baseline.call(cfg, prompts[role], p, out, role,
                        lambda d: validate_result(d, all_pairs, pool))
                    decisions[role] = {r['pair_id']: r for r in data['results']}
                except Exception as error:
                    stage_failures[role] = {'error_type': type(error).__name__, 'error': str(error)[:300]}
                    baseline.save(out/'stage-failures.json', stage_failures)
            if stage_failures:
                # A失败仍执行隔离B，不把无效结果交给C或组装成正式结论。
                raise RuntimeError('独立判定阶段结构失败：'+','.join(stage_failures))
            disagree = [r for r in all_pairs if not equivalent(decisions['a'][r['pair_id']], decisions['b'][r['pair_id']])]
            decisions['c'] = {}
            if disagree:
                cp = payload(disagree, pool)
                cp.pop('pairs')
                cp['disagreements'] = [{'pair': r, 'candidate_1': decisions['a'][r['pair_id']],
                                        'candidate_2': decisions['b'][r['pair_id']]} for r in disagree]
                data = await baseline.call(cfg, prompts['c'], cp, out, 'c',
                    lambda d: validate_result(d, disagree, pool))
                decisions['c'] = {r['pair_id']: r for r in data['results']}
            final = []
            for row in recall:
                key = row['pair_id']
                final.append({**row, 'a': decisions['a'][key], 'b': decisions['b'][key],
                              'final': decisions['c'].get(key, decisions['a'][key]),
                              'adjudicated': key in decisions['c']})
            baseline.save(out/'final.json', final)
            print(json.dumps({'完成': name, 'pairs': len(final), 'recalled':sum(r['recalled'] for r in final)},ensure_ascii=False),flush=True)
        except Exception as error:
            baseline.save(out/'failure.json', {'error_type': type(error).__name__, 'error':str(error)[:300]})
            print(json.dumps({'失败':name,'type':type(error).__name__},ensure_ascii=False),flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--phase', choices=('points','relations'), required=True)
    parser.add_argument('--model', choices=('qwen3.7-flash-2026-07-15','kimi-k3'),
                        default='qwen3.7-flash-2026-07-15')
    parser.add_argument('--optimized', action='store_true', help='使用新版审核协议及正式提取函数，仅保存本地检查点')
    args = parser.parse_args()
    if args.optimized and args.phase == 'relations':
        parser.error('新版召回校准请使用calibrate_layer1_recall.py；此入口只支持新版要点复测')
    folder = args.folder.resolve()
    source = read(folder/'source.json')
    identity = {'model': args.model, 'source_sha256': baseline_hash(source)}
    if args.optimized:
        identity['point_review_protocol'] = 'issues-v2'
    identity_path = folder/'experiment-identity.json'
    if identity_path.exists():
        assert read(identity_path) == identity, '实验目录已有不同模型或样本，须使用新目录'
    baseline.save(identity_path, identity)
    await ((optimized_points if args.optimized else points)(folder, source, args.model) if args.phase == 'points'
           else relations(folder, source, args.model))


if __name__ == '__main__':
    asyncio.run(main())
