from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepSpec:
    id: str
    kind: str
    config: Dict[str, Any] = field(default_factory=dict)
    next: List[str] = field(default_factory=list)
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.kind
        if self.next is None:
            self.next = []
        if isinstance(self.next, str):
            self.next = [self.next]
        else:
            self.next = list(self.next)


@dataclass
class PipelineSpec:
    steps: List[StepSpec]
    pipeline_id: str = "generated_pipeline"
    name: str = "Untitled Pipeline"


Pipeline = PipelineSpec
Step = StepSpec

