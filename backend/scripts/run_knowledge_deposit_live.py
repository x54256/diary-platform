"""使用指定模型对一篇日记执行正式知识沉淀，并恢复原知识模型配置。

示例：
  PYTHONPATH=. venv/bin/python scripts/run_knowledge_deposit_live.py \
    --diary-id 567d5606-f5f4-49c6-9d57-933bb72045a9 \
    --model deepseek-v4-pro \
    --delete-existing

--delete-existing 会删除该日记已有的正式知识事件和成功沉淀记录，
使其可以重新沉淀；历史任务审计记录保持不变。
"""

import argparse
import asyncio
import json
from datetime import datetime
from uuid import UUID

from database import SessionLocal
from models.diary import Diary, DiaryOrganized
from models.knowledge import KnowledgeAtomicEvent, KnowledgeDeposit, KnowledgeTask
from models.model_config import ChannelModel, ModelSetting
from services.model_management import ModelConfigError, validate_thinking_choice
from services.knowledge_tasks import knowledge_task_manager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行正式知识沉淀实时测试")
    parser.add_argument("--diary-id", required=True, type=UUID, help="待沉淀日记 UUID")
    parser.add_argument("--model", required=True, help="已启用的语言模型名称")
    parser.add_argument("--channel", help="指定模型所属渠道名称；同名模型存在多个渠道时必须传入")
    parser.add_argument(
        "--delete-existing",
        action="store_true",
        help="删除该日记已有正式知识事件和成功沉淀记录后重新测试",
    )
    parser.add_argument("--poll-seconds", type=float, default=3, help="任务状态轮询间隔")
    parser.add_argument("--timeout-seconds", type=int, default=720, help="等待任务终态的超时秒数")
    return parser.parse_args()


def create_task(args: argparse.Namespace) -> tuple[UUID, UUID]:
    db = SessionLocal()
    try:
        diary = db.query(Diary).filter(
            Diary.id == args.diary_id,
            Diary.deleted_at.is_(None),
        ).with_for_update().first()
        if not diary:
            raise RuntimeError("日记不存在")

        active = db.query(KnowledgeTask).filter(
            KnowledgeTask.diary_id == diary.id,
            KnowledgeTask.status.in_(("QUEUED", "RUNNING")),
        ).first()
        if active:
            raise RuntimeError(f"日记已有进行中的知识任务: {active.id}")

        setting = db.query(ModelSetting).filter(
            ModelSetting.setting_key == "knowledge",
        ).with_for_update().first()
        target_query = db.query(ChannelModel).filter(
            ChannelModel.enabled.is_(True),
            ChannelModel.model.has(model_name=args.model),
        )
        if args.channel:
            target_query = target_query.filter(ChannelModel.channel.has(name=args.channel))
        targets = target_query.all()
        if not setting:
            raise RuntimeError("知识沉淀基础模型未配置")
        if not targets:
            raise RuntimeError(f"指定模型不可用: {args.model}")
        if len(targets) > 1:
            raise RuntimeError(f"模型 {args.model} 存在多个可用渠道，请通过 --channel 指定")
        target = targets[0]
        if not target.model.enabled or not target.channel.enabled:
            raise RuntimeError(f"指定模型不可用: {args.model}")
        try:
            validate_thinking_choice(target, bool(setting.thinking_enabled), "知识沉淀")
        except ModelConfigError as exc:
            raise RuntimeError(f"指定模型运行配置无效: {exc}") from exc

        organized = db.query(DiaryOrganized).filter(DiaryOrganized.diary_id == diary.id).first()
        if not organized:
            raise RuntimeError("结构化来源不存在")

        deposit = db.query(KnowledgeDeposit).filter(KnowledgeDeposit.diary_id == diary.id).first()
        if deposit:
            if not args.delete_existing:
                raise RuntimeError("日记已有成功沉淀；如需重新测试，请显式传入 --delete-existing")
            deleted_events = db.query(KnowledgeAtomicEvent).filter(
                KnowledgeAtomicEvent.diary_id == diary.id,
            ).delete(synchronize_session=False)
            deleted_deposits = db.query(KnowledgeDeposit).filter(
                KnowledgeDeposit.diary_id == diary.id,
            ).delete(synchronize_session=False)
            print(json.dumps({
                "deleted_knowledge_events": deleted_events,
                "deleted_knowledge_deposits": deleted_deposits,
            }, ensure_ascii=False))

        original_model_id = setting.channel_model_id
        setting.channel_model_id = target.id
        setting.updated_at = datetime.utcnow()
        task = KnowledgeTask(
            user_id=diary.user_id,
            diary_id=diary.id,
            source_diary_organized_id=organized.id,
            source_structured_revision=organized.structured_revision,
            status="QUEUED",
            available_at=datetime.utcnow(),
        )
        db.add(task)
        db.commit()
        print(json.dumps({
            "task_id": str(task.id),
            "model": args.model,
            "channel": target.channel.name,
            "status": "QUEUED",
        }, ensure_ascii=False))
        return task.id, original_model_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def restore_model(original_model_id: UUID) -> None:
    db = SessionLocal()
    try:
        setting = db.query(ModelSetting).filter(
            ModelSetting.setting_key == "knowledge",
        ).with_for_update().first()
        if not setting:
            raise RuntimeError("无法恢复知识沉淀模型：基础配置不存在")
        setting.channel_model_id = original_model_id
        setting.updated_at = datetime.utcnow()
        db.commit()
        print(json.dumps({"knowledge_model_restored": True}, ensure_ascii=False))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def wait_for_task(task_id: UUID, args: argparse.Namespace) -> dict:
    await knowledge_task_manager.start()
    knowledge_task_manager.wake()
    try:
        attempts = int(args.timeout_seconds / args.poll_seconds)
        for _ in range(attempts):
            await asyncio.sleep(args.poll_seconds)
            db = SessionLocal()
            try:
                task = db.query(KnowledgeTask).filter(KnowledgeTask.id == task_id).first()
                if not task:
                    raise RuntimeError("知识任务不存在")
                if task.status in ("SUCCEEDED", "FAILED"):
                    return {
                        "task_id": str(task.id),
                        "status": task.status,
                        "step": task.current_step,
                        "error_code": task.error_code,
                        "error_message": task.error_message,
                    }
            finally:
                db.close()
        raise TimeoutError(f"任务在 {args.timeout_seconds} 秒内未结束")
    finally:
        await knowledge_task_manager.stop()


async def main() -> None:
    args = parse_args()
    task_id, original_model_id = create_task(args)
    try:
        result = await wait_for_task(task_id, args)
    finally:
        restore_model(original_model_id)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "SUCCEEDED":
        raise RuntimeError(f"知识沉淀失败: {result['error_code'] or result['error_message']}")


if __name__ == "__main__":
    asyncio.run(main())
