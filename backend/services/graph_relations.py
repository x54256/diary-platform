"""完整要点向量、事件级精确召回和同v4独立双判。"""

import json
import math
from datetime import date
from itertools import combinations
from uuid import UUID

from sqlalchemy import text

from database import SessionLocal
from models.diary import Diary, DiaryEvent
from models.graph import GraphEventPoint, GraphRun, GraphRunEvent
from services.graph_points import require
from services.graph_runtime import GraphError, digest
from services.llm_metrics import estimate_prompt_tokens


def validate_vector(vector):
    require(isinstance(vector, list) and len(vector) == 1024, "向量维度必须为1024")
    require(all(type(x) in (float, int) and math.isfinite(x) for x in vector), "向量包含非法数值")
    require(sum(x * x for x in vector) > 0, "向量模长为零")


def pair_key(a, b):
    return "pair-" + digest(sorted((a, b)))[:24]


async def embed_points(ctx, state):
    vectors = dict(state.get("vectors", {}))
    for work in state["point_work"].values():
        for point in work["points"]:
            if point["id"] in vectors:
                validate_vector(vectors[point["id"]]); continue
            if len(point["detail"]) > ctx.config["embedding_max_chars"]:
                raise GraphError("EMBEDDING_INPUT_TOO_LARGE", "完整要点超向量输入预算", event_id=point["event_id"])
            def validate(data):
                require(isinstance(data, dict) and isinstance(data.get("data"), list) and len(data["data"]) == 1, "向量响应数量不一致")
                require(data["data"][0].get("index") == 0, "向量响应索引不一致")
                validate_vector(data["data"][0].get("embedding"))
            result = await ctx.call("embedding", point["id"], [point["detail"]], validate, embedding=True)
            vectors[point["id"]] = result["data"][0]["embedding"]
            state = ctx.save("EMBED_POINTS", vectors=vectors)
    return state


def recall(ctx, source, current_points, vectors):
    with SessionLocal() as db:
        ctx.owned(db)
        historic = db.query(GraphEventPoint).join(GraphRun, GraphRun.id == GraphEventPoint.run_id).join(
            Diary, Diary.id == GraphRun.diary_id).join(DiaryEvent, DiaryEvent.id == GraphEventPoint.event_id).filter(
                GraphRun.user_id == UUID(source["user_id"]), GraphRun.status == "PUBLISHED",
                GraphRun.diary_date < date.fromisoformat(source["diary_date"]), Diary.deleted_at.is_(None), DiaryEvent.is_in_graph.is_(True))
        if historic.filter(GraphEventPoint.embedding_model != ctx.config["embedding_model"]).first():
            raise GraphError("EMBEDDING_NOT_READY", "历史要点向量模型版本与当前任务不一致")
        queries = [{"point_id": p["id"], "embedding": "[" + ",".join(str(float(x)) for x in vectors[p["id"]]) + "]"} for p in current_points]
        result = db.execute(text("""
            WITH q AS (
                SELECT point_id::uuid, embedding::vector AS embedding
                FROM jsonb_to_recordset(CAST(:queries AS jsonb)) AS q(point_id text, embedding text)
            ), hits AS (
                SELECT p.event_id, p.run_id, p.id AS historic_point_id, q.point_id AS current_point_id,
                       1-(p.embedding <=> q.embedding) AS score
                FROM graph_event_points p
                JOIN graph_runs r ON r.id=p.run_id
                JOIN diaries d ON d.id=r.diary_id
                JOIN diary_events e ON e.id=p.event_id CROSS JOIN q
                WHERE r.user_id=:user_id AND r.status='PUBLISHED'
                  AND r.diary_date<:diary_date AND d.deleted_at IS NULL AND e.is_in_graph=true
                  AND p.embedding_model=:model
            ), best AS (
                SELECT DISTINCT ON (event_id) * FROM hits WHERE score>=:threshold
                ORDER BY event_id,score DESC,current_point_id,historic_point_id
            ) SELECT * FROM best ORDER BY score DESC,event_id LIMIT :top_k
        """), {"queries": json.dumps(queries), "user_id": UUID(source["user_id"]),
                "diary_date": date.fromisoformat(source["diary_date"]), "model": ctx.config["embedding_model"],
                "threshold": ctx.config["min_similarity"], "top_k": ctx.config["top_k"]}).mappings().all()
        return [{k: str(v) if isinstance(v, UUID) else v for k, v in r.items()} for r in result]


