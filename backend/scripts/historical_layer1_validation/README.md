# 第一层事件要点与关系识别历史实验脚本

本目录保存最终方案确认阶段使用的完整历史验证流程：

- `validate_event_points_baseline.py`：事件要点生成、审核修正合并和独立复核。
- `validate_layer1_full.py`：串联事件要点、向量生成、候选检索和关系识别的分阶段流程。
- `validate_layer1_semantic_only.py`：纯语义相似度候选检索。
- `validate_layer1_blind_verify.py`：A/B 独立判断与 C 分歧裁决。
- `validate_layer1_relation_final.py`：最终关系方案入口，固定 A=v4、B=v3、C=v3。
- `validate_layer1_relations_0826.py`：早期 08-26 关系识别实验。

在 `backend` 目录使用项目 Python 3.11 环境运行，例如：

```bash
venv/bin/python -m scripts.historical_layer1_validation.validate_layer1_relation_final
```

`bytecode/` 中的 `.pyc` 是 2026-10-14 清理实验文件后仍保留在 `backend/scripts/__pycache__` 中的 CPython 3.11 字节码副本，用于恢复当时尚未提交到 Git 的关系实验脚本。

| 模块 | SHA-256 |
| --- | --- |
| `validate_layer1_blind_verify.cpython-311.pyc` | `67abc7f60d568d233564634b41a2989dc7f87470d18549e88660785b5594c798` |
| `validate_layer1_semantic_only.cpython-311.pyc` | `ad9ecfc8023107b05d57a871a73e805a7d2e886593425d4e5d488217dd262c3f` |
| `validate_layer1_full.cpython-311.pyc` | `bcab958e367b340fa7d59c02bd2370d66f7980afd70bab7701a530e96ab1029e` |
| `validate_layer1_relations_0826.cpython-311.pyc` | `0d754faafa102692de5d25aa047a88d124de2302dc7590d38e1b94e20b4a5605` |

`validate_layer1_relation_final.py` 已根据其 616 字节原源码对应字节码逐条恢复。其固定配置为 A 使用 v4、B 使用 v3、C 使用 v3。

其余四个模块通过 `_historical_pyc.py` 在原源码路径语境中执行冻结字节码，保证运行逻辑来自清理前字节码，而不是按当前设计重新实现。它们必须使用项目的 Python 3.11 环境运行，也仍依赖当时的冻结输入及实验目录。
