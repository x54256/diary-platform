"""冻结配置、执行权和可回放的模型调用，认证信息不进入过程记录。"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

import httpx
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import SessionLocal
from models.graph import GraphModelCall, GraphRun, GraphTask, utcnow
from models.model_config import ChannelModel
from services.llm_metrics import estimate_prompt_tokens
from services.model_management import decrypt_channel_key
from services.model_runtime import ModelRuntimeError, resolve_model_setting, resolve_thinking_payload

CALL_STEPS = {
    "point_generate": "EXTRACT_POINTS", "point_combined": "EXTRACT_POINTS", "point_review": "EXTRACT_POINTS",
    "embedding": "EMBED_POINTS", "relation_a": "JUDGE_A", "relation_b": "JUDGE_B", "relation_c": "ADJUDICATE",
    "mood_tag_extract": "ANALYZE_METADATA", "core_analysis": "ANALYZE_CORE", "feedback_core_analysis": "ANALYZE_CORE",
    "cognition_analysis": "ANALYZE_COGNITION", "feedback_cognition_analysis": "ANALYZE_COGNITION", "action_planning": "PLAN_ACTIONS",
}


class GraphError(RuntimeError):
    def __init__(self, code, message, **context):
        super().__init__(message)
        self.code, self.context = code, context


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def freeze_model(config, thinking=True):
    if not config.channel_model_id:
        raise GraphError("MODEL_NOT_CONFIGURED", "模型用途尚未配置")
    try:
        payload = resolve_thinking_payload(config, enabled=thinking) if config.model_type == "language" else {}
    except ModelRuntimeError as error:
        raise GraphError("THINKING_UNSUPPORTED", str(error)) from error
    if thinking and not payload:
        raise GraphError("THINKING_UNSUPPORTED", "当前渠道不能显式开启思考模式")
    return {"channel_model_id": str(config.channel_model_id), "model_name": config.model_name,
            "api_base_url": config.api_base_url, "model_type": config.model_type,
            "protocol": config.protocol, "thinking_payload": payload}


def thaw_model(snapshot):
    with SessionLocal() as db:
        item = db.query(ChannelModel).options(joinedload(ChannelModel.channel)).filter(
            ChannelModel.id == UUID(snapshot["channel_model_id"])).first()
        if not item or not item.enabled or not item.channel.enabled:
            raise GraphError("MODEL_NOT_CONFIGURED", "冻结的渠道模型已不可用")
        key = decrypt_channel_key(item.channel)
    return snapshot["api_base_url"].rstrip("/"), key


def freeze_config(include_analysis=False):
    from config import settings
    fixtures = Path(__file__).resolve().parents[1] / "scripts/fixtures"
    baseline = json.loads((fixtures / "event_point_baseline.json").read_text())
    for name, prompt in baseline["prompts"].items():
        if hashlib.sha256(prompt.encode()).hexdigest() != baseline["prompt_sha256"][name]:
            raise GraphError("PROMPT_CHANGED", "要点提示指纹与冻结基线不一致")
    models = {}
    def resolve(setting, step=None):
        try: return resolve_model_setting(setting, step)
        except ModelRuntimeError as error:
            raise GraphError("MODEL_NOT_CONFIGURED", str(error), stage=step or setting) from error
    for role in ("point_generate", "point_combined", "point_review", "relation_a", "relation_b", "relation_c"):
        models[role] = freeze_model(resolve("graph", "graph_" + role))
    for roles in (("point_generate", "point_combined", "point_review"), ("relation_a", "relation_b", "relation_c")):
        if len({digest(models[r]) for r in roles}) != 1:
            raise GraphError("MODEL_CONFIGURATION_MISMATCH", "同组生成与核验阶段必须使用相同冻结模型配置")
    models["embedding"] = freeze_model(resolve("graph_embedding"), thinking=False)
    prompts = {"point_generate": baseline["prompts"]["generate"],
               "point_combined": baseline["prompts"]["combined"],
               "point_review": baseline["prompts"]["review"],
               "relation_a": (fixtures / "layer1_relation_batch_prompt_v4.txt").read_text(),
               "relation_c": (fixtures / "layer1_relation_adjudicate_v3.txt").read_text()}
    prompts["relation_b"] = prompts["relation_a"]
    if include_analysis:
        from services.graph_analysis import analysis_prompts
        prompts.update(analysis_prompts())
        for role in analysis_prompts():
            analysis_config = resolve("analysis", role)
            models[role] = freeze_model(analysis_config, thinking=bool(analysis_config.thinking_enabled))
    return {"models": models, "prompts": prompts,
            "prompt_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in prompts.items()},
            "point_version": baseline["version"], "relation_version": "v4-shared",
            "analysis_version": "analysis-graph-event-id-20261014",
            "context_limit": settings.GRAPH_CONTEXT_TOKEN_LIMIT,
            "max_output_tokens": settings.GRAPH_MAX_OUTPUT_TOKENS,
            "output_per_pair": settings.GRAPH_OUTPUT_TOKENS_PER_PAIR,
            "safety_tokens": settings.GRAPH_CONTEXT_SAFETY_TOKENS,
            "embedding_max_chars": settings.GRAPH_EMBEDDING_MAX_CHARS,
            "min_similarity": settings.GRAPH_RECALL_MIN_SIMILARITY,
            "top_k": settings.GRAPH_RECALL_TOP_K,
            "embedding_model": digest(models["embedding"])}


@dataclass
class GraphContext:
    task_id: UUID
    run_id: UUID
    token: UUID
    config: dict

    def owned(self, db, lock=False):
        query = db.query(GraphTask).filter(GraphTask.id == self.task_id,
            GraphTask.status == "RUNNING", GraphTask.run_token == self.token,
            GraphTask.lease_until > utcnow())
        task = query.with_for_update().first() if lock else query.first()
        if not task:
            raise GraphError("OWNERSHIP_LOST", "任务执行权已失效")
        return task

    def save(self, step=None, **changes):
        with SessionLocal() as db:
            task = self.owned(db, lock=True)
            run = db.query(GraphRun).filter(GraphRun.id == self.run_id,
                                           GraphRun.task_id == task.id).with_for_update().one()
            state = dict(run.checkpoint or {})
            state.update(changes)
            run.checkpoint, run.updated_at = state, utcnow()
            if step:
                run.current_step = step
                if task.organize_task_id:
                    from models.diary import OrganizeTask
                    db.query(OrganizeTask).filter(OrganizeTask.id == task.organize_task_id).update({"current_step": step})
            db.commit()
        return state

    async def call(self, role, unit_key, payload, validator: Callable, *, max_attempts=2,
                   prompt=None, embedding=False):
        if role in CALL_STEPS:
            self.save(CALL_STEPS[role])
        model = self.config["models"][role]
        prompt = self.config["prompts"].get(role, "") if prompt is None else prompt
        base_request = {"model": model["model_name"]}
        if embedding:
            base_request.update(input=payload, dimensions=1024, encoding_format="float")
        else:
            base_request.update(messages=[{"role": "system", "content": prompt},
                                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                                response_format={"type": "json_object"},
                                max_tokens=self.config["max_output_tokens"])
            base_request.update(model["thinking_payload"])
            size = estimate_prompt_tokens(model["model_name"], prompt, base_request["messages"][1]["content"])
            if size + self.config["max_output_tokens"] + self.config["safety_tokens"] > self.config["context_limit"]:
                raise GraphError("INPUT_TOO_LARGE", "完整请求超过冻结上下文预算")
        request_hash = digest(base_request)
        with SessionLocal() as db:
            self.owned(db)
            calls = db.query(GraphModelCall).filter(GraphModelCall.run_id == self.run_id,
                GraphModelCall.stage == role.upper(), GraphModelCall.unit_key == unit_key).order_by(GraphModelCall.attempt_no).all()
            for record in calls:
                if record.status == "SUCCEEDED" and record.request_snapshot.get("base_sha256") == request_hash:
                    validator(record.parsed_result)
                    return record.parsed_result
            offset = max((r.attempt_no for r in calls), default=0)
        previous_raw, previous_error = None, None
        for attempt in range(max_attempts):
            body = json.loads(json.dumps(base_request))
            if previous_error and not embedding:
                body["messages"].append({"role": "user", "content": "前次结构错误：" + previous_error +
                    "。重新完整输出，不改变结论迎合结构。前次响应：" + (previous_raw or "")})
                retry_size = estimate_prompt_tokens(model["model_name"], prompt, json.dumps(body["messages"], ensure_ascii=False))
                if retry_size + self.config["max_output_tokens"] + self.config["safety_tokens"] > self.config["context_limit"]:
                    body["messages"].pop()  # 仍发送完整原请求，不截断事件输入。
            with SessionLocal() as db:
                self.owned(db, lock=True)
                record = GraphModelCall(task_id=self.task_id, run_id=self.run_id, stage=role.upper(),
                    unit_key=unit_key, attempt_no=offset + attempt + 1, status="STARTED",
                    request_snapshot={"body": body, "base_sha256": request_hash,
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "model": model, "context_limit": self.config["context_limit"]})
                db.add(record); db.flush(); record_id = record.id; db.commit()
            raw, content, parsed, errors, usage = None, None, None, [], {}
            api_key = ""
            error_code = "MODEL_CALL_FAILED"
            try:
                base_url, api_key = thaw_model(model)
                async with httpx.AsyncClient(timeout=1200) as client:
                    response = await client.post(base_url + ("/embeddings" if embedding else "/chat/completions"),
                        headers={"Authorization": "Bearer " + api_key}, json=body)
                raw = response.text
                if response.status_code != 200:
                    try:
                        provider_error = response.json().get("error") or {}
                    except (ValueError, AttributeError):
                        provider_error = {}
                    if isinstance(provider_error, dict) and provider_error.get("code") == "insufficient_quota":
                        raise GraphError("MODEL_QUOTA_EXHAUSTED", "模型额度已耗尽，请恢复额度后重试")
                    raise GraphError("MODEL_CALL_FAILED", "模型服务返回HTTP " + str(response.status_code))
                data = response.json(); usage = data.get("usage") or {}
                if embedding:
                    parsed = data
                else:
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    if choice.get("finish_reason") == "length":
                        raise GraphError("MODEL_OUTPUT_TRUNCATED", "模型响应达到输出上限")
                    parsed = json.loads(content)
                validator(parsed)
            except (httpx.HTTPError, KeyError, TypeError, ValueError, GraphError) as exc:
                error_code = exc.code if isinstance(exc, GraphError) else "MODEL_OUTPUT_INVALID" if raw else "MODEL_CALL_FAILED"
                errors = [(str(exc).replace(api_key, "[已隐藏]") if api_key else str(exc))[:1000]]
            with SessionLocal() as db:
                self.owned(db, lock=True)
                record = db.query(GraphModelCall).filter(GraphModelCall.id == record_id).one()
                record.status = "FAILED" if errors else "SUCCEEDED"
                record.response_text = (raw.replace(api_key, "[已隐藏]") if api_key else raw) if raw else None
                record.parsed_result, record.validation_errors = parsed, errors
                record.input_tokens = usage.get("prompt_tokens")
                record.output_tokens = usage.get("completion_tokens")
                record.reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                record.error_code = error_code if errors else None
                record.error_message = errors[0] if errors else None
                record.completed_at = utcnow(); db.commit()
            if not errors:
                return parsed
            if error_code == "MODEL_QUOTA_EXHAUSTED":
                raise GraphError(error_code, "模型额度已耗尽，请恢复额度后重试", stage=role, call_id=str(record_id))
            previous_raw, previous_error = content, errors[0]
        raise GraphError(error_code, "模型阶段未取得合法结果", stage=role, call_id=str(record_id))
