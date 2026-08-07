"""百炼 OpenAI 兼容 embedding 客户端封装。

封装对百炼（DashScope）OpenAI 兼容 /embeddings 端点的调用：
- 复用现有 openai SDK（与 ai.py 一致）。
- 模型名与维度由管理端 DB 托管的 EMBEDDING 设置提供（见 services.model_management）。
- 批量调用（单次上限保守取 10），对空文本跳过并以 None 占位保持顺序。
- 出网仅发送待向量化文本，不附带任何用户标识（隐私最小化，决策 12）。

依赖运行环境安装 openai SDK 与 pgvector（后者仅向量存储侧使用）。
"""

import logging
from typing import List, Optional

from openai import OpenAI

from services.model_management import (
    EMBEDDING_DIMENSIONS,
    EmbeddingConfig,
    get_embedding_config,
)

logger = logging.getLogger(__name__)

# 单次批量上限：百炼 / OpenAI 兼容 embeddings 端点通常限制批量条数，保守取 10。
EMBEDDING_BATCH_LIMIT = 10


class EmbeddingClientError(RuntimeError):
    """embedding 调用失败。"""


def embed_texts(
    texts: List[str],
    dimensions: Optional[int] = None,
) -> List[Optional[List[float]]]:
    """批量生成文本 embedding（向量）。

    Args:
        texts: 待向量化文本列表（单行纯文本）。
        dimensions: 维度覆盖；默认取配置维度（1024，与模型及迁移 038 一致）。

    Returns:
        与输入等长的结果列表，每项为一维 float 向量；对应输入为空文本的项为 None，
        以保持与输入顺序一致（便于按 (chunk_type, vector) 回填）。
    """
    dim = dimensions or EMBEDDING_DIMENSIONS

    # 过滤空文本：仅对非空文本发起调用，结果按原顺序回填。
    indexed: List[tuple[int, str]] = []
    for idx, text in enumerate(texts):
        if text and text.strip():
            indexed.append((idx, text.strip()))
    results: List[Optional[List[float]]] = [None] * len(texts)
    if not indexed:
        return results

    config: EmbeddingConfig = get_embedding_config()
    # 每次调用新建客户端（轻量且线程安全）；如需连接复用可改为模块级单例。
    client = OpenAI(api_key=config.api_key, base_url=config.api_base_url)

    for start in range(0, len(indexed), EMBEDDING_BATCH_LIMIT):
        batch = indexed[start : start + EMBEDDING_BATCH_LIMIT]
        batch_indices = [item[0] for item in batch]
        batch_texts = [item[1] for item in batch]
        try:
            resp = client.embeddings.create(
                model=config.model_name,
                input=batch_texts,
                dimensions=dim,
                encoding_format="float",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("embedding 调用失败 model=%s dim=%s", config.model_name, dim)
            raise EmbeddingClientError(f"embedding 调用失败: {exc}") from exc

        # OpenAI 兼容接口按输入顺序返回；逐条回填到原索引位置。
        data_list = list(resp.data)
        if len(data_list) != len(batch_indices):
            raise EmbeddingClientError(
                f"embedding 返回条数({len(data_list)})与请求({len(batch_indices)})不一致"
            )
        for i, data in enumerate(data_list):
            results[batch_indices[i]] = list(data.embedding)

    return results
