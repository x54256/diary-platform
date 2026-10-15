"""从残留 CPython 3.11 字节码恢复的关系盲判与分歧裁决脚本。"""

import asyncio
import sys

from scripts.historical_layer1_validation import validate_event_points_baseline
from scripts.historical_layer1_validation import validate_layer1_full
from scripts.historical_layer1_validation import validate_layer1_semantic_only
from scripts.historical_layer1_validation._historical_pyc import restore


sys.modules["scripts.validate_event_points_baseline"] = validate_event_points_baseline
sys.modules["scripts.validate_layer1_full"] = validate_layer1_full
sys.modules["scripts.validate_layer1_semantic_only"] = validate_layer1_semantic_only


restore(
    globals(),
    "validate_layer1_blind_verify",
    "67abc7f60d568d233564634b41a2989dc7f87470d18549e88660785b5594c798",
)


if __name__ == "__main__":
    asyncio.run(main())
