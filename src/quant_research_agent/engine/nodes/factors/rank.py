from typing import Any, Dict

from ..base import BaseStep


class RankStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        values = config.get("values", {})
        if not isinstance(values, dict):
            raise ValueError("factor.rank requires a score mapping in config.values")

        descending = bool(config.get("descending", True))
        ordered_pairs = sorted(values.items(), key=lambda item: item[1], reverse=descending)
        ordered = [
            {"symbol": symbol, "score": score, "rank": index}
            for index, (symbol, score) in enumerate(ordered_pairs, start=1)
        ]
        return {"ordered": ordered, "top": [row["symbol"] for row in ordered]}

