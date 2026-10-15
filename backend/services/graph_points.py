"""按冻结基线执行单事件要点生成、审核修正及独立复核。"""

import re
from copy import deepcopy
from uuid import uuid4

from database import SessionLocal
from services.graph_runtime import GraphError


def require(ok, message):
    if not ok:
        raise ValueError(message)


def paragraphs(body):
    import json
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError as exc:
            raise GraphError("SOURCE_NOT_READY", "来源正文不是合法JSON数组") from exc
    if not isinstance(body, list) or any(not isinstance(p, str) for p in body):
        raise GraphError("SOURCE_NOT_READY", "来源正文必须为字符串数组")
    if not any(p.strip() for p in body):
        raise GraphError("SOURCE_NOT_READY", "准入事件正文为空")
    return [{"id": i + 1, "text": p} for i, p in enumerate(body)]


def source_units(event):
    rows = []
    for p in event["paragraphs"]:
        for sentence in re.findall(r"[^。！？]+[。！？]?", p["text"]):
            if sentence.strip():
                rows.append({"id": len(rows) + 1, "paragraph_id": p["id"], "text": sentence})
    return rows


def validate_points(data, event):
    require(isinstance(data, dict) and set(data) == {"title", "points"}, "要点顶层字段不一致")
    require(data["title"] == event["title"], "要点未沿用原标题")
    points = data["points"]
    require(isinstance(points, list) and bool(points), "要点数组为空")
    for i, point in enumerate(points, 1):
        require(isinstance(point, dict) and set(point) == {"no", "summary", "detail"}, "要点字段不一致")
        require(type(point["no"]) is int and point["no"] == i, "要点序号必须为连续整数")
        require(all(isinstance(point[k], str) and point[k].strip() for k in ("summary", "detail")), "要点内容为空")


def validate_review(data, event, candidate, protocol="legacy"):
    require(protocol in ("legacy", "issues-v2"), "未知审核协议")
    require(isinstance(data, dict) and set(data) == {"source_checks", "checks"}, "审核顶层字段不一致")
    require(isinstance(data["source_checks"], list) and isinstance(data["checks"], list), "审核清单不是数组")
    for row in data["source_checks"]:
        require(isinstance(row, dict), "source_checks每项必须为对象")
        require(type(row.get("source_unit_id")) is int,
                "source_checks每项必须使用字段source_unit_id并填整数；不能用输入的id代替，实际字段：" + str(list(row)))
    require(all(isinstance(x, dict) and type(x.get("no")) is int for x in data["checks"]), "审核要点编号必须为整数")
    actual_ids = [x["source_unit_id"] for x in data["source_checks"]]
    expected_ids = [x["id"] for x in source_units(event)]
    require(actual_ids == expected_ids,
            f"原句检查编号必须完整且按序；预期{expected_ids}，实际{actual_ids}")
    require(all(isinstance(x.get("comparison"), str) and x["comparison"].strip() for x in data["source_checks"]), "缺少原句比较")
    require([x.get("no") for x in data["checks"] if isinstance(x, dict)] == [p["no"] for p in candidate["points"]], "要点检查不完整")
    for check, point in zip(data["checks"], candidate["points"]):
        if protocol == "issues-v2":
            require(set(check) == {"no", "issues"}, "新版审核每项只允许no和issues，通过状态由程序计算")
        require(isinstance(check.get("issues"), list), "审核问题必须为数组")
        for issue in check["issues"]:
            require(isinstance(issue, dict) and issue.get("field") in ("summary", "detail"), "审核问题字段不合法")
            quote = issue.get("candidate_quote")
            require(isinstance(quote, str) and quote and quote in point[issue["field"]],
                    f"要点{point['no']}的{issue['field']}候选引用必须是输入字段的连续原文，不得使用省略号拼接")
            require(type(issue.get("source_index")) is int and 1 <= issue["source_index"] <= len(data["source_checks"]), "原句编号越界")
            require(all(isinstance(issue.get(k), str) and issue[k].strip() for k in ("difference", "repair")), "修正意见缺失")
        if protocol == "legacy":
            for field in ("summary", "detail"):
                require(type(check.get(field + "_ok")) is bool and check[field + "_ok"] ==
                        (not any(x["field"] == field for x in check["issues"])), "审核状态与问题矛盾")


def review_with_status(data):
    """验证后的问题清单计算状态；不改写模型原始响应或调用缓存。"""
    result = deepcopy(data)
    for check in result["checks"]:
        for field in ("summary", "detail"):
            check[field + "_ok"] = not any(x["field"] == field for x in check["issues"])
    return result


def combined_payload(source, candidate, previous_review=None):
    payload = {"source": source, "candidate": candidate}
    if previous_review is not None:
        payload["previous_review"] = deepcopy(previous_review)
    return payload


def validate_combined(data, event, candidate, protocol="legacy"):
    require(isinstance(data, dict) and set(data) == {"review", "candidate"}, "合并输出字段不一致")
    validate_review(data["review"], event, candidate, protocol)
    validate_points(data["candidate"], event)
    if not any(c["issues"] for c in data["review"]["checks"]):
        require(data["candidate"] == candidate, "未发现问题却修改候选")


async def extract_event(ctx, event, state):
    event_id = event["event_id"]
    source = {"title": event["title"], "paragraphs": paragraphs(event["body"])}
    with SessionLocal() as db: recovery = ctx.owned(db).retry_count
    cache = dict(state.get("point_work", {}))
    work = dict(cache.get(event_id, {}))
    candidate = work.get("candidate")
    protocol = ctx.config.get("point_review_protocol", "legacy")
    if candidate is None:
        candidate = await ctx.call("point_generate", event_id, source, lambda x: validate_points(x, source))
        work.update(candidate=candidate, round=0, next="combined", reports=[])
        cache[event_id] = work
        state = ctx.save("EXTRACT_POINTS", point_work=cache)
    while work["round"] < 2:
        round_no = work["round"] + 1
        review_source = {**source, "source_units": source_units(source)}
        if work["next"] == "combined":
            result = await ctx.call("point_combined", f"{event_id}:{recovery}:{round_no}",
                combined_payload(review_source, candidate,
                    work.get("pending_review") if protocol == "issues-v2" else None),
                lambda x: validate_combined(x, source, candidate, protocol))
            work["reports"].append(review_with_status(result["review"]))
            work.pop("pending_review", None)
            if not any(c["issues"] for c in result["review"]["checks"]):
                work["passed"] = True
                break
            candidate = result["candidate"]
            work.update(candidate=candidate, next="review")
            cache[event_id] = work
            state = ctx.save("EXTRACT_POINTS", point_work=cache)
        review = await ctx.call("point_review", f"{event_id}:{recovery}:{round_no}",
            {"source": review_source, "candidate": candidate},
            lambda x: validate_review(x, source, candidate, protocol))
        work["reports"].append(review_with_status(review))
        if protocol == "issues-v2":
            work["pending_review"] = deepcopy(review)
        work.update(round=round_no, next="combined")
        cache[event_id] = work
        state = ctx.save("EXTRACT_POINTS", point_work=cache)
        if not any(c["issues"] for c in review["checks"]):
            work["passed"] = True
            break
    if not work.get("passed"):
        raise GraphError("POINT_REVIEW_FAILED", "两轮修正后仍未通过独立核验", event_id=event_id)
    if "points" not in work:
        work["points"] = [{**p, "id": str(uuid4()), "event_id": event_id,
                           "run_id": str(ctx.run_id)} for p in candidate["points"]]
    cache[event_id] = work
    return ctx.save("EXTRACT_POINTS", point_work=cache)
