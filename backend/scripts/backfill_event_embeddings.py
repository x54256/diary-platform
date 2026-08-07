"""迁移 038 存量事件 embedding 回填脚本（按需执行，非应用启动自动运行）。

用途：
- 对「有检索内容（search_text 非空）但缺失语义分块」的事件补算 embedding，
  使其可被语义分支召回。增量同步（organize/analyze/更新）已覆盖新建与变更事件，
  本脚本用于补全历史 / 失败遗漏。
- 收敛性：仅处理有 search_text 却无 chunk 的事件；补算后写入 chunk，下次不再选中。
  空内容（search_text 为空）事件不参与（关键词分支也检索不到，无需向量）。

前置条件：
- pgvector 扩展与 event_embedding_chunks 表已就绪（迁移 038）。
- 管理端已配置 EMBEDDING 模型设置（否则每个事件同步失败并跳过）。

用法：
    python -m scripts.backfill_event_embeddings [--batch 200] [--limit 1000] [--dry-run]
"""

import argparse
import sys

from sqlalchemy import text

from database import SessionLocal, engine
from services.embedding_sync import sync_event_embeddings


def _ensure_extension_and_table() -> None:
    """校验 pgvector 与 event_embedding_chunks 表可用，否则给出可读错误并退出。"""
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT '[1,2,3]'::vector"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"[FAIL] 未启用 pgvector 扩展（语义检索依赖）：{exc}\n"
                "       请由 DBA 执行：CREATE EXTENSION IF NOT EXISTS vector;"
            )
        try:
            conn.execute(text("SELECT id FROM event_embedding_chunks LIMIT 0"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"[FAIL] event_embedding_chunks 表不存在（需先执行迁移 038）：{exc}"
            )


def _find_missing_event_ids(limit: int) -> list:
    """返回有 search_text 但无语义分块的事件 ID 列表。"""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT de.id FROM diary_events de
                LEFT JOIN event_embedding_chunks eec ON eec.event_id = de.id
                WHERE eec.id IS NULL AND de.search_text IS NOT NULL AND de.search_text <> ''
                ORDER BY de.updated_at
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
    return [row[0] for row in rows]


def backfill(batch: int = 200, limit: int | None = None, dry_run: bool = False) -> int:
    _ensure_extension_and_table()
    db = SessionLocal()
    try:
        event_ids = _find_missing_event_ids(limit if limit else 1_000_000)
        total = len(event_ids)
        print(f"待回填事件数：{total}")
        if dry_run:
            print("[DRY-RUN] 未实际写入。")
            return 0

        done = 0
        for i, event_id in enumerate(event_ids, start=1):
            try:
                sync_event_embeddings(db, event_id)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"[WARN] 事件 {event_id} 同步失败：{exc}")
                continue
            done += 1
            if i % batch == 0:
                db.commit()
                print(f"进度 {i}/{total}")
        db.commit()
        print(f"\n[PASS] 回填完成，成功处理 {done}/{total} 个事件。")
        return 0
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="回填事件 embedding 语义分块")
    parser.add_argument("--batch", type=int, default=200, help="每批提交数量")
    parser.add_argument("--limit", type=int, default=None, help="最大处理事件数（默认全部）")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()
    sys.exit(backfill(batch=args.batch, limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
