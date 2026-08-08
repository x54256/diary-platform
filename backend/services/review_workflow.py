"""定期回顾执行入口：业务表中的任务状态与每日产物是断点恢复真相。"""

from __future__ import annotations

import uuid
from services.review_generation import execute_review_task


async def execute_review_graph(task_id: uuid.UUID, run_token: uuid.UUID) -> None:
    """直接从业务表恢复回顾任务。"""
    await execute_review_task(task_id, run_token)
