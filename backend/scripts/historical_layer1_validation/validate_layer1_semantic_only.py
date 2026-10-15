"""从残留 CPython 3.11 字节码恢复的纯语义关系隔离实验脚本。"""

import asyncio
import sys

from scripts.historical_layer1_validation import validate_event_points_baseline
from scripts.historical_layer1_validation import validate_layer1_full
from scripts.historical_layer1_validation._historical_pyc import restore


sys.modules["scripts.validate_event_points_baseline"] = validate_event_points_baseline
sys.modules["scripts.validate_layer1_full"] = validate_layer1_full


restore(
    globals(),
    "validate_layer1_semantic_only",
    "ad9ecfc8023107b05d57a871a73e805a7d2e886593425d4e5d488217dd262c3f",
)


if __name__ == "__main__":
    asyncio.run(main())
