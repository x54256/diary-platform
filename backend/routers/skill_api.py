"""固定 Token 的 Skill 数据接口，用户身份由服务端配置绑定。"""
import hmac
import json
from pathlib import Path
import subprocess
import sys

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from config import settings
from services.skill_worker import ACTIONS


class SkillRequest(BaseModel):
    params: dict = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)


def authenticate(authorization: str = Header(default='')):
    expected = settings.SKILL_API_TOKEN
    if not expected:
        raise HTTPException(503, 'Skill 接口尚未配置 Token')
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, 'Skill Token 无效')


router = APIRouter(prefix='/api/skills', tags=['Skill 数据'], dependencies=[Depends(authenticate)])


@router.post('/{stage}/{action}')
def execute_skill(stage: str, action: str, payload: SkillRequest):
    if action not in ACTIONS.get(stage, set()):
        raise HTTPException(404, '不支持的 Skill 操作')
    if action == 'schema' and payload.params.get('write'):
        raise HTTPException(400, '请在服务端执行固定迁移')
    backend = Path(__file__).resolve().parents[1]
    try:
        # 只执行服务端固定入口；不接受脚本路径、SQL 或命令行。
        process = subprocess.run(
            [sys.executable, '-m', 'services.skill_worker'], cwd=backend,
            input=json.dumps({'stage': stage, 'action': action, **payload.model_dump()}, ensure_ascii=False),
            capture_output=True, text=True, timeout=900,
        )
        response = json.loads(process.stdout)
        if process.returncode or not response.get('ok'):
            raise HTTPException(409, response.get('error', '操作未完成，请先查询状态'))
        return response['result']
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '执行超时，请先查询原任务状态再恢复') from None
    except (ValueError, OSError):
        raise HTTPException(500, 'Skill 执行失败，请先查询状态') from None
