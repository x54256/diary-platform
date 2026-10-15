"""加载清理后由 CPython 3.11 字节码恢复的历史实验脚本。"""

import hashlib
import importlib.util
import marshal
import sys
from pathlib import Path


BYTECODE_DIR = Path(__file__).with_name("bytecode")


def restore(namespace: dict, module_name: str, expected_sha256: str) -> None:
    """在原源码路径语境中执行冻结字节码，并导出其公开成员。"""
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("历史实验字节码必须使用 Python 3.11 运行")

    path = BYTECODE_DIR / f"{module_name}.cpython-311.pyc"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError(f"历史实验字节码指纹不一致: {module_name}")
    if raw[:4] != importlib.util.MAGIC_NUMBER:
        raise RuntimeError(f"历史实验字节码版本不兼容: {module_name}")

    recovered = {
        "__name__": f"scripts._recovered_{module_name}",
        "__package__": "scripts",
        # 冻结代码通过 __file__ 计算仓库根目录，保留清理前的源码位置语义。
        "__file__": str(Path(__file__).parent.parent / f"{module_name}.py"),
        "__builtins__": __builtins__,
    }
    exec(marshal.loads(raw[16:]), recovered)
    for name, value in recovered.items():
        if name not in {"__name__", "__package__", "__file__", "__builtins__"}:
            namespace[name] = value
