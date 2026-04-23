from typing import Any, Dict

from ..base import BaseStep


class ManualTriggerStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        return dict(config)

