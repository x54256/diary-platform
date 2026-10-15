"""第一层事件关系最终方案入口；纯语义召回、A/B 盲判与 C 分歧裁决。"""

import asyncio

from scripts.historical_layer1_validation import validate_layer1_blind_verify as runner


runner.DEFAULT_OUT = runner.ROOT / "knowledge-graph/validation-2026-08-26/final-relation-scheme"
runner.A_PROMPT = runner.ROOT / "backend/scripts/fixtures/layer1_relation_batch_prompt_v4.txt"
runner.B_PROMPT = runner.ROOT / "backend/scripts/fixtures/layer1_relation_blind_verify_v3.txt"
runner.C_PROMPT = runner.ROOT / "backend/scripts/fixtures/layer1_relation_adjudicate_v3.txt"


if __name__ == "__main__":
    asyncio.run(runner.main())