def load_history(ctx, source, candidates):
    events = {}
    with SessionLocal() as db:
        ctx.owned(db)
        for hit in candidates:
            event_id = hit["event_id"]
            if event_id in events: continue
            run = db.query(GraphRun).filter(GraphRun.id == UUID(hit["run_id"]),
                GraphRun.user_id == UUID(source["user_id"]), GraphRun.status == "PUBLISHED").one_or_none()
            if not run:
                raise GraphError("DEPENDENCY_OBSOLETE", "历史端点运行已过时")
            event = db.query(DiaryEvent).filter(DiaryEvent.id == UUID(event_id), DiaryEvent.is_in_graph.is_(True)).one()
            points = db.query(GraphEventPoint).filter(GraphEventPoint.run_id == run.id,
                GraphEventPoint.event_id == event.id).order_by(GraphEventPoint.no).all()
            occurrence = db.query(GraphRunEvent).filter(GraphRunEvent.run_id == run.id, GraphRunEvent.event_id == event.id).one()
            events[event_id] = {"id": event_id, "run_id": str(run.id), "title": event.event_title,
                "diary_date": run.diary_date.isoformat(), "occurred_on": occurrence.occurred_on.isoformat() if occurrence.occurred_on else None,
                "points": [{"id": str(p.id), "no": p.no, "summary": p.summary, "detail": p.detail} for p in points]}
    return events


async def discover(ctx, source, state):
    hits = dict(state.get("recall", {}))
    current = {}
    for event in source["events"]:
        event_id = event["event_id"]
        if event_id not in state["point_work"]: continue
        points = state["point_work"][event_id]["points"]
        current[event_id] = {"id": event_id, "run_id": str(ctx.run_id), "title": event["title"],
            "diary_date": source["diary_date"], "occurred_on": None, "points": points}
        if event_id not in hits:
            hits[event_id] = recall(ctx, source, points, state["vectors"])
            state = ctx.save("RECALL_PAIRS", recall=hits)
    historic = load_history(ctx, source, [h for group in hits.values() for h in group])
    pairs = {pair_key(a, b): {"pair_id": pair_key(a, b), "event_a_id": a, "event_b_id": b}
             for a, b in combinations(sorted(current), 2)}
    for event_id, group in hits.items():
        for hit in group:
            a, b = sorted((event_id, hit["event_id"]))
            pairs[pair_key(a, b)] = {"pair_id": pair_key(a, b), "event_a_id": a, "event_b_id": b}
    return ctx.save("RECALL_PAIRS", event_pool={**current, **historic}, pairs=sorted(pairs.values(), key=lambda p: p["pair_id"]))


def validate_pair(result, pair, events):
    fields = {"pair_id", "status", "reason", "relation"}
    require(isinstance(result, dict), "事件对结果必须为对象")
    require(set(result) == fields,
            f"事件对结果字段不一致；缺少{sorted(fields - set(result))}，多出{sorted(set(result) - fields)}")
    require(result["pair_id"] == pair["pair_id"], "事件对ID不匹配")
    require(result["status"] in ("RELATED", "NO_RELATION", "UNRESOLVED"), "关系状态不合法")
    require(isinstance(result["reason"], str) and result["reason"].strip(), "判断理由为空")
    relation = result["relation"]
    if result["status"] != "RELATED":
        require(relation is None, "非关系状态必须relation=null"); return
    require(isinstance(relation, dict) and set(relation) == {"source_event_id", "target_event_id", "relation_type", "certainty", "source_point_nos", "target_point_nos", "description"}, "关系字段不一致")
    require({relation["source_event_id"], relation["target_event_id"]} == {pair["event_a_id"], pair["event_b_id"]}, "关系端点不属于指定事件对")
    require(relation["relation_type"] in ("后续事件", "引发事件", "提及事件"), "关系类型不合法")
    require(relation["certainty"] in ("EXPLICIT", "SPECULATIVE"), "确定性不合法")
    require(isinstance(relation["description"], str) and relation["description"].strip(), "关系描述为空")
    for side in ("source", "target"):
        nums = relation[side + "_point_nos"]
        require(isinstance(nums, list) and nums and all(type(n) is int for n in nums) and len(set(nums)) == len(nums), "证据序号必须非空无重复整数")
        require(set(nums) <= {p["no"] for p in events[relation[side + "_event_id"]]["points"]}, "证据不属于关系端点")


def equivalent(a, b):
    if a["status"] != b["status"]: return False
    if a["status"] != "RELATED": return True
    def canonical(item):
        r = dict(item["relation"])
        r["description"] = r["description"].strip()
        r["source_point_nos"] = sorted(r["source_point_nos"])
        r["target_point_nos"] = sorted(r["target_point_nos"])
        return r
    return canonical(a) == canonical(b)


def payload_for(pairs, events):
    ids = sorted({p[k] for p in pairs for k in ("event_a_id", "event_b_id")})
    pool = [{k: v for k, v in events[i].items() if k in ("id", "title", "diary_date", "occurred_on")} |
            {"points": [{k: p[k] for k in ("no", "summary", "detail")} for p in events[i]["points"]]} for i in ids]
    return {"events": pool, "pairs": pairs}


