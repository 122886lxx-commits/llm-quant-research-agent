from pathlib import Path
from typing import Any, Dict, Union

from ..dsl.parser import PipelineParser
from .registry import get_registry
from .scheduler import PipelineScheduler


class PipelineEngine:
    def __init__(self):
        self.parser = PipelineParser()
        self.registry = get_registry()
        self.scheduler = PipelineScheduler(self.registry)

    async def run_pipeline(self, source: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
        parsed_pipeline = self._load_pipeline(source)
        return await self.scheduler.execute(parsed_pipeline)

    def _load_pipeline(self, source: Union[str, Path, Dict[str, Any]]):
        if isinstance(source, dict):
            return self.parser.parse_dict(source)
        return self.parser.parse_file(source)

