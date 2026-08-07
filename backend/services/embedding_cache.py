"""进程内查询 embedding TTL 缓存（无新依赖，轻量 LRU + TTL）。

用途：搜索查询的 embedding 向量计算代价较高（一次百炼 API 调用）。同一查询在短时间内
（默认 600s）重复出现时直接命中缓存，降低出网与耗时。仅缓存「查询文本 -> 向量」，
不缓存任何用户标识（隐私最小化，决策 8/12）。

实现：OrderedDict 维护插入顺序实现 LRU；字典值为 (时间戳, 向量)。访问时校验 TTL，
过期则剔除；容量上限保护（默认 1024 条）防止内存无限增长。线程安全由模块级锁保证
（FastAPI 多 worker 下每个进程各自一份，足够覆盖单进程内的重复查询）。
"""

import threading
import time
from collections import OrderedDict
from typing import List, Optional

# 查询向量缓存 TTL（秒）。决策 8：默认 600s。
QUERY_EMBEDDING_TTL_SECONDS = 600
# 缓存条目上限保护（防止内存无限增长）。
QUERY_EMBEDDING_MAX_ENTRIES = 1024

_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[float, List[float]]]" = OrderedDict()


def _normalize_key(q: str) -> str:
    """统一缓存键：去除首尾空白（与语义匹配口径一致）。"""
    return (q or "").strip()


def get_cached_query_embedding(q: str) -> Optional[List[float]]:
    """读取查询向量缓存；未命中或已过期返回 None。"""
    key = _normalize_key(q)
    if not key:
        return None
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, vec = entry
        if time.monotonic() - ts > QUERY_EMBEDDING_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        # LRU 触活：移到末尾表示最近使用。
        _cache.move_to_end(key)
        return vec


def cache_query_embedding(q: str, vec: List[float]) -> None:
    """写入查询向量缓存；空键或空向量直接忽略。"""
    key = _normalize_key(q)
    if not key or vec is None:
        return
    with _lock:
        _cache[key] = (time.monotonic(), vec)
        _cache.move_to_end(key)
        while len(_cache) > QUERY_EMBEDDING_MAX_ENTRIES:
            _cache.popitem(last=False)
