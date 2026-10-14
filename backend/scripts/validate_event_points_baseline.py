"""最终方案验证入口：生成、审核修正合并、独立复核；实测仅保存本地候选。"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = Path(__file__).parent / 'fixtures/event_point_baseline.json'
EVENT_ID = 'a7c66da7-00f5-41e5-af90-04abd8c6cb21'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def units(event):
    rows = []
    for paragraph in event['paragraphs']:
        for sentence in re.findall(r'[^。！？]+[。！？]?', paragraph['text']):
            if sentence.strip():
                rows.append({'id': len(rows) + 1, 'paragraph_id': paragraph['id'], 'text': sentence})
    return rows


def validate_points(data, event):
    assert set(data) == {'title', 'points'} and data['title'] == event['title'], '标题或字段不一致'
    points = data['points']
    assert isinstance(points, list) and points, '要点数组为空'
    assert [p['no'] for p in points] == list(range(1, len(points) + 1)), '序号不连续'
    for point in points:
        assert set(point) == {'no', 'summary', 'detail'}, '要点字段不一致'
        assert all(isinstance(point[k], str) and point[k].strip() for k in ('summary', 'detail')), '要点内容为空'


def validate_review(data, event, candidate):
    assert [x['source_unit_id'] for x in data['source_checks']] == [x['id'] for x in units(event)], '原句检查不完整'
    assert all(x['comparison'].strip() for x in data['source_checks']), '缺少原句比较'
    assert [x['no'] for x in data['checks']] == [p['no'] for p in candidate['points']], '要点检查不完整'
    for check, point in zip(data['checks'], candidate['points']):
        for issue in check['issues']:
            assert issue['field'] in ('summary', 'detail'), '问题字段不合法'
            assert issue['candidate_quote'] and issue['candidate_quote'] in point[issue['field']], '候选引用不真实'
            assert type(issue['source_index']) is int and 1 <= issue['source_index'] <= len(data['source_checks']), '原句编号越界'
            assert issue['difference'].strip() and issue['repair'].strip(), '问题说明不完整'
        for field in ('summary', 'detail'):
            assert type(check[field + '_ok']) is bool, '通过状态类型不合法'
            assert check[field + '_ok'] == (not any(i['field'] == field for i in check['issues'])), '通过状态与问题列表矛盾'


async def call(cfg, prompt, payload, folder, label, validator, max_attempts=2):
    import httpx
    from services.model_runtime import resolve_thinking_payload
    path = folder / (label + '.json')
    request = {'system': prompt, 'payload': payload}
    record = json.loads(path.read_text()) if path.exists() else {'request': request, 'attempts': []}
    assert record['request'] == request, '缓存请求与当前输入不同'
    if 'data' in record:
        validator(record['data'])
        return record['data']
    assert max_attempts >= 1
    for attempt in range(max_attempts):
        if attempt < len(record['attempts']):
            item = record['attempts'][attempt]
            if 'raw' not in item:
                raise RuntimeError('该阶段已有服务失败记录；保留原记录，用新输出目录重试')
            raw = item['raw']
        else:
            messages = [{'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
            if attempt:
                previous = record['attempts'][attempt - 1]
                messages.append({'role': 'user', 'content': '前次结构错误：' + previous['structure_error']
                                 + '。重新完整输出，不改结论以迎合结构。前次响应：' + previous['raw']})
            body = {'model': cfg.model_name, 'response_format': {'type': 'json_object'}, 'messages': messages}
            if cfg.model_name == 'qwen3.8-max':
                body['temperature'] = 0.2
            body.update(resolve_thinking_payload(cfg) or {})
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=600) as client:
                    response = await client.post(cfg.api_base_url + '/chat/completions',
                                                 headers={'Authorization': 'Bearer ' + cfg.api_key}, json=body)
            except httpx.HTTPError as exc:
                record['attempts'].append({'transport_error': type(exc).__name__})
                save(path, record)
                raise RuntimeError('模型网络请求失败，类型已记录') from None
            if response.status_code != 200:
                failure = {'http_status': response.status_code}
                try:
                    error = response.json().get('error', {})
                    if isinstance(error, dict):
                        for key in ('code', 'type', 'message'):
                            if isinstance(error.get(key), str):
                                failure['provider_' + key] = error[key].replace(cfg.api_key, '[已隐藏]')[:1000]
                except (ValueError, AttributeError):
                    pass
                record['attempts'].append(failure)
                save(path, record)
                raise RuntimeError('模型HTTP状态 ' + str(response.status_code))
            result = response.json()
            raw = result['choices'][0]['message']['content']
            item = {'raw': raw, 'seconds': round(time.monotonic() - started, 2),
                    'model': cfg.model_name, 'usage': result.get('usage'),
                    'reasoning_chars': len(result['choices'][0]['message'].get('reasoning_content') or '')}
            record['attempts'].append(item)
            save(path, record)
            print(json.dumps({'stage': label, 'attempt': attempt + 1}, ensure_ascii=False), flush=True)
        try:
            data = json.loads(raw)
            validator(data)
            record['data'] = data
            save(path, record)
            return data
        except (AssertionError, KeyError, TypeError, ValueError) as exc:
            item['structure_error'] = str(exc)
            save(path, record)
    raise RuntimeError('结构校验失败，已达到本次允许的请求次数')


def validate_combined(data, event, original):
    assert set(data) == {'review', 'candidate'}, '合并输出字段不一致'
    validate_review(data['review'], event, original)
    validate_points(data['candidate'], event)
    if not any(c['issues'] for c in data['review']['checks']):
        assert data['candidate'] == original, '未发现问题却修改候选'


async def run_combined(cfg, prompts, source, event, candidate, folder):
    for iteration in (1, 2):
        original = candidate
        data = await call(cfg, prompts['combined'], {'source': source, 'candidate': original}, folder,
                          f'combined-{iteration}', lambda d: validate_combined(d, event, original))
        candidate = data['candidate']
        if not any(c['issues'] for c in data['review']['checks']):
            passed = True
        else:
            review = await call(cfg, prompts['review'], {'source': source, 'candidate': candidate}, folder,
                                f'review-{iteration}', lambda d: validate_review(d, event, candidate))
            passed = not any(c['issues'] for c in review['checks'])
        save(folder / 'candidate.json', candidate)
        save(folder / 'model-status.json', {'passed': passed, 'iterations': iteration})
        if passed:
            break
    return {'passed': passed, 'iterations': iteration}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--model', choices=('deepseek-v4-flash-0731',))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--event-id', default=EVENT_ID)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    baseline = json.loads(BASELINE_FILE.read_text())
    assert baseline['scheme'] == 'B' and baseline['repair_limit'] == 2
    assert baseline['pipeline'] == 'generate_then_combined_review_repair_then_independent_review'
    args.model = args.model or baseline['default_model']
    prompts = baseline['prompts']
    for key, prompt in prompts.items():
        assert hashlib.sha256(prompt.encode()).hexdigest() == baseline['prompt_sha256'][key], '提示快照指纹不一致'
    if args.preflight:
        source_units = None
        if args.source:
            event = next(x for x in json.loads(args.source.read_text())['events'] if x['id'] == args.event_id)
            source_units = len(units(event))
        print(json.dumps({'scheme': 'B', 'preflight_passed': True,
                          'source_units': source_units, 'model_called': False,
                          'version': baseline['version'], 'pipeline': baseline['pipeline'],
                          'default_model': args.model}, ensure_ascii=False))
        return
    if not args.source:
        parser.error('实测须通过 --source 指定输入文件')
    event = next(x for x in json.loads(args.source.read_text())['events'] if x['id'] == args.event_id)
    payload = {'title': event['title'], 'paragraphs': event['paragraphs']}
    source = {**payload, 'source_units': units(event)}
    if not args.out:
        parser.error('实测须明确指定新的 --out 输出目录')
    from services.model_runtime import resolve_model_setting
    try:
        resolved = resolve_model_setting('knowledge', 'knowledge_event_extract')
    except Exception as exc:
        raise RuntimeError('只读模型配置加载失败：' + type(exc).__name__) from None
    cfg = replace(resolved, model_name=args.model, reasoning_mode='switchable', thinking_enabled=True,
                  thinkmode={'disabled': {'enable_thinking': False},
                             'enabled': {'enable_thinking': True}})
    assert urlparse(cfg.api_base_url).hostname == baseline['channel_host'], '模型主机与最终方案不同'
    folder = args.out.resolve()
    manifest = {'scheme': 'B', 'version': baseline['version'], 'pipeline': baseline['pipeline'],
                'model': args.model, 'settings': baseline['model_settings'][args.model],
                'prompt_sha256': baseline['prompt_sha256'], 'event_id': event['id'], 'repair_limit': 2,
                'source_sha256': hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()}
    if folder.exists() and any(folder.iterdir()):
        assert (folder / 'manifest.json').exists() and json.loads((folder / 'manifest.json').read_text()) == manifest, '已有目录输入不同'
    save(folder / 'manifest.json', manifest)
    candidate = await call(cfg, prompts['generate'], payload, folder, 'generate', lambda d: validate_points(d, event))
    await run_combined(cfg, prompts, source, event, candidate, folder)


if __name__ == '__main__':
    asyncio.run(main())
