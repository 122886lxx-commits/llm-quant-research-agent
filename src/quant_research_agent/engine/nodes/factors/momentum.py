from typing import Any, Dict

from ..base import BaseStep


class MomentumStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        bars = config.get("bars", {})
        if not isinstance(bars, dict):
            raise ValueError("factor.momentum requires grouped bars in config.bars")

        window = int(config.get("window", 3))
        scores: Dict[str, float] = {}
        valid = 0
        for symbol, series in bars.items():
            closes = [item["close"] for item in series][-max(window, 2):] if isinstance(series, list) else []
            if len(closes) < 2:
                continue
            scores[symbol] = round((closes[-1] / closes[0]) - 1.0, 6)
            valid += 1

        coverage = round(valid / len(bars), 6) if bars else 0.0
        return {"scores": scores, "coverage": coverage, "window": window}

