"""迁移 036 回填校验脚本：校验 diary_events.search_text 的非空比例与抽样命中。

用途：
- 迁移 036 为存量数据补齐 search_text 后，运行本脚本确认回填完整、检索可工作。
- 统计 search_text 非空比例；对样本事件抽取标题片段做 ILIKE 自匹配，验证聚合文本
  至少包含事件自身字段；并演示 pg_trgm 的 similarity 可用于排序。

前置条件：
- search_text 列（迁移 036）与 pg_trgm 扩展已就绪；否则脚本给出明确指引并以非零码退出。

用法：
    python -m scripts.verify_search_backfill [--sample 20] [--min-ratio 0.9]
"""

import argparse
import json
import sys

from sqlalchemy import text

from database import SessionLocal, engine


def _ensure_extension_and_column():
    """校验 pg_trgm 与 search_text 列可用，否则抛出可读错误。"""
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT similarity('abc', 'abc')"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"[FAIL] 未启用 pg_trgm 扩展（统一搜索方案 B 依赖它）：{exc}\n"
                "       请由 DBA 执行：CREATE EXTENSION IF NOT EXISTS pg_trgm;"
            )
        try:
            conn.execute(text("SELECT search_text FROM diary_events LIMIT 0"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"[FAIL] diary_events.search_text 列不存在（需先执行迁移 036）：{exc}"
            )


def verify(sample: int = 20, min_ratio: float = 0.9):
    _ensure_extension_and_column()
    db = SessionLocal()
    try:
        # 注意：SQLAlchemy 2.0 不允许把裸 TextClause 直接当 select_from，
        # 统一改用 db.execute(text(...)) 的形式，避免 ArgumentError。
        total = db.execute(text("SELECT COUNT(*) FROM diary_events")).scalar() or 0
        populated = db.execute(text(
            "SELECT COUNT(*) FROM diary_events "
            "WHERE search_text IS NOT NULL AND search_text <> ''"
        )).scalar() or 0
        ratio = (populated / total) if total else 0.0

        print(f"事件总数            : {total}")
        print(f"search_text 非空数  : {populated}")
        print(f"非空比例            : {ratio:.2%}")

        # 抽样自匹配：取样本事件的标题片段，确认聚合文本至少包含事件自身字段。
        rows = db.execute(text(
            "SELECT id, event_title, search_text FROM diary_events "
            "WHERE search_text IS NOT NULL AND search_text <> '' LIMIT :n"
        ), {"n": sample}).fetchall()
        self_match = 0
        checked = 0
        samples = []
        for row in rows:
            event_id, title, search_text = row[0], row[1], row[2]
            if not title or len(title) < 2:
                continue
            checked += 1
            token = title[:2]
            hit = db.execute(text(
                "SELECT COUNT(*) FROM diary_events WHERE id = :eid AND search_text ILIKE :pat"
            ), {"eid": str(event_id), "pat": f"%{token}%"}).scalar() or 0
            if hit >= 1:
                self_match += 1
            if len(samples) < 5:
                samples.append({"id": str(event_id), "token": token, "self_match": hit >= 1})

        self_ratio = (self_match / checked) if checked else 0.0
        print(f"抽样自匹配检查数    : {checked}")
        print(f"自匹配成功数        : {self_match} ({self_ratio:.2%})")
        if samples:
            print("抽样示例（前 5 条）:")
            print(json.dumps(samples, ensure_ascii=False, indent=2))

        # 综合判定
        ok = ratio >= min_ratio and self_ratio >= min_ratio
        if ok:
            print(f"\n[PASS] search_text 回填完整（非空比例 {ratio:.2%}，自匹配 {self_ratio:.2%}）。")
            return 0
        print(
            f"\n[WARN] 回填不完整：非空比例 {ratio:.2%}（阈值 {min_ratio:.2%}），"
            f"自匹配 {self_ratio:.2%}。请重新执行迁移 037 回填。",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="校验 diary_events.search_text 回填")
    parser.add_argument("--sample", type=int, default=20, help="自匹配抽样事件数")
    parser.add_argument("--min-ratio", type=float, default=0.9, help="非空/自匹配最低接受比例")
    args = parser.parse_args()
    sys.exit(verify(sample=args.sample, min_ratio=args.min_ratio))


if __name__ == "__main__":
    main()