def batches(ctx, role, pairs, events, candidates=None):
    batches_, batch = [], []
    def fits(items):
        payload = payload_for(items, events)
        if candidates is not None: payload["disagreements"] = [{"pair": p, "candidate_1": candidates[p["pair_id"]][0], "candidate_2": candidates[p["pair_id"]][1]} for p in items]
        if candidates is not None: payload.pop("pairs")
        n = estimate_prompt_tokens(ctx.config["models"][role]["model_name"], ctx.config["prompts"][role], json.dumps(payload, ensure_ascii=False))
        reserve = max(ctx.config["output_per_pair"] * len(items), 1024)
        return reserve <= ctx.config["max_output_tokens"] and n + ctx.config["max_output_tokens"] + ctx.config["safety_tokens"] <= ctx.config["context_limit"]
    for pair in pairs:
        if not fits([pair]): raise GraphError("INPUT_TOO_LARGE", "单事件对完整内容超预算", pair_id=pair["pair_id"])
        if batch and not fits(batch + [pair]): batches_.append(batch); batch = []
        batch.append(pair)
    if batch: batches_.append(batch)
    return batches_


async def judge(ctx, state, role, pairs, candidates=None):
    saved = dict(state.get(role, {}))
    todo = [p for p in pairs if p["pair_id"] not in saved]
    events = state["event_pool"]
    with SessionLocal() as db:
        recovery = ctx.owned(db).retry_count
    diagnostics = list(state.get("relation_diagnostics", []))
    for batch in batches(ctx, role, todo, events, candidates):
        pending_batches = [batch]
        for attempt in range(2):
            retry_batches = []
            for pending in pending_batches:
                payload = payload_for(pending, events)
                if candidates is not None:
                    payload["disagreements"] = [{"pair": p, "candidate_1": candidates[p["pair_id"]][0],
                        "candidate_2": candidates[p["pair_id"]][1]} for p in pending]
                    payload.pop("pairs")
                pending_ids = {p["pair_id"] for p in pending}
                feedback = [error for item in diagnostics if item["stage"] == role
                            for error in item["errors"] if error.get("pair_id") in pending_ids]
                if feedback:
                    payload["validation_errors"] = feedback
                def validate(data):
                    require(isinstance(data, dict) and set(data) == {"results"} and isinstance(data["results"], list), "批量响应顶层不合法")
                unit = digest([p["pair_id"] for p in pending]) + f":{recovery}:{attempt}"
                try:
                    result = await ctx.call(role, unit, payload, validate, max_attempts=1)
                except GraphError as error:
                    if error.code == "MODEL_QUOTA_EXHAUSTED": raise
                    if attempt == 1: raise
                    if error.code in ("MODEL_OUTPUT_TRUNCATED", "MODEL_OUTPUT_INVALID") and len(pending) > 1:
                        middle = (len(pending) + 1) // 2
                        retry_batches.extend((pending[:middle], pending[middle:]))
                    else:
                        retry_batches.append(pending)
                    continue
                results = result["results"]
                requested = {p["pair_id"]: p for p in pending}
                errors = []
                for row in results:
                    if not isinstance(row, dict) or row.get("pair_id") not in requested:
                        errors.append({"code": "EXTRA_PAIR", "pair_id": row.get("pair_id") if isinstance(row, dict) else None})
                for pair_id, pair in requested.items():
                    found = [r for r in results if isinstance(r, dict) and r.get("pair_id") == pair_id]
                    if len(found) != 1:
                        errors.append({"code": "MISSING_PAIR" if not found else "DUPLICATE_PAIR", "pair_id": pair_id})
                        continue
                    try: validate_pair(found[0], pair, events)
                    except (ValueError, KeyError, TypeError) as error:
                        errors.append({"code": "INVALID_PAIR", "pair_id": pair_id, "message": str(error)[:1000]})
                        continue
                    saved[pair_id] = found[0]
                if errors: diagnostics.append({"stage": role, "unit_key": unit, "errors": errors})
                state = ctx.save({"relation_a": "JUDGE_A", "relation_b": "JUDGE_B", "relation_c": "ADJUDICATE"}[role],
                    **{role: saved}, relation_diagnostics=diagnostics)
                missing = [p for p in pending if p["pair_id"] not in saved]
                if missing: retry_batches.extend(batches(ctx, role, missing, events, candidates))
            pending_batches = retry_batches
            if not pending_batches: break
        if pending_batches:
            raise GraphError("PAIR_RESULTS_INCOMPLETE", "两次请求后仍有缺失或无效事件对", stage=role,
                pair_id=pending_batches[0][0]["pair_id"])

    return state


async def identify(ctx, state):
    pairs = state["pairs"]
    state = await judge(ctx, state, "relation_a", pairs)
    state = await judge(ctx, state, "relation_b", pairs)
    disagreements, candidates = [], {}
    for pair in pairs:
        a, b = state.get("relation_a", {})[pair["pair_id"]], state.get("relation_b", {})[pair["pair_id"]]
        if not equivalent(a, b):
            disagreements.append(pair); candidates[pair["pair_id"]] = [a, b]
    state = await judge(ctx, state, "relation_c", disagreements, candidates)
    final = []
    for pair in pairs:
        key = pair["pair_id"]
        result = dict(state["relation_c"][key] if key in candidates else state["relation_a"][key])
        result["final_source"] = "ADJUDICATED" if key in candidates else "AGREEMENT"
        final.append(result)
    return ctx.save("CHECK_GRAPH", final_pair_results=final, graph_checked=True)
