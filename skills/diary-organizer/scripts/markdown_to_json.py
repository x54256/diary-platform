#!/usr/bin/env python3
"""将约定格式的整理稿转换为入库结果；不访问数据库。"""

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paragraphs(lines):
    return [part.strip() for part in re.split(r"\n\s*\n", "\n".join(lines)) if part.strip()]


def list_items(lines):
    items = []
    for line in lines:
        if not line.strip():
            continue
        match = re.match(r"^\s*(?:[-*]|\d+[.、])\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip())
        elif line.startswith(("  ", "\t")) and items:
            items[-1] += "\n" + line.strip()
        else:
            raise ValueError("琐事和后续计划须使用列表；续行须缩进")
    return items


def derived_items(lines):
    nonempty = [line for line in lines if line.strip()]
    if nonempty and re.match(r"^\s*(?:[-*]|\d+[.、])\s+", nonempty[0]):
        return list_items(lines)
    return paragraphs(lines)


def validate_result(result):
    expected = {"title", "summary", "location", "introduction", "events", "trivia", "plans",
                "check_log", "clean_check_log"}
    if not isinstance(result, dict) or set(result) != expected:
        raise ValueError("整理结果字段不完整或包含未知字段")
    for key in ("title", "summary", "location", "introduction"):
        if not isinstance(result[key], str):
            raise ValueError(f"{key} 必须是字符串")
    for key in ("events", "trivia", "plans", "check_log", "clean_check_log"):
        if not isinstance(result[key], list):
            raise ValueError(f"{key} 必须是数组")
    if any(result[key] for key in ("title", "summary", "location", "check_log", "clean_check_log")):
        raise ValueError("本脚本仅导入整理结果，元数据和审核记录须为空")
    for key in ("trivia", "plans"):
        if any(not isinstance(item, str) or not item.strip() for item in result[key]):
            raise ValueError(f"{key} 必须包含非空字符串")
    for index, event in enumerate(result["events"], 1):
        if not isinstance(event, dict) or set(event) != {
            "title", "body", "feeling", "reflection", "importance", "importance_reason"
        }:
            raise ValueError(f"事件 {index} 字段不完整或包含未知字段")
        if not isinstance(event["title"], str) or not 1 <= len(event["title"].strip()) <= 200:
            raise ValueError(f"事件 {index} 标题须为 1 至 200 字")
        for key in ("body", "feeling", "reflection"):
            values = event[key]
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"事件 {index} 的 {key} 须为非空字符串组成的数组")
        if not event["body"]:
            raise ValueError(f"事件 {index} 正文为空")
        if event["importance"] not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError(f"事件 {index} 缺少有效的重要性")
        if not isinstance(event["importance_reason"], str) or not event["importance_reason"].strip():
            raise ValueError(f"事件 {index} 缺少重要性理由")
    if not any(result[key] for key in ("introduction", "events", "trivia", "plans")):
        raise ValueError("整理稿为空")
    return result


def parse_markdown(markdown):
    result = dict(title="", summary="", location="", introduction="", events=[],
                  trivia=[], plans=[], check_log=[], clean_check_log=[])
    sections = []
    lines = []
    target = "introduction"
    event = None
    seen_top = set()
    seen_event = set()
    order = 0
    for number, line in enumerate(markdown.splitlines(), 1):
        if line.startswith("## 事件："):
            if order > 1:
                raise ValueError(f"第 {number} 行：事件须位于琐事和后续计划之前")
            sections.append((event, target, lines))
            event = dict(title=line[len("## 事件："):].strip(), body=[], feeling=[],
                         reflection=[], importance=None, importance_reason="")
            result["events"].append(event)
            target, lines, seen_event, order = "body", [], set(), 1
        elif line in ("## 琐事", "## 后续计划"):
            key, new_order = ("trivia", 2) if line == "## 琐事" else ("plans", 3)
            if key in seen_top or new_order < order:
                raise ValueError(f"第 {number} 行：栏目重复或顺序错误")
            sections.append((event, target, lines))
            target, event, lines, order = key, None, [], new_order
            seen_top.add(key)
        elif line in ("### 感受", "### 反思与成长", "### 重要性"):
            key = {"### 感受": "feeling", "### 反思与成长": "reflection", "### 重要性": "importance"}[line]
            if event is None or key in seen_event:
                raise ValueError(f"第 {number} 行：事件子栏目重复或不属于事件")
            sections.append((event, target, lines))
            target, lines = key, []
            seen_event.add(key)
        elif re.match(r"^\s*#{1,6}(?:\s|$)", line) or line.lstrip().startswith("```"):
            raise ValueError(f"第 {number} 行：不支持的标题或代码块，请按入库格式整理")
        else:
            lines.append(line)
    sections.append((event, target, lines))
    for owner, key, content in sections:
        if key == "introduction":
            result[key] = "\n\n".join(paragraphs(content))
        elif key in ("trivia", "plans"):
            result[key] = list_items(content)
        elif key == "importance":
            value = "\n".join(content).strip()
            match = re.fullmatch(r"(HIGH|MEDIUM|LOW)\s*[：:]\s*(\S[^\n]*)", value)
            if not match:
                raise ValueError("重要性须单独一行写为 HIGH：理由、MEDIUM：理由或 LOW：理由")
            owner["importance"], owner["importance_reason"] = match.groups()
        elif key == "body":
            owner[key] = paragraphs(content)
        else:
            owner[key] = derived_items(content)
    return validate_result(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = parse_markdown(args.markdown.read_text(encoding="utf-8"))
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"转换失败：{exc}\n")
    print(f"转换完成：{args.output}，事件数：{len(result['events'])}")


if __name__ == "__main__":
    main()
