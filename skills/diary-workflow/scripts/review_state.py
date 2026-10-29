#!/usr/bin/env python3
"""记录真实的人工审阅通知和联动复查结论，不访问数据库。"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'shared'))
from review_flow import transition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['wait', 'start', 'finish'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--user-message')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = transition(args.action, json.loads(args.source.read_text(encoding='utf-8')),
            user_message=args.user_message,
            report=json.loads(args.report.read_text(encoding='utf-8')) if args.report else None)
        print(json.dumps({'phase': result['phase'], 'diary_id': result['identity']['diary_id']}, ensure_ascii=False))
    except (ValueError, OSError, KeyError):
        parser.exit(1, '流程记录未更新：请检查来源、用户实际通知和复查结论\n')


if __name__ == '__main__': main()
