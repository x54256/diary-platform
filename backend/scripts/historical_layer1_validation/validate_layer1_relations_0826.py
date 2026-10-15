"""从残留 CPython 3.11 字节码恢复的历史关系判断脚本。"""

import sys

from scripts.historical_layer1_validation import validate_event_points_baseline
from scripts.historical_layer1_validation._historical_pyc import restore


sys.modules["scripts.validate_event_points_baseline"] = validate_event_points_baseline


restore(
    globals(),
    "validate_layer1_relations_0826",
    "0d754faafa102692de5d25aa047a88d124de2302dc7590d38e1b94e20b4a5605",
)
