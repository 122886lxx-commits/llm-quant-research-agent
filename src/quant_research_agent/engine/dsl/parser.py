from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from .models import Pipeline, StepSpec
from .validator import PipelineValidator


class PipelineParser:
    def __init__(self) -> None:
        self.validator = PipelineValidator()

    def parse_file(self, path: Union[str, Path]) -> Pipeline:
        with open(path, "r", encoding="utf-8") as handle:
            return self.parse_dict(yaml.safe_load(handle))

    def parse_dict(self, data: Dict[str, Any]) -> Pipeline:
        payload = data["pipeline"] if "pipeline" in data else data
        steps = [self._parse_step(item) for item in payload.get("steps", [])]
        pipeline = Pipeline(
            pipeline_id=payload.get("pipeline_id", "generated_pipeline"),
            name=payload.get("name", "Untitled Pipeline"),
            steps=steps,
        )
        self.validator.validate(pipeline)
        return pipeline

    def _parse_step(self, payload: Dict[str, Any]) -> StepSpec:
        return StepSpec(
            id=payload["id"],
            kind=payload["kind"],
            name=payload.get("name"),
            config=dict(payload.get("config", {})),
            next=self._normalize_next(payload.get("next", [])),
        )

    def _normalize_next(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

