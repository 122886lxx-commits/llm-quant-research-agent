from typing import Any, Dict

from ..base import BaseStep


class ReportStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        return {"sections": config.get("sections", [])}

