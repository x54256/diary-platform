"""从残留 CPython 3.11 字节码恢复的第一层完整隔离实测脚本。"""

import asyncio
import sys

from scripts.historical_layer1_validation import validate_event_points_baseline
from scripts.historical_layer1_validation import validate_layer1_relations_0826
from scripts.historical_layer1_validation._historical_pyc import restore


sys.modules["scripts.validate_event_points_baseline"] = validate_event_points_baseline
sys.modules["scripts.validate_layer1_relations_0826"] = validate_layer1_relations_0826


restore(
    globals(),
    "validate_layer1_full",
    "bcab958e367b340fa7d59c02bd2370d66f7980afd70bab7701a530e96ab1029e",
)


if __name__ == "__main__":
    asyncio.run(main())
