from abc import ABC
from typing import Any, Dict


class RuntimeStep(ABC):
    async def execute(self, config: Dict[str, Any], context: Any) -> Any:
        raise NotImplementedError


BaseStep = RuntimeStep

