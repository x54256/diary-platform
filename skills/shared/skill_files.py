"""本地读取文件；接口执行时仅从本次上传内容读取业务文件。"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_uploaded = ContextVar('skill_uploaded_files', default=None)
_CODE_ROOT = Path(__file__).resolve().parents[1]


def read_bytes(path):
    files = _uploaded.get()
    key = str(Path(path).resolve())
    if files is None:
        return Path(path).read_bytes()
    # Skill 自身的指纹使用服务端随版本部署的代码，上传内容不能覆盖它。
    resolved = Path(key)
    if resolved.is_relative_to(_CODE_ROOT) and resolved.is_file() and resolved.suffix in {'.py', '.md', '.json'}:
        return resolved.read_bytes()
    if key in files:
        return files[key].encode('utf-8')
    raise ValueError('缺少本次请求的来源或稿件文件')


def read_text(path):
    return read_bytes(path).decode('utf-8')


@contextmanager
def uploaded_files(files):
    token = _uploaded.set(files)
    try:
        yield
    finally:
        _uploaded.reset(token)
