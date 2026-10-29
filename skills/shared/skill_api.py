"""Skill 的 HTTP 数据适配；默认数据库模式，API 模式无需后端依赖。"""
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ApiError(ValueError):
    pass


def api_enabled():
    mode = os.environ.get('DIARY_DATA_MODE', 'db')
    if mode not in {'db', 'api'}:
        raise ApiError('DIARY_DATA_MODE 只支持 db 或 api')
    return mode == 'api'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 不将携带 Token 和日记内容的请求重定向到其他地址。
        return None


def request(stage, action, params=None, files=None):
    base = os.environ.get('DIARY_API_BASE_URL', '').rstrip('/')
    token = os.environ.get('DIARY_API_TOKEN', '')
    parsed = urlsplit(base)
    if parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError('请配置有效的 DIARY_API_BASE_URL，例如 https://应用域名/diary/api')
    if not token:
        raise ApiError('缺少 DIARY_API_TOKEN')
    payload = json.dumps({'params': params or {}, 'files': files or {}}, ensure_ascii=False, default=str).encode()
    req = Request(base + '/skills/' + stage + '/' + action, data=payload,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect).open(req, timeout=920) as response:
            return json.load(response)
    except HTTPError as error:
        detail = ''
        try:
            response = json.load(error)
            if isinstance(response.get('detail'), str): detail = '：' + response['detail']
        except (ValueError, OSError):
            pass
        raise ApiError(f'接口返回 HTTP {error.code}' + detail + '；保存失败先查询状态再恢复') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ApiError('接口请求未完成；请核对连接，保存失败须先查询状态再恢复') from None


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def collect_files(packet, labels=('source_file', 'markdown', 'clarifications')):
    files = {}
    for label in labels:
        if label in packet:
            path = Path(packet[label]['path']).resolve()
            files[str(path)] = path.read_bytes().decode('utf-8')
    return files


def remote_document(stage, args, p):
    action = args.command
    files = {}
    if action in {'export', 'prepare'} and args.output.exists():
        raise ApiError('输出文件已存在，请使用新文件名')
    if action == 'prepare':
        for key in ('source', 'markdown', 'clarifications'):
            if hasattr(args, key):
                path = Path(getattr(args, key)).resolve()
                p[key] = str(path)
                files[str(path)] = path.read_bytes().decode('utf-8')
    if action == 'save':
        p['packet'] = json.loads(args.packet.read_text(encoding='utf-8'))
        files = collect_files(p['packet'])
    result = request(stage, action, p, files)
    if action in {'export', 'prepare'}:
        content = result.pop('file' if action == 'export' else 'packet')
        write_json(args.output, content)
        result['path' if action == 'export' else 'packet'] = str(args.output)
        if action == 'export':
            result['source'] = content['source']
            if 'capabilities' in content: result['capabilities'] = content['capabilities']
    return result


def remote_points(stage, args, p):
    action = args.command
    files = {}
    if action == 'prepare':
        if args.output.exists(): raise ApiError('入库包已存在，请使用新文件名')
        if stage == 'supplement':
            p['inputs'] = json.loads(args.inputs.read_text(encoding='utf-8'))
            for item in p['inputs']:
                for key in ('source', 'markdown'):
                    path = Path(item[key]).resolve()
                    item[key] = str(path)
                    files[str(path)] = path.read_bytes().decode('utf-8')
        else:
            for key in ('source', 'markdown'):
                path = Path(getattr(args, key)).resolve()
                p[key] = str(path)
                files[str(path)] = path.read_bytes().decode('utf-8')
    elif action in {'save', 'status'}:
        p['packet'] = json.loads(args.packet.read_text(encoding='utf-8'))
        if action != 'status':
            if stage == 'supplement':
                for item in p['packet']['items']: files.update(collect_files(item))
            else:
                files = collect_files(p['packet'])
    result = request(stage, action, p, files)
    if action == 'prepare':
        write_json(args.output, result.pop('packet'))
        result['packet'] = str(args.output)
    return result


def remote_relations(args, p):
    import workflow as workflow_module
    action = args.command
    if action in {'read', 'record', 'status', 'check', 'render', 'convert'}:
        return None
    if action == 'prepare':
        snapshot = request('relations', action, p)['snapshot']
        folder = workflow_module.write_package(snapshot)
        return {'run_dir': str(folder), 'pairs': len(snapshot['pairs']), 'events': len(snapshot['events']),
                'package_sha256': snapshot['package_sha256'], 'history_mode': snapshot['history_mode']}
    if action == 'verify':
        with workflow_module.local_lock(args.run_dir):
            snapshot, _ = workflow_module.load_package(args.run_dir)
            receipt = args.run_dir / 'verification.json'
            receipt.unlink(missing_ok=True)
            result = request('relations', 'verify', {'snapshot': snapshot})
            workflow_module.write_json(receipt, result)
            return result
    if action == 'prepare-storage':
        from storage import build_packet
        packet = build_packet(args.run_dir, args.username, args.markdown)
        if args.output is None:
            args.output = args.run_dir / ('入库包-事件关系-' + packet['storage_sha256'][:16] + '.json')
        if args.output.exists(): raise ApiError('入库包已存在，请使用新文件名')
        p['packet'] = packet
        result = request('relations', 'preflight', p)
        write_json(args.output, packet)
        return {**result, 'packet_file': str(args.output)}
    if action in {'save', 'storage-status'}:
        p['packet'] = json.loads(args.packet.read_text(encoding='utf-8'))
        # 当前磁盘稿与实际确认包绑定；状态查询不依赖旧磁盘文件。
        if action == 'save' and 'draft' in p['packet']:
            draft = p['packet']['draft']
            if Path(draft['path']).read_text(encoding='utf-8') != draft['content']:
                raise ApiError('关系稿已变化，请重新预检并确认当前稿')
    return request('relations', action, p)


def maybe_remote(stage, args):
    """在解析 CLI 参数后调用；本地模式保持原执行路径。"""
    try:
        if not api_enabled(): return
        # 网络操作前固定本地绝对路径，接口请求不携带 backend-dir。
        for key, value in vars(args).copy().items():
            if isinstance(value, Path): setattr(args, key, value.resolve())
        p = {k: v for k, v in vars(args).items()
             if k not in {'backend_dir', 'output', 'command', 'run_dir', 'packet', 'inputs'}}
        action = getattr(args, 'command', 'status' if stage == 'workflow' else 'export')
        if stage in {'organize', 'analyze'}: result = remote_document(stage, args, p)
        elif stage in {'points', 'supplement'}: result = remote_points(stage, args, p)
        elif stage == 'relations':
            result = remote_relations(args, p)
            if result is None: return
        elif stage == 'people':
            if args.output.exists(): raise ApiError('输出文件已存在，请使用新文件名')
            content = request(stage, action, p)['file']
            write_json(args.output, content)
            result = {'path': str(args.output), 'people': len(content['people']), 'user_id': content['user_id']}
        elif stage == 'points-source':
            result = request(stage, action, p)
            if action == 'export':
                from export_events import write_run
                source = result['source']
                folder = write_run(source)
                result = {'run_dir': str(folder), 'events': len(source['events']),
                          'excluded': len(source['excluded_events']), 'source_sha256': source['source_sha256']}
        else: result = request(stage, action, p)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except ApiError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, KeyError, TypeError, OSError):
        print('接口操作未完成；请核对配置、当前稿和来源；保存失败先查询状态再恢复。未输出认证信息', file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)
